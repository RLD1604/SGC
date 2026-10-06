#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
# Report only line and exit status; commands/configuration can contain secrets.
trap 'rc=$?; printf "SGC_BACKUP_ERROR line=%s exit=%s\n" "$LINENO" "$rc" >&2; exit "$rc"' ERR

CONFIG=${SGC_BACKUP_CONFIG:-/etc/sgc-backup/sgc-backup.conf}
[[ -r "$CONFIG" ]] || { echo "Configuração ausente: $CONFIG" >&2; exit 2; }
# shellcheck source=/dev/null
source "$CONFIG"

: "${BACKUP_ROOT:?}"
: "${DB_CONTAINER:?}"
: "${APP_CONTAINER:?}"
: "${DB_NAME:?}"
: "${DB_USER:?}"
: "${POSTGRES_IMAGE:=postgres:17}"
: "${AGE_RECIPIENT:?Defina AGE_RECIPIENT}"
: "${STAGING_ROOT:=/run/sgc-backup}"

for command_name in docker age sha256sum jq tar; do
  command -v "$command_name" >/dev/null || { echo "Dependência ausente: $command_name" >&2; exit 3; }
done

run_id=$(date -u +%Y%m%dT%H%M%SZ)-$(od -An -N4 -tx1 /dev/urandom | tr -d ' \n')
final_dir="$BACKUP_ROOT/$run_id"
stage="$STAGING_ROOT/$run_id"
restore_name="sgc-backup-verify-$run_id"
accepted=false

cleanup() {
  docker rm -f "$restore_name" >/dev/null 2>&1 || true
  if [[ -d "$stage" ]]; then
    find "$stage" -type f -exec chmod 0600 {} + 2>/dev/null || true
    rm -rf -- "$stage"
  fi
  if [[ "$accepted" != true && -d "$final_dir" ]]; then
    mv -- "$final_dir" "$BACKUP_ROOT/rejected-$run_id"
  fi
}
trap cleanup EXIT

install -d -m 0700 "$BACKUP_ROOT" "$STAGING_ROOT" "$stage"
[[ ! -e "$final_dir" && ! -e "$BACKUP_ROOT/rejected-$run_id" ]] || { echo "Execução já existe: $run_id" >&2; exit 4; }

db_state=$(docker inspect -f '{{.State.Running}}' "$DB_CONTAINER")
app_state=$(docker inspect -f '{{.State.Running}}' "$APP_CONTAINER")
[[ "$db_state" == true && "$app_state" == true ]] || { echo "SGC não está totalmente em execução" >&2; exit 5; }

dump="$stage/database.dump"
docker exec "$DB_CONTAINER" pg_dump \
  --username="$DB_USER" --dbname="$DB_NAME" \
  --format=custom --compress=9 --no-password >"$dump"
[[ -s "$dump" ]]
docker exec -i "$DB_CONTAINER" pg_restore --list <"$dump" >/dev/null

# Restaura em um banco efêmero, sem porta publicada e sem rede compartilhada.
docker run -d --name "$restore_name" --network none \
  -e POSTGRES_HOST_AUTH_METHOD=trust -e POSTGRES_DB="$DB_NAME" \
  -e POSTGRES_USER="$DB_USER" "$POSTGRES_IMAGE" >/dev/null
for _ in $(seq 1 60); do
  if docker exec "$restore_name" pg_isready -U "$DB_USER" -d "$DB_NAME" >/dev/null 2>&1; then break; fi
  sleep 1
done
docker exec "$restore_name" pg_isready -U "$DB_USER" -d "$DB_NAME" >/dev/null
docker exec -i "$restore_name" pg_restore --exit-on-error --no-owner --no-privileges \
  -U "$DB_USER" -d "$DB_NAME" <"$dump"
table_count=$(docker exec "$restore_name" psql -XAt -U "$DB_USER" -d "$DB_NAME" \
  -c "select count(*) from information_schema.tables where table_schema='public' and table_type='BASE TABLE'")
[[ "$table_count" =~ ^[0-9]+$ && "$table_count" -gt 0 ]]
docker rm -f "$restore_name" >/dev/null

