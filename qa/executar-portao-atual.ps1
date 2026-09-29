param()
# Docker Compose writes progress to stderr even on success. Windows PowerShell
# turns that stream into NativeCommandError when Stop is active, so native
# commands are gated explicitly by their exit codes below.
$ErrorActionPreference='Continue'
$qaRoot=$PSScriptRoot
$projectRoot=Split-Path $qaRoot -Parent
$repoRoot=Split-Path $projectRoot -Parent
$compose=Join-Path $projectRoot 'compose.yaml'
$runId=(Get-Date -Format 'yyyyMMddTHHmmssZ')+'-'+[Guid]::NewGuid().ToString('N').Substring(0,8)
$resultDir=Join-Path $qaRoot ('results/current-gate/'+$runId)
New-Item -ItemType Directory -Force $resultDir|Out-Null
$dockerCandidates=@(
  (Get-Command docker.exe -ErrorAction SilentlyContinue|Select-Object -ExpandProperty Source -First 1),
  'C:\Users\roddr\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe',
  'C:\Program Files\Docker\Docker\resources\bin\docker.exe'
)|Where-Object{$_ -and (Test-Path $_)}
$docker=$dockerCandidates|Select-Object -First 1
if(!$docker){throw 'Docker Desktop CLI não encontrado'}

function Save-Lines([string]$path,$value){[IO.File]::WriteAllLines($path,@($value|ForEach-Object{$_.ToString()}))}

$buildOutput=& $docker compose -f $compose build prototipo 2>&1
$buildCode=$LASTEXITCODE;Save-Lines (Join-Path $resultDir 'build.log') $buildOutput

$unitOutput=& $docker compose -f $compose run --rm --no-deps -v "${qaRoot}:/site/qa:ro" -e AI_FREE_TIER_CONFIRMED=false prototipo python -m unittest discover -s /site/qa -p 'test_*unit.py' -v 2>&1
$unitCode=$LASTEXITCODE;Save-Lines (Join-Path $resultDir 'unit.log') $unitOutput

$database='sqa_current_'+[Guid]::NewGuid().ToString('N')
$integrationCode=1;$integrationOutput=@();$databaseCreated=$false
try {
  & $docker compose -f $compose exec -T database createdb -U condominio $database|Out-Null
  if($LASTEXITCODE-ne 0){throw 'createdb falhou'};$databaseCreated=$true
  $integrationOutput=& $docker compose -f $compose run --rm --no-deps -v "${qaRoot}:/site/qa:ro" -e "DB_NAME=$database" -e QA_DISPOSABLE_DATABASE=YES -e AI_FREE_TIER_CONFIRMED=false prototipo python /site/qa/etapa6_integration.py 2>&1
  $integrationCode=$LASTEXITCODE
} finally {
  Save-Lines (Join-Path $resultDir 'integration.log') $integrationOutput
  if($databaseCreated -and $database -match '^sqa_current_[a-f0-9]{32}$'){& $docker compose -f $compose exec -T database dropdb -U condominio $database|Out-Null}
}

