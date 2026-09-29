param()

# Each suite receives its own disposable PostgreSQL database and application
# container on 19001. The workstation service on 9001 is never a test target.
$ErrorActionPreference='Stop'
$qaRoot=$PSScriptRoot
$projectRoot=Split-Path $qaRoot -Parent
$runId=(Get-Date -Format 'yyyyMMddTHHmmssZ')+'-'+[Guid]::NewGuid().ToString('N').Substring(0,8)
$resultDir=Join-Path $qaRoot ('results/final/'+$runId)
New-Item -ItemType Directory -Force $resultDir | Out-Null
$linuxProject=(wsl -d Ubuntu -- wslpath -a -u $projectRoot.Replace('\','/')).Trim()
if($LASTEXITCODE -ne 0){throw 'WSL/Ubuntu indisponível'}
$composeFile="$linuxProject/compose.yaml"
$playwright='C:\Users\roddr\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\node_modules\playwright'
if(!(Test-Path $playwright)){throw 'Runtime Playwright não encontrado'}
$results=@()

function Stop-Isolated([string]$container,[string]$database,[bool]$started,[bool]$created){
  if($started -and $container -match '^sqa-final-[a-f0-9]{12}$'){wsl -d Ubuntu -- docker rm -f $container | Out-Null}
  if($created -and $database -match '^sqa_final_[a-f0-9]{32}$'){wsl -d Ubuntu -- docker compose -f $composeFile exec -T database dropdb -U condominio $database | Out-Null}
}

function Run-Isolated([string]$name,[string]$kind){
  $database='sqa_final_'+[Guid]::NewGuid().ToString('N')
  $container='sqa-final-'+[Guid]::NewGuid().ToString('N').Substring(0,12)
  $suiteDir=Join-Path $resultDir $name
  $log=Join-Path $suiteDir 'suite.log'
  New-Item -ItemType Directory -Force $suiteDir | Out-Null
  $created=$false;$started=$false;$code=1;$output=@()
  try {
    wsl -d Ubuntu -- docker compose -f $composeFile exec -T database createdb -U condominio $database
    if($LASTEXITCODE -ne 0){throw 'Não foi possível criar banco descartável para '+$name}
    $created=$true
    wsl -d Ubuntu -- docker compose -f $composeFile run -d --no-deps --name $container -p 127.0.0.1:19001:8080 -e "DB_NAME=$database" -e AI_FREE_TIER_CONFIRMED=false prototipo
    if($LASTEXITCODE -ne 0){throw 'Não foi possível iniciar contêiner descartável para '+$name}
    $started=$true;$ready=$false
    for($attempt=0;$attempt -lt 30;$attempt++){
      try {if((Invoke-RestMethod http://localhost:19001/api/health).status -eq 'ok'){$ready=$true;break}}catch{}
      Start-Sleep -Seconds 1
    }
    if(!$ready){throw 'A instância isolada não respondeu para '+$name}
    $env:QA_URL='http://localhost:19001';$env:QA_RESULTS_DIR=$suiteDir;$env:PLAYWRIGHT_MODULE=$playwright
    $previousErrorPreference=$ErrorActionPreference
    $ErrorActionPreference='Continue'
    if($kind -eq 'node'){
      Push-Location (Split-Path $projectRoot -Parent)
      try {$output=& node (Join-Path $qaRoot ($name+'.cjs')) 2>&1;$code=$LASTEXITCODE} finally {Pop-Location}
    } else {
      $mount=$linuxProject+'/qa:/qa:ro'
      $output=wsl -d Ubuntu -- docker compose -f $composeFile run --rm --no-deps -v $mount -e "DB_NAME=$database" -e AI_FREE_TIER_CONFIRMED=false prototipo python ('/qa/'+$name) 2>&1
      $code=$LASTEXITCODE
    }
    $ErrorActionPreference=$previousErrorPreference
  } catch {$output=@($output)+$_.Exception.Message;$code=1
  } finally {
    [IO.File]::WriteAllLines($log,@($output|ForEach-Object {$_.ToString()}))
    Stop-Isolated $container $database $started $created
  }
  $script:results+=@{name=$name;kind=$kind;passed=($code -eq 0);exitCode=$code;directory=(Split-Path $suiteDir -Leaf)}
}

$regression=@('record-trash','editorial','beta-editor','photo-optimizer','photo-persistence','shared-storage','ai-review','compact-editor','photo-editor')
foreach($name in $regression){Run-Isolated $name 'node'}

# Historic additional verification set: 34 API + 33 fields + 8 edge = 75.
Run-Isolated 'intensive-api.py' 'python'
Run-Isolated 'intensive-fields' 'node'
Run-Isolated 'intensive-edge' 'node'

foreach($name in @('etapa1','etapa1-drafts','etapa1-persistence','etapa2-acceptance','etapa3-acceptance','etapa4-responsive','etapa5-ai-simulado','etapa5-fluxo-completo','frontend-validation','undo-last-block','responsive-narrow')){Run-Isolated $name 'node'}
foreach($name in @('etapa2-validation.py','etapa2-migration.py','etapa3-status.py')){Run-Isolated $name 'python'}

$apiTotal=0;$apiPassed=0;$fieldsTotal=0;$fieldsPassed=0;$edgeTotal=0;$edgePassed=0
$apiLog=Join-Path (Join-Path $resultDir 'intensive-api.py') 'suite.log'
if(Test-Path $apiLog){$m=[regex]::Match((Get-Content $apiLog -Raw),'\{\s*"checks".*\}\s*$',[Text.RegularExpressions.RegexOptions]::Singleline);if($m.Success){$api=$m.Value|ConvertFrom-Json;$apiTotal=$api.total;$apiPassed=$api.passed}}
$fieldsPath=Join-Path (Join-Path $resultDir 'intensive-fields') 'fields.json'
if(Test-Path $fieldsPath){$fields=Get-Content $fieldsPath -Raw|ConvertFrom-Json;$fieldsTotal=@($fields.checks).Count;$fieldsPassed=@($fields.checks|Where-Object {$_.passed}).Count}
$edgePath=Join-Path (Join-Path $resultDir 'intensive-edge') 'edge.json'
if(Test-Path $edgePath){$edge=Get-Content $edgePath -Raw|ConvertFrom-Json;$edgeTotal=@($edge).Count;$edgePassed=@($edge|Where-Object {$_.passed}).Count}
$additionalTotal=$apiTotal+$fieldsTotal+$edgeTotal;$additionalPassed=$apiPassed+$fieldsPassed+$edgePassed
$regressionPassed=@($results|Where-Object {$regression -contains $_.name -and $_.passed}).Count
$allScriptsPassed=(@($results|Where-Object {-not $_.passed}).Count -eq 0)
$summary=[ordered]@{runId=$runId;qaUrl='http://localhost:19001';resultDirectory=$resultDir;regressionRequired=9;regressionPassed=$regressionPassed;additionalRequired=75;additionalObserved=$additionalTotal;additionalPassed=$additionalPassed;allScriptsPassed=$allScriptsPassed;results=$results}
$summary|ConvertTo-Json -Depth 6|Set-Content (Join-Path $resultDir 'summary.json')
$summary|ConvertTo-Json -Depth 4
if($regressionPassed -ne 9 -or $additionalTotal -ne 75 -or $additionalPassed -ne 75 -or -not $allScriptsPassed){exit 1}
