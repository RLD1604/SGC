$ErrorActionPreference = 'Stop'
$project = Split-Path $PSScriptRoot -Parent
$nonce = [Guid]::NewGuid().ToString('N').Substring(0,12)
$prefix = "sgc-preentrega-media-$nonce"
$network = "$prefix-net"
$db = "$prefix-db"
$sourceDb = 'sgc_owner_qa_maverick_preentrega20261006_final'
$targetDb = 'sgc_owner_qa_maverick_restore20261006'
$sourceContainer = 'sistema-gestao-comunicacao-condominio-database-1'
$work = Join-Path $project ".secrets/$prefix"
$expectedRoot = [IO.Path]::GetFullPath((Join-Path $project '.secrets')) + [IO.Path]::DirectorySeparatorChar
if (-not [IO.Path]::GetFullPath($work).StartsWith($expectedRoot)) { throw 'Private staging outside workspace' }
$sourceDump = "/tmp/$prefix.dump"
$createdNet = $false
$createdDb = $false
$step = 'private_staging'
function Invoke-RestoreDocker([string[]]$Arguments) {
    $output = & docker @Arguments 2>&1
    if ($LASTEXITCODE -ne 0) { throw "Docker failed at $step" }
    return $output
}
try {
    New-Item -ItemType Directory -Path $work | Out-Null
    & icacls $work /inheritance:r /grant:r "${env:USERNAME}:(OI)(CI)F" *> $null
    if ($LASTEXITCODE -ne 0) { throw 'Private staging ACL failed' }
    $common = @('--rm','--read-only','--tmpfs','/tmp','--cap-drop','ALL','--security-opt','no-new-privileges:true',
        '--mount',"type=bind,source=$project,target=/app,readonly",'--workdir','/app',
        '--mount',"type=bind,source=$work,target=/verify",
        '--mount',"type=bind,source=$project/.secrets/postgres_password,target=/run/secrets/db,readonly",
        '--mount',"type=bind,source=$project/.secrets/user_mfa_key,target=/run/secrets/mfa,readonly",
        '--mount',"type=bind,source=$project/.secrets/qa_preentrega_finalcredentials.json,target=/verify/credentials.json,readonly",
        '--mount',"type=bind,source=$project/.secrets/qa_preentrega_finalsessions.json,target=/verify/sessions.json,readonly",
        '-e','DB_USER=condominio','-e','DB_PASSWORD_FILE=/run/secrets/db','-e','USER_MFA_KEY_FILE=/run/secrets/mfa',
        '-e','PYTHONPATH=/app')
    $step = 'source_baseline'
    $baseline = Invoke-RestoreDocker (@('run','--name',"$prefix-baseline",'--network','sistema-gestao-comunicacao-condominio_default') + $common + @('-e',"DB_HOST=$sourceContainer",'-e',"DB_NAME=$sourceDb",'-e','QA_RESTORE_MODE=baseline','sgc-codex:pre-entrega-20261006','python','qa/pre_delivery_media_restore.py'))
    $baseline | Set-Content (Join-Path $project 'qa/results/pre-entrega-20261006/media-restore-baseline.json')
    $step = 'qa_dump'
    Invoke-RestoreDocker @('exec',$sourceContainer,'pg_dump','-U','condominio','-d',$sourceDb,'-Fc','-f',$sourceDump) | Out-Null
    Invoke-RestoreDocker @('exec',$sourceContainer,'chmod','0600',$sourceDump) | Out-Null
    Invoke-RestoreDocker @('cp',"${sourceContainer}:$sourceDump",(Join-Path $work 'database.dump')) | Out-Null
    $step = 'isolated_database'
    Invoke-RestoreDocker @('network','create','--internal',$network) | Out-Null
    $createdNet = $true
    Invoke-RestoreDocker @('run','-d','--name',$db,'--network',$network,'--network-alias','database',
        '--mount',"type=bind,source=$project/.secrets/postgres_password,target=/run/secrets/db,readonly",
        '-e',"POSTGRES_DB=$targetDb",'-e','POSTGRES_USER=condominio','-e','POSTGRES_PASSWORD_FILE=/run/secrets/db','postgres:17-alpine') | Out-Null
    $createdDb = $true
    for ($i=0;$i -lt 40;$i++) {
        & docker exec $db pg_isready -U condominio -d $targetDb *> $null
        if ($LASTEXITCODE -eq 0) { break }
        Start-Sleep -Seconds 1
    }
    if ($LASTEXITCODE -ne 0) { throw 'Isolated database not ready' }
    $step = 'restore'
    Invoke-RestoreDocker @('cp',(Join-Path $work 'database.dump'),"${db}:/tmp/database.dump") | Out-Null
    Invoke-RestoreDocker @('exec',$db,'pg_restore','-U','condominio','-d',$targetDb,'--exit-on-error','--no-owner','--no-privileges','/tmp/database.dump') | Out-Null
    $step = 'restored_verification'
    $verified = Invoke-RestoreDocker (@('run','--name',"$prefix-verify",'--network',$network) + $common + @('-e','DB_HOST=database','-e',"DB_NAME=$targetDb",'-e','QA_RESTORE_MODE=verify','sgc-codex:pre-entrega-20261006','python','qa/pre_delivery_media_restore.py'))
    $verified | Set-Content (Join-Path $project 'qa/results/pre-entrega-20261006/media-restore-result.json')
    $verified
} catch {
    @{passed=$false;failedStep=$step;errorType=$_.Exception.GetType().Name} | ConvertTo-Json -Compress
    throw "Isolated QA media restoration failed at $step"
} finally {
    if ($createdDb) { & docker rm -f -v $db *> $null }
    if ($createdNet) { & docker network rm $network *> $null }
    & docker exec $sourceContainer rm -f -- $sourceDump *> $null
    if ((Test-Path -LiteralPath $work) -and [IO.Path]::GetFullPath($work).StartsWith($expectedRoot)) {
        Remove-Item -LiteralPath $work -Recurse -Force
    }
}
