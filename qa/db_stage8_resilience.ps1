param([Parameter(Mandatory=$true)][string]$WorkDirectory)

$ErrorActionPreference='Stop'
$run=[Guid]::NewGuid().ToString('N').Substring(0,12)
$db="sgc-stage8-db-$run"
$network="sgc-stage8-$run"
$project=Split-Path $PSScriptRoot -Parent
$passwordFile=Join-Path $project '.secrets/postgres_password'
$dump=Join-Path $WorkDirectory 'database.dump'
$benchFile=Join-Path $WorkDirectory 'stage8-pgbench.sql'
$result=Join-Path $WorkDirectory 'stage8-result.json'
$created=[ordered]@{network=$false;db=$false}
$step='initialization'

function Invoke-DockerStage8([string[]]$Arguments) {
    $previous=$ErrorActionPreference; $ErrorActionPreference='Continue'
    try { $output=& docker @Arguments 2>&1; $exit=$LASTEXITCODE }
    finally { $ErrorActionPreference=$previous }
    if($exit -ne 0){ throw "Docker falhou em ${step}: $($output -join [Environment]::NewLine)" }
    return $output
}

try {
    if(!(Test-Path $passwordFile) -or !(Test-Path $dump)){throw 'Entradas obrigatórias ausentes.'}
    @'
BEGIN;
SELECT revision FROM workspace_state WHERE id=1;
SELECT count(*) FROM records;
INSERT INTO qa_stage8_counter(id,value) VALUES (1,1)
ON CONFLICT (id) DO UPDATE SET value=qa_stage8_counter.value+1;
COMMIT;
'@ | Set-Content -LiteralPath $benchFile -Encoding ascii

    $step='create_internal_network'; Invoke-DockerStage8 @('network','create','--internal',$network)|Out-Null; $created.network=$true
    $step='start_database'; Invoke-DockerStage8 @('run','-d','--name',$db,'--network',$network,
      '--mount',"type=bind,src=$passwordFile,dst=/run/secrets/db_password,readonly",
      '-e','POSTGRES_DB=condominio','-e','POSTGRES_USER=condominio','-e','POSTGRES_PASSWORD_FILE=/run/secrets/db_password',
      'postgres:17-alpine')|Out-Null; $created.db=$true
    for($i=0;$i-lt 40;$i++){& docker exec $db pg_isready -U condominio -d condominio *> $null;if($LASTEXITCODE-eq 0){break};Start-Sleep 1}
    if($LASTEXITCODE-ne 0){throw 'Banco descartável não ficou pronto.'}
    $step='restore'; Invoke-DockerStage8 @('cp',$dump,"${db}:/tmp/database.dump")|Out-Null
    Invoke-DockerStage8 @('exec',$db,'pg_restore','--list','/tmp/database.dump')|Out-Null
    Invoke-DockerStage8 @('exec',$db,'pg_restore','-U','condominio','-d','condominio','--no-owner','--exit-on-error','/tmp/database.dump')|Out-Null
    Invoke-DockerStage8 @('exec',$db,'psql','-U','condominio','-d','condominio','-v','ON_ERROR_STOP=1','-c','CREATE TABLE qa_stage8_counter(id integer PRIMARY KEY,value bigint NOT NULL DEFAULT 0);')|Out-Null
    Invoke-DockerStage8 @('cp',$benchFile,"${db}:/tmp/stage8-pgbench.sql")|Out-Null

    $step='concurrent_workload'
    $bench=Invoke-DockerStage8 @('exec',$db,'pgbench','-U','condominio','-n','-c','8','-j','4','-T','15','-f','/tmp/stage8-pgbench.sql','condominio')
    $benchText=$bench -join "`n"
    $failed=[regex]::Match($benchText,'number of failed transactions:\s+(\d+)').Groups[1].Value
    if($failed-eq ''){$failed='0'}
    $tpsMatch=[regex]::Match($benchText,'tps = ([0-9.]+)')
    $latencyMatch=[regex]::Match($benchText,'latency average = ([0-9.]+) ms')
    $transactions=(Invoke-DockerStage8 @('exec',$db,'psql','-U','condominio','-d','condominio','-tA','-c','SELECT value FROM qa_stage8_counter WHERE id=1;')|Select-Object -Last 1).Trim()
    $metricsRaw=(Invoke-DockerStage8 @('exec',$db,'psql','-U','condominio','-d','condominio','-tA','-F','|','-c',
      "SELECT pg_database_size(current_database()),(SELECT count(*) FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE'),(SELECT count(*) FROM pg_index WHERE NOT indisvalid OR NOT indisready),(SELECT count(*) FROM pg_constraint WHERE connamespace='public'::regnamespace AND NOT convalidated),(SELECT setting::int FROM pg_settings WHERE name='max_connections'),(SELECT count(*) FROM pg_stat_activity WHERE datname=current_database());")|Select-Object -Last 1)
    $metrics=$metricsRaw.Trim().Split('|')
    if([int]$failed-ne 0 -or [int64]$transactions-le 0 -or [int]$metrics[1]-lt 28 -or [int]$metrics[2]-ne 0 -or [int]$metrics[3]-ne 0){throw 'Critério de resiliência ou integridade reprovado.'}
    [ordered]@{passed=$true;clients=8;threads=4;durationSeconds=15;failedTransactions=[int]$failed;
      completedTransactions=[int64]$transactions;tps=if($tpsMatch.Success){[double]$tpsMatch.Groups[1].Value}else{$null};
      averageLatencyMs=if($latencyMatch.Success){[double]$latencyMatch.Groups[1].Value}else{$null};
      databaseBytes=[int64]$metrics[0];publicTables=[int]$metrics[1];invalidIndexes=[int]$metrics[2];
      unvalidatedConstraints=[int]$metrics[3];maxConnections=[int]$metrics[4];observedConnections=[int]$metrics[5];
      productionWrites=0;internalNetwork=$true;exposedPorts=0}|ConvertTo-Json|Set-Content $result -Encoding UTF8
}
catch { [ordered]@{passed=$false;failedStep=$step;error=$_.Exception.Message}|ConvertTo-Json|Set-Content $result -Encoding UTF8; throw }
finally {
    if($created.db){& docker rm -f $db *> $null}
    if($created.network){& docker network rm $network *> $null}
    if(Test-Path $benchFile){Remove-Item -LiteralPath $benchFile -Force}
}
