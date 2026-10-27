#!/usr/bin/env bash
# Publica a manutenção 0.2.7-beta.4 (Python 3.12.16, Pillow 13.0.0, psycopg2 2.9.13, TinyMCE 8.10.0).
# Mesmo desenho do pre-entrega-20261006.sh: renomeia o contêiner atual para rollback,
# cria o novo com as mesmas proteções e volta sozinho se qualquer conferência falhar.
# Diferenças: IP do proxy lido do Traefik no momento (era fixo em 172.18.0.5 e o Traefik
# passou a 172.18.0.2) e cabeçalho HSTS opcional via rótulos (ENABLE_HSTS=1).
set -Eeuo pipefail

root=/opt/sgc-codex-20260925
image=sgc-codex:manut-20261027
expected_image_id=sha256:33c9e9e8bbb367e3a96e455836087a55d4115bf5d864669870945d48513a928e
expected_version=0.2.7-beta.4
[ "$(docker image inspect -f '{{.Id}}' "$image")" = "$expected_image_id" ] || { echo 'Candidate image mismatch; refusing deploy.' >&2; exit 23; }
app=sgc-codex-app
old=sgc-codex-app-pre-manut-20261027
evidence="$root/evidence/manut-20261027"
mkdir -p "$evidence"
proxy_ip=$(docker inspect root-traefik-1 --format '{{(index .NetworkSettings.Networks "root_default").IPAddress}}')
[[ "$proxy_ip" =~ ^172\.18\.[0-9]+\.[0-9]+$ ]] || { echo "Unexpected proxy address; revalidate trust before deploy." >&2; exit 21; }

hsts_labels=()
if [ "${ENABLE_HSTS:-0}" = 1 ]; then
  hsts_labels=(
    --label traefik.http.middlewares.sgc-hsts.headers.stsSeconds=31536000
    --label traefik.http.routers.sgc-codex.middlewares=sgc-hsts
  )
fi

fetch_health() {
  url=$1
  destination=$2
  rm -f "$destination" "$destination.tmp"
  for _ in $(seq 1 20); do
    if curl --fail --silent --show-error "$url" > "$destination.tmp"; then
      mv "$destination.tmp" "$destination"
      return 0
    fi
    sleep 2
  done
  return 1
}

docker inspect "$app" > "$evidence/container-before.json"
docker ps --format '{{.Names}}\t{{.Image}}\t{{.Status}}' > "$evidence/containers-before.txt"
curl --fail --silent --show-error http://127.0.0.1:9001/api/health > "$evidence/local-health-before.json"
fetch_health https://sq.srv1178310.hstgr.cloud/SGC/api/health "$evidence/public-health-before.json"

if docker container inspect "$old" >/dev/null 2>&1; then
  echo "Rollback container $old already exists; refusing to overwrite it." >&2
  exit 20
fi

rollback() {
  rc=$?
  trap - EXIT
  if [ "$rc" -ne 0 ]; then
    # Old name was absent at preflight: its presence proves our rename happened.
    if docker container inspect "$old" >/dev/null 2>&1; then
      if docker container inspect "$app" >/dev/null 2>&1; then
        docker stop "$app" >/dev/null 2>&1 || true
        docker rename "$app" "$app-failed-manut-20261027" >/dev/null 2>&1 || true
      fi
      docker rename "$old" "$app" >/dev/null 2>&1 || true
    fi
    docker start "$app" >/dev/null 2>&1 || true
  fi
  exit "$rc"
}
trap rollback EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

docker stop "$app" >/dev/null
docker rename "$app" "$old"

