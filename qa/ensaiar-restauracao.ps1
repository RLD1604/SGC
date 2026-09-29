param(
    [Parameter(Mandatory=$true)]
    [ValidateScript({ Test-Path $_ -PathType Leaf })]
    [string]$DumpPath
)

# Windows PowerShell 5.1. Read-only against condominio; writes only qa_restore_<32hex>.
$ErrorActionPreference='Stop'
$qaRoot=$PSScriptRoot
$projectRoot=Split-Path $qaRoot -Parent
$resultsRoot=Join-Path $qaRoot 'results/restauracao'
New-Item -ItemType Directory -Force -Path $resultsRoot | Out-Null
$runId=[Guid]::NewGuid().ToString('N')
$qaDb='qa_restore_'+$runId
$qaContainer='qa-restore-'+$runId.Substring(0,12)
$containerDump='/tmp/qa-restore-'+$runId+'.dump'
$resultPath=Join-Path $resultsRoot ('restauracao-'+$runId+'.json')
$dbCreated=$false
$candidateStarted=$false
$databaseContainer=$null

function Invoke-Docker {
    param([string[]]$DockerArgs)
    $oldPreference=$ErrorActionPreference
    $ErrorActionPreference='Continue'
    try { $output=& docker @DockerArgs 2>&1 } finally { $ErrorActionPreference=$oldPreference }
    if($LASTEXITCODE -ne 0){ throw ('Falha no Docker: '+($output -join [Environment]::NewLine)) }
    return $output
}

function Invoke-PsqlJson {
    param([string]$Database,[string]$Sql)
    $output=Invoke-Docker @('exec',$databaseContainer,'psql','-U','condominio','-d',$Database,'-tA','-c',$Sql)
    $line=($output | Where-Object { $_ -match '^\{' } | Select-Object -Last 1)
    if(!$line){ throw 'A consulta de comparação não retornou JSON.' }
    return ($line | ConvertFrom-Json)
}

try {
    $resolvedDump=(Resolve-Path $DumpPath).Path
    $composeFile=Join-Path $projectRoot 'compose.yaml'

    $databaseContainer=(Invoke-Docker @('compose','-f',$composeFile,'ps','-q','database') | Select-Object -Last 1).Trim()
    if(!$databaseContainer){ throw 'O contêiner PostgreSQL principal não foi encontrado.' }

    # Validate the archive in the existing PostgreSQL container before creating any temporary database.
    Invoke-Docker @('cp',$resolvedDump,($databaseContainer+':'+$containerDump)) | Out-Null
    Invoke-Docker @('exec',$databaseContainer,'pg_restore','--list',$containerDump) | Out-Null

    Invoke-Docker @('exec',$databaseContainer,'createdb','-U','condominio',$qaDb) | Out-Null
    $dbCreated=$true
    Invoke-Docker @('exec',$databaseContainer,'pg_restore','-U','condominio','--exit-on-error','-d',$qaDb,$containerDump) | Out-Null

    $summarySql=@'
SELECT json_build_object(
  'revision',(SELECT revision FROM workspace_state WHERE id=1),
  'records',(SELECT count(*) FROM records),
  'record_ids',(SELECT md5(coalesce(string_agg(id,',' ORDER BY id),'')) FROM records),
  'editions',(SELECT count(*) FROM editions),
  'edition_ids',(SELECT md5(coalesce(string_agg(id,',' ORDER BY id),'')) FROM editions),
  'publications',(SELECT count(*) FROM publications),
  'publication_ids',(SELECT md5(coalesce(string_agg(id,',' ORDER BY id),'')) FROM publications),
  'media',(SELECT count(*) FROM media),
  'media_ids',(SELECT md5(coalesce(string_agg(id,',' ORDER BY id),'')) FROM media),
  'media_bytes',(SELECT coalesce(sum(octet_length(content)),0) FROM media)
);
'@
    $origin=Invoke-PsqlJson -Database 'condominio' -Sql $summarySql
    $restoredBeforeMigration=Invoke-PsqlJson -Database $qaDb -Sql $summarySql
    $matches=@{}
    foreach($property in $origin.PSObject.Properties.Name){ $matches[$property]=($origin.$property -eq $restoredBeforeMigration.$property) }
    if(($matches.Values | Where-Object { -not $_ }).Count -gt 0){ throw 'A cópia restaurada diverge da origem antes da migração.' }

    Invoke-Docker @('compose','-f',$composeFile,'run','-d','--no-deps','--name',$qaContainer,'-p','127.0.0.1:19001:8080','-e',('DB_NAME='+$qaDb),'-e','AI_FREE_TIER_CONFIRMED=false','prototipo') | Out-Null
    $candidateStarted=$true
    $health=$null
    for($attempt=0;$attempt -lt 45;$attempt++){
        try { $health=Invoke-RestMethod -Uri 'http://localhost:19001/api/health' -TimeoutSec 3 } catch { $health=$null }
        if($health -and $health.status -eq 'ok'){ break }
        Start-Sleep -Seconds 1
    }
    if(!$health -or $health.status -ne 'ok'){ throw 'A candidata restaurada não respondeu saudável na porta 19001.' }
    $schemaV4=Invoke-Docker @('exec',$databaseContainer,'psql','-U','condominio','-d',$qaDb,'-tA','-c','SELECT count(*) FROM schema_versions WHERE version=4')
    $schemaV4Count=[int](($schemaV4 | Select-Object -Last 1).Trim())
    if($schemaV4Count -ne 1){ throw 'A migração v4 não foi registrada exatamente uma vez.' }
    $restoredAfterMigration=Invoke-PsqlJson -Database $qaDb -Sql $summarySql

    [ordered]@{
        runId=$runId; dump=$resolvedDump; qaDatabase=$qaDb; candidateContainer=$qaContainer
        health=$health; schemaV4Count=$schemaV4Count; origin=$origin
        restoredBeforeMigration=$restoredBeforeMigration; restoredAfterMigration=$restoredAfterMigration
        matchesBeforeMigration=$matches; passed=$true
    } | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $resultPath -Encoding UTF8
    Write-Output "Ensaio concluído: $resultPath"
}
catch {
    [ordered]@{runId=$runId; qaDatabase=$qaDb; candidateContainer=$qaContainer; passed=$false; error=$_.Exception.Message} |
        ConvertTo-Json | Set-Content -LiteralPath $resultPath -Encoding UTF8
    throw
}
finally {
    if($candidateStarted -and $qaContainer -match '^qa-restore-[a-f0-9]{12}$'){ & docker rm -f $qaContainer | Out-Null }
    if($databaseContainer -and $containerDump -match '^/tmp/qa-restore-[a-f0-9]{32}\.dump$'){ & docker exec $databaseContainer rm -f $containerDump | Out-Null }
    if($dbCreated -and $databaseContainer -and $qaDb -match '^qa_restore_[a-f0-9]{32}$'){ & docker exec $databaseContainer dropdb -U condominio $qaDb | Out-Null }
}