# Rejeita imagens que tenham valores de segredos em ENV. Variáveis de conexão
# devem ser injetadas apenas no contêiner em tempo de execução.
image_ref=$(docker inspect -f '{{.Config.Image}}' "$APP_CONTAINER")
image_id=$(docker image inspect -f '{{.Id}}' "$image_ref")
if docker image inspect "$image_ref" | jq -e '
  .[0].Config.Env // [] | map(select(test("^(.*_)?(PASSWORD|PASSWD|TOKEN|SECRET|PRIVATE_KEY|API_KEY)="; "i"))) | length > 0
' >/dev/null; then
  echo "A imagem contém variável ENV com possível segredo; backup abortado" >&2
  exit 6
fi

docker image save "$image_ref" -o "$stage/application-image.tar"
docker inspect "$APP_CONTAINER" | jq '.[0] | {
  name: .Name, image: .Config.Image, image_id: .Image,
  entrypoint: .Config.Entrypoint, cmd: .Config.Cmd, healthcheck: .Config.Healthcheck,
  labels: .Config.Labels, restart_policy: .HostConfig.RestartPolicy,
  resources: {memory: .HostConfig.Memory, nano_cpus: .HostConfig.NanoCpus},
  networks: (.NetworkSettings.Networks | keys),
  mounts: [.Mounts[] | {type: .Type, destination: .Destination, name: .Name}]
}' >"$stage/application-runtime-sanitized.json"

cat >"$stage/RESTORE.txt" <<'EOF'
1. Decifre os arquivos somente em host isolado.
2. Carregue a imagem com: docker image load -i application-image.tar
3. Restaure database.dump em um PostgreSQL vazio com pg_restore --exit-on-error.
4. Recrie redes, volume e contêiner usando configuração operacional custodiada separadamente.
5. Injete senhas de banco/IA a partir do cofre. Se existir credentials/, restaure
   owner_totp e user_mfa_key em arquivos privados e montagens somente leitura.
6. Valide saúde, contagens, login e mídia antes de publicar tráfego.
EOF

dump_sha=$(sha256sum "$dump" | awk '{print $1}')
image_sha=$(sha256sum "$stage/application-image.tar" | awk '{print $1}')
cat >"$stage/manifest.json" <<EOF
{"format_version":1,"run_id":"$run_id","created_utc":"$(date -u +%FT%TZ)","database":{"name":"$DB_NAME","sha256":"$dump_sha","restore_tested":true,"restored_public_tables":$table_count},"application":{"image_ref":"$image_ref","image_id":"$image_id","archive_sha256":"$image_sha","runtime_metadata_sanitized":true},"encryption":"age","retention_mode":"report-only"}
EOF

archive_files=(database.dump application-image.tar application-runtime-sanitized.json RESTORE.txt manifest.json)
# MFA keys are recovery-critical. Include them ONLY inside the age-encrypted
# package, never in the external manifest, image, logs or Git.
secret_root=${MFA_SECRET_ROOT:-/opt/sgc-codex-20260925/runtime-secrets}
if [[ -r "$secret_root/user-mfa-app" ]]; then
  [[ -r "$secret_root/owner-app" ]] || { echo 'Chave MFA do dono ausente; backup abortado' >&2; exit 7; }
  install -d -m 0700 "$stage/credentials"
  install -m 0600 "$secret_root/user-mfa-app" "$stage/credentials/user_mfa_key"
  install -m 0600 "$secret_root/owner-app" "$stage/credentials/owner_totp"
  archive_files+=(credentials)
fi
tar --format=posix -C "$stage" -cf "$stage/sgc-recovery.tar" "${archive_files[@]}"
age -r "$AGE_RECIPIENT" -o "$stage/sgc-recovery.tar.age" "$stage/sgc-recovery.tar"
(
  cd "$stage"
  sha256sum sgc-recovery.tar.age >sgc-recovery.tar.age.sha256
)

install -d -m 0700 "$final_dir"
install -m 0600 "$stage/sgc-recovery.tar.age" "$final_dir/"
install -m 0600 "$stage/sgc-recovery.tar.age.sha256" "$final_dir/"
install -m 0600 "$stage/manifest.json" "$final_dir/"
printf '%s\n' "$run_id" >"$final_dir/SUCCESS"
chmod 0600 "$final_dir/SUCCESS"
ln -s "$run_id" "$BACKUP_ROOT/.latest-$run_id"
mv -Tf "$BACKUP_ROOT/.latest-$run_id" "$BACKUP_ROOT/latest"
accepted=true
echo "Backup aceito: $final_dir"
