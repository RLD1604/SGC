param()
$ErrorActionPreference='Stop'
$qaRoot=$PSScriptRoot
$projectRoot=Split-Path $qaRoot -Parent
$linuxProject=(wsl -d Ubuntu -- wslpath -a -u $projectRoot.Replace('\','/')).Trim()
if($LASTEXITCODE -ne 0){throw 'WSL indisponível'}
$composeFile="$linuxProject/compose.yaml"
$qaDb='sqa_intensive_'+[Guid]::NewGuid().ToString('N')
$qaContainer='sqa-intensive-'+[Guid]::NewGuid().ToString('N').Substring(0,12)
$logDir=Join-Path $qaRoot 'results/intensive'
New-Item -ItemType Directory -Force $logDir | Out-Null
$env:PLAYWRIGHT_MODULE='C:\Users\roddr\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\node_modules\playwright'
$env:QA_URL='http://localhost:19001'
if(!(Test-Path $env:PLAYWRIGHT_MODULE)){throw 'Runtime Playwright não encontrado'}
$dbCreated=$false
$testExit=1
try {
 wsl -d Ubuntu -- docker compose -f $composeFile exec -T database createdb -U condominio $qaDb
 if($LASTEXITCODE -ne 0){throw 'Não foi possível criar banco temporário'}
 $dbCreated=$true
 wsl -d Ubuntu -- docker compose -f $composeFile run -d --no-deps --name $qaContainer -p 127.0.0.1:19001:8080 -e "DB_NAME=$qaDb" -e AI_FREE_TIER_CONFIRMED=false prototipo
 if($LASTEXITCODE -ne 0){throw 'Não foi possível iniciar a cópia; verifique se a porta 19001 está livre'}
 $ready=$false
 for($attempt=0;$attempt -lt 30;$attempt++){
  try{$health=Invoke-RestMethod http://localhost:19001/api/health;if($health.status -eq 'ok'){$ready=$true;break}}catch{}
  Start-Sleep -Seconds 1
 }
 if(!$ready){throw 'A cópia não iniciou'}
 $mount=$linuxProject+'/qa:/qa:ro'
 $apiOutput=wsl -d Ubuntu -- docker compose -f $composeFile run --rm --no-deps -v $mount prototipo python /qa/intensive-api.py
 if($LASTEXITCODE -ne 0){throw 'Falha na execução dos testes de API'}
 $apiJson=$apiOutput | Where-Object {$_ -match '^\{"checks":'}
 if(!$apiJson){throw 'Resultado da API ausente'}
 [IO.File]::WriteAllText((Join-Path $logDir 'api.json'),($apiJson -join [Environment]::NewLine))
 Push-Location (Split-Path $projectRoot -Parent)
 try{node (Join-Path $qaRoot 'run-intensive.cjs');$testExit=$LASTEXITCODE}finally{Pop-Location}
 $apiResult=($apiJson -join [Environment]::NewLine)|ConvertFrom-Json
 if($apiResult.passed -ne $apiResult.total){$testExit=1}
 Write-Host "Resultados em $logDir. Consulte os casos reprovados nos arquivos JSON."
} finally {
 if($qaContainer -match '^sqa-intensive-[a-f0-9]{12}$'){wsl -d Ubuntu -- docker rm -f $qaContainer}
 if($dbCreated -and $qaDb -match '^sqa_intensive_[a-f0-9]{32}$'){wsl -d Ubuntu -- docker compose -f $composeFile exec -T database dropdb -U condominio $qaDb}
}
exit $testExit