$browserDatabase='sqa_browser_'+[Guid]::NewGuid().ToString('N')
$browserContainer='sqa-current-'+[Guid]::NewGuid().ToString('N').Substring(0,12)
$browserLogin='qa_browser';$browserPassword='Qa1!'+[Guid]::NewGuid().ToString('N')
$browserCode=1;$browserOutput=@();$browserDatabaseCreated=$false;$browserStarted=$false
$playwright='C:\Users\roddr\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\node_modules\playwright'
try {
  if(!(Test-Path $playwright)){throw 'Runtime Playwright não encontrado'}
  & $docker compose -f $compose exec -T database createdb -U condominio $browserDatabase|Out-Null
  if($LASTEXITCODE-ne 0){throw 'createdb do navegador falhou'};$browserDatabaseCreated=$true
  & $docker compose -f $compose run -d --no-deps --name $browserContainer -p 127.0.0.1:19001:8080 -e "DB_NAME=$browserDatabase" -e AI_FREE_TIER_CONFIRMED=false prototipo|Out-Null
  if($LASTEXITCODE-ne 0){throw 'contêiner do navegador falhou'};$browserStarted=$true
  $ready=$false
  for($attempt=0;$attempt-lt 30;$attempt++){try{if((Invoke-RestMethod 'http://127.0.0.1:19001/api/health').status-eq'ok'){$ready=$true;break}}catch{};Start-Sleep -Seconds 1}
  if(!$ready){throw 'instância de navegador não ficou saudável'}
  & $docker compose -f $compose run --rm --no-deps -v "${qaRoot}:/site/qa:ro" -e "DB_NAME=$browserDatabase" -e QA_DISPOSABLE_DATABASE=YES -e "QA_BROWSER_LOGIN=$browserLogin" -e "QA_BROWSER_PASSWORD=$browserPassword" -e AI_FREE_TIER_CONFIRMED=false prototipo python /site/qa/seed_browser_user.py|Out-Null
  if($LASTEXITCODE-ne 0){throw 'semente do navegador falhou'}
  $env:PLAYWRIGHT_MODULE=$playwright;$env:QA_URL='http://127.0.0.1:19001';$env:QA_BROWSER_LOGIN=$browserLogin;$env:QA_BROWSER_PASSWORD=$browserPassword
  $browserOutput=& node (Join-Path $qaRoot 'current-fields-blocks.cjs') 2>&1;$browserCode=$LASTEXITCODE
} finally {
  Save-Lines (Join-Path $resultDir 'browser.log') $browserOutput
  Remove-Item Env:QA_BROWSER_PASSWORD,Env:QA_BROWSER_LOGIN,Env:QA_URL -ErrorAction SilentlyContinue
  if($browserStarted -and $browserContainer -match '^sqa-current-[a-f0-9]{12}$'){& $docker rm -f $browserContainer|Out-Null}
  if($browserDatabaseCreated -and $browserDatabase -match '^sqa_browser_[a-f0-9]{32}$'){& $docker compose -f $compose exec -T database dropdb -U condominio $browserDatabase|Out-Null}
}

$jevCode=1;$jevOutput=@();$jevReport=Join-Path $resultDir 'jev-calibration.json'
$keyFile=Join-Path $repoRoot 'chave.txt'
if(Test-Path $keyFile){
  $secret=(Get-Content -Raw -LiteralPath $keyFile).Trim()
  if($secret.StartsWith('TYPESAFE_API_KEY=')){$secret=$secret.Substring(17).Trim().Trim('"').Trim("'")}
  if([string]::IsNullOrWhiteSpace($secret)){throw 'chave.txt está vazio'}
  $linuxScript=(wsl -d Ubuntu -- wslpath -a -u (Join-Path $qaRoot 'jev/calibrate_jev.py').Replace('\','/')).Trim()
  $linuxReport=(wsl -d Ubuntu -- wslpath -a -u $jevReport.Replace('\','/')).Trim()
  $previousWslEnv=$env:WSLENV;$env:TYPESAFE_API_KEY=$secret
  if([string]::IsNullOrWhiteSpace($previousWslEnv)){$env:WSLENV='TYPESAFE_API_KEY'}
  elseif($previousWslEnv -notmatch '(^|:)TYPESAFE_API_KEY(/[^:]*)?($|:)'){$env:WSLENV=$previousWslEnv+':TYPESAFE_API_KEY'}
  try {$jevOutput=wsl -d Ubuntu -- python3 $linuxScript --runs 3 --output $linuxReport 2>&1;$jevCode=$LASTEXITCODE}
  finally {Remove-Item Env:TYPESAFE_API_KEY -ErrorAction SilentlyContinue;$env:WSLENV=$previousWslEnv;$secret=$null}
  Save-Lines (Join-Path $resultDir 'jev.log') $jevOutput
}

$jevPassed=$false
if(Test-Path $jevReport){$jevPassed=[bool]((Get-Content -Raw $jevReport|ConvertFrom-Json).passed)}
$passed=($buildCode-eq 0 -and $unitCode-eq 0 -and $integrationCode-eq 0 -and $browserCode-eq 0 -and $jevCode-eq 0 -and $jevPassed)
$summary=[ordered]@{runId=$runId;passed=$passed;resultDirectory=$resultDir;buildPassed=($buildCode-eq 0);unitTests=35;unitPassed=($unitCode-eq 0);integrationPassed=($integrationCode-eq 0);authenticatedBrowserPassed=($browserCode-eq 0);jevPassed=$jevPassed;jevRuns=3;legacyBrowserSuite='substituida no portao atual pela bateria autenticada de campos e blocos'}
[IO.File]::WriteAllText((Join-Path $resultDir 'summary.json'),($summary|ConvertTo-Json -Depth 4),(New-Object Text.UTF8Encoding($false)))
$summary|ConvertTo-Json -Depth 4
if(!$passed){exit 1}