docker create \
  --name "$app" \
  --restart unless-stopped \
  --memory 512m \
  --cpus .75 \
  --pids-limit 256 \
  --read-only \
  --tmpfs /tmp:rw,noexec,nosuid,size=64m \
  --cap-drop ALL \
  --security-opt no-new-privileges:true \
  --network sgc-codex_private \
  --publish 127.0.0.1:9001:8080 \
  --mount type=bind,src="$root/runtime-secrets/db-app",dst=/run/secrets/db_password,readonly \
  --mount type=bind,src="$root/runtime-secrets/groq-app",dst=/run/secrets/groq_key,readonly \
  --env DB_HOST=database \
  --env DB_NAME=condominio \
  --env DB_USER=condominio \
  --env DB_PASSWORD_FILE=/run/secrets/db_password \
  --env GROQ_API_KEY_FILE=/run/secrets/groq_key \
  --env AI_FREE_TIER_CONFIRMED=true \
  --env APP_BASE_PATH=/SGC \
  --env AUTH_COOKIE_SECURE=true \
  --env AUTH_TRUSTED_PROXY_IPS="$proxy_ip" \
  --env OWNER_TOTP_FILE=/run/secrets/owner_totp \
  --env USER_MFA_KEY_FILE=/run/secrets/user_mfa_key \
  --env OWNER_BACKUP_STATUS_FILE=/runtime-status/backup.json \
  --mount type=bind,src="$root/runtime-secrets/owner-app",dst=/run/secrets/owner_totp,readonly \
  --mount type=bind,src="$root/runtime-secrets/user-mfa-app",dst=/run/secrets/user_mfa_key,readonly \
  --mount type=bind,src="$root/runtime-status",dst=/runtime-status,readonly \
  --label com.docker.compose.project=sgc-codex \
  --label com.docker.compose.service=app \
  --label traefik.enable=true \
  --label traefik.docker.network=root_default \
  --label 'traefik.http.routers.sgc-codex.rule=Host(`sq.srv1178310.hstgr.cloud`) && (Path(`/SGC`) || PathPrefix(`/SGC/`))' \
  --label traefik.http.routers.sgc-codex.priority=200 \
  --label traefik.http.routers.sgc-codex.entrypoints=websecure \
  --label traefik.http.routers.sgc-codex.tls=true \
  --label traefik.http.routers.sgc-codex.tls.certresolver=mytlschallenge \
  --label traefik.http.services.sgc-codex.loadbalancer.server.port=8080 \
  "${hsts_labels[@]}" \
  "$image" >/dev/null

docker network connect sgc-codex_egress "$app"
docker network connect root_default "$app"
docker start "$app" >/dev/null

for _ in $(seq 1 60); do
  state=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$app")
  [ "$state" = healthy ] && break
  sleep 2
done
[ "$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$app")" = healthy ]

test "$(docker exec sgc-codex-database psql -U condominio -d condominio -tA -c "SELECT count(*) FROM platform_owner_grants WHERE revoked_at IS NULL;")" = 1
curl --fail --silent --show-error http://127.0.0.1:9001/api/health > "$evidence/local-health-after.json"
fetch_health https://sq.srv1178310.hstgr.cloud/SGC/api/health "$evidence/public-health-after.json"
curl --fail --silent --show-error https://sq.srv1178310.hstgr.cloud/SGC/version.json > "$evidence/public-version-after.json"
[ "$(jq -r .version "$evidence/public-version-after.json")" = "$expected_version" ]
schema=$(docker exec sgc-codex-database psql -U condominio -d condominio -tA -c 'SELECT max(version) FROM schema_versions;')
trigger=$(docker exec sgc-codex-database psql -U condominio -d condominio -tA -c "SELECT count(*) FROM pg_trigger WHERE tgname='audit_events_immutable' AND NOT tgisinternal;")
[ "$schema" = 11 ]
[ "$trigger" = 1 ]
printf 'schema=%s\naudit_trigger=%s\nproxy_ip=%s\nhsts=%s\n' "$schema" "$trigger" "$proxy_ip" "${ENABLE_HSTS:-0}" > "$evidence/database-validation.txt"
docker inspect "$app" > "$evidence/container-after.json"
docker ps --format '{{.Names}}\t{{.Image}}\t{{.Status}}' > "$evidence/containers-after.txt"
sha256sum "$evidence"/* > "$evidence/SHA256SUMS"
printf 'SUCCESS\n' > "$evidence/SUCCESS"
trap - EXIT
printf 'DEPLOY_OK image=%s rollback=%s evidence=%s\n' "$image" "$old" "$evidence"
