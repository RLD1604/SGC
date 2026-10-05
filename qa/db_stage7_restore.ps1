param(
    [Parameter(Mandatory=$true)][string]$WorkDirectory
)

$ErrorActionPreference = 'Stop'
$run = [Guid]::NewGuid().ToString('N').Substring(0,12)
$network = "sgc-stage7-$run"
$db = "sgc-stage7-db-$run"
$app = "sgc-stage7-app-$run"
$project = Split-Path $PSScriptRoot -Parent
$passwordFile = Join-Path $project '.secrets/postgres_password'
$aiKeyFile = Join-Path $project '.secrets/groq_api_key'
$dump = Join-Path $WorkDirectory 'database.dump'
$result = Join-Path $WorkDirectory 'restore-result.json'
$created = [ordered]@{ network=$false; db=$false; app=$false }
$step = 'initialization'

function Invoke-DockerStage7([string[]]$Arguments) {
    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $output = & docker @Arguments 2>&1
        $exitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousPreference
    }
    if ($exitCode -ne 0) { throw "Docker falhou em ${step}: $($output -join [Environment]::NewLine)" }
    return $output
}
try {
    foreach ($path in @($passwordFile,$aiKeyFile,$dump)) {
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Arquivo necessário ausente: $path" }
    }
    $step = 'create_internal_network'
    Invoke-DockerStage7 @('network','create','--internal',$network) | Out-Null
    $created.network = $true
    $step = 'start_database'
    Invoke-DockerStage7 @('run','-d','--name',$db,'--network',$network,'--network-alias','database',
        '--mount',"type=bind,src=$passwordFile,dst=/run/secrets/db_password,readonly",
        '-e','POSTGRES_DB=condominio','-e','POSTGRES_USER=condominio',
        '-e','POSTGRES_PASSWORD_FILE=/run/secrets/db_password','postgres:17-alpine') | Out-Null
    $created.db = $true
    for ($i=0; $i -lt 40; $i++) {
        & docker exec $db pg_isready -U condominio -d condominio *> $null
        if ($LASTEXITCODE -eq 0) { break }
        Start-Sleep -Seconds 1
    }
    if ($LASTEXITCODE -ne 0) { throw 'PostgreSQL descartável não ficou pronto.' }
    $step = 'restore_database'
    Invoke-DockerStage7 @('cp',$dump,"${db}:/tmp/database.dump") | Out-Null
    Invoke-DockerStage7 @('exec',$db,'pg_restore','--list','/tmp/database.dump') | Out-Null
    Invoke-DockerStage7 @('exec',$db,'pg_restore','-U','condominio','-d','condominio','--no-owner','--exit-on-error','/tmp/database.dump') | Out-Null

    $tableCount = (Invoke-DockerStage7 @('exec',$db,'psql','-U','condominio','-d','condominio','-tA','-c',
        "SELECT count(*) FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE';") | Select-Object -Last 1).Trim()
    $invalidIndexes = (Invoke-DockerStage7 @('exec',$db,'psql','-U','condominio','-d','condominio','-tA','-c',
        'SELECT count(*) FROM pg_index WHERE NOT indisvalid OR NOT indisready;') | Select-Object -Last 1).Trim()
    $unvalidatedConstraints = (Invoke-DockerStage7 @('exec',$db,'psql','-U','condominio','-d','condominio','-tA','-c',
        "SELECT count(*) FROM pg_constraint WHERE connamespace='public'::regnamespace AND NOT convalidated;") | Select-Object -Last 1).Trim()
    if ([int]$tableCount -ne 28 -or [int]$invalidIndexes -ne 0 -or [int]$unvalidatedConstraints -ne 0) {
        throw "Integridade estrutural inesperada: tables=$tableCount invalid_indexes=$invalidIndexes unvalidated_constraints=$unvalidatedConstraints"
    }

    $step = 'start_application'
    Invoke-DockerStage7 @('run','-d','--name',$app,'--network',$network,
        '--read-only','--tmpfs','/tmp','--cap-drop','ALL','--security-opt','no-new-privileges:true',
        '--mount',"type=bind,src=$passwordFile,dst=/run/secrets/db_password,readonly",
        '--mount',"type=bind,src=$aiKeyFile,dst=/run/secrets/groq_key,readonly",
        '-e','DB_HOST=database','-e','DB_NAME=condominio','-e','DB_USER=condominio',
        '-e','DB_PASSWORD_FILE=/run/secrets/db_password','-e','GROQ_API_KEY_FILE=/run/secrets/groq_key',
        '-e','AI_FREE_TIER_CONFIRMED=false','sgc-codex:dfa7990') | Out-Null
    $created.app = $true
    $base = $null
    for ($i=0; $i -lt 60; $i++) {
        foreach ($candidate in @('', '/SGC')) {
            $previousPreference = $ErrorActionPreference
            $ErrorActionPreference = 'Continue'
            try {
                & docker exec $app python -c "import json,urllib.request; print(json.load(urllib.request.urlopen('http://127.0.0.1:8080${candidate}/api/health',timeout=2))['status'])" *> $null
                $healthExitCode = $LASTEXITCODE
            } finally {
                $ErrorActionPreference = $previousPreference
            }
            if ($healthExitCode -eq 0) { $base = $candidate; break }
        }
        if ($null -ne $base) { break }
        Start-Sleep -Seconds 1
    }
    if ($null -eq $base) { throw 'Aplicação restaurada não ficou saudável.' }

    $step = 'authentication_smoke'
    $login = "restore.$run"
    $inviteRaw = Invoke-DockerStage7 @('exec',$app,'python','manage_accounts.py','invite','--login',$login,'--name','Restore QA','--role','gestor','--condominium','sqa')
    $invite = ($inviteRaw | Select-Object -Last 1) | ConvertFrom-Json
    $password = "R7!$([Guid]::NewGuid().ToString('N').Substring(0,12))a"
    $baseArgument = if ($base -eq '') { '__ROOT__' } else { $base }
    $authScript = "import json,sys,urllib.request,http.cookiejar; p='' if sys.argv[1]=='__ROOT__' else sys.argv[1]; b='http://127.0.0.1:8080'+p; cj=http.cookiejar.CookieJar(); o=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj)); post=lambda u,x: json.load(o.open(urllib.request.Request(b+u,data=json.dumps(x).encode(),headers={'Content-Type':'application/json'}))); post('/api/auth/activate',{'token':sys.argv[2],'password':sys.argv[3]}); assert post('/api/auth/login',{'login':sys.argv[4],'password':sys.argv[3]})['principal']; assert json.load(o.open(b+'/api/auth/session'))['principal']; print('passed')"
    $authResult = Invoke-DockerStage7 @('exec',$app,'python','-c',$authScript,$baseArgument,$invite.activationToken,$password,$login)
    if (($authResult | Select-Object -Last 1).Trim() -ne 'passed') { throw 'Smoke test de autenticação falhou.' }
    $crossTenant = (Invoke-DockerStage7 @('exec',$db,'psql','-U','condominio','-d','condominio','-tA','-c',
        "SELECT count(*) FROM role_grants rg JOIN memberships m ON m.id=rg.membership_id WHERE rg.condominium_id<>m.condominium_id OR rg.user_id<>m.user_id;") | Select-Object -Last 1).Trim()
    if ([int]$crossTenant -ne 0) { throw 'Inconsistência de isolamento entre condomínios detectada.' }

    [ordered]@{
        passed=$true; image='sgc-codex:dfa7990'; health='ok'; auth='passed'; isolation='passed'
        restoredPublicTables=[int]$tableCount; invalidIndexes=[int]$invalidIndexes
        unvalidatedConstraints=[int]$unvalidatedConstraints; exposedPorts=0; internalNetwork=$true
    } | ConvertTo-Json | Set-Content -LiteralPath $result -Encoding UTF8
}
catch {
    [ordered]@{passed=$false; failedStep=$step; error=$_.Exception.Message} | ConvertTo-Json | Set-Content -LiteralPath $result -Encoding UTF8
    throw
}
finally {
    if ($created.app) { & docker rm -f $app *> $null }
    if ($created.db) { & docker rm -f $db *> $null }
    if ($created.network) { & docker network rm $network *> $null }
}

