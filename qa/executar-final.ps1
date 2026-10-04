param([string[]]$Only=@())

# Each suite receives its own disposable PostgreSQL database and application
# container on 19001. The workstation service on 9001 is never a test target.
$ErrorActionPreference='Stop'
$qaRoot=$PSScriptRoot
$projectRoot=Split-Path $qaRoot -Parent
$runId=(Get-Date -Format 'yyyyMMddTHHmmssZ')+'-'+[Guid]::NewGuid().ToString('N').Substring(0,8)
$resultDir=Join-Path $qaRoot ('results/final/'+$runId)
New-Item -ItemType Directory -Force $resultDir | Out-Null
$composeFile=Join-Path $projectRoot 'compose.yaml'
$dockerCandidates=@(
  (Get-Command docker.exe -ErrorAction SilentlyContinue|Select-Object -ExpandProperty Source -First 1),
  'C:\Users\roddr\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe',
  'C:\Program Files\Docker\Docker\resources\bin\docker.exe'
)|Where-Object{$_ -and (Test-Path $_)}
$docker=$dockerCandidates|Select-Object -First 1
if(!$docker){throw 'Docker Desktop CLI não encontrado'}
$playwrightRuntime='C:\Users\roddr\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\node_modules\playwright'
$playwrightWrapper=Join-Path $qaRoot 'playwright-auth-wrapper.cjs'
if(!(Test-Path $playwrightRuntime)){throw 'Runtime Playwright não encontrado'}
$results=@()

function Assert-QaPortAvailable {
  $listener=$null
  try {
    $listener=[Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback,19001)
    $listener.Start()
  } catch {
    throw 'A porta exclusiva de QA 19001 está ocupada; nenhum teste foi iniciado.'
  } finally {
    if($listener){$listener.Stop()}
  }
}

function Stop-Isolated([string]$container,[string]$database,[bool]$started,[bool]$created){
  if($container -match '^sqa-final-[a-f0-9]{12}$'){
    & $docker inspect $container *> $null
    if($LASTEXITCODE -eq 0){& $docker rm -f $container | Out-Null}
  }
  if($created -and $database -match '^sqa_final_[a-f0-9]{32}$'){& $docker compose -f $composeFile exec -T database dropdb -U condominio $database | Out-Null}
}

function Run-Isolated([string]$name,[string]$kind){
  Assert-QaPortAvailable
  $database='sqa_final_'+[Guid]::NewGuid().ToString('N')
  $container='sqa-final-'+[Guid]::NewGuid().ToString('N').Substring(0,12)
  $suiteDir=Join-Path $resultDir $name
  $log=Join-Path $suiteDir 'suite.log'
  New-Item -ItemType Directory -Force $suiteDir | Out-Null
  $created=$false;$started=$false;$code=1;$output=@()
  $browserLogin='qa_'+[Guid]::NewGuid().ToString('N').Substring(0,12)
  $browserPassword='Qa1!'+[Guid]::NewGuid().ToString('N')
  try {
    & $docker compose -f $composeFile exec -T database createdb -U condominio $database
    if($LASTEXITCODE -ne 0){throw 'Não foi possível criar banco descartável para '+$name}
    $created=$true
    & $docker compose -f $composeFile run -d --no-deps --name $container -p 127.0.0.1:19001:8080 -e "DB_NAME=$database" -e AI_FREE_TIER_CONFIRMED=false prototipo
    if($LASTEXITCODE -ne 0){throw 'Não foi possível iniciar contêiner descartável para '+$name}
    $started=$true;$ready=$false
    for($attempt=0;$attempt -lt 30;$attempt++){
      try {if((Invoke-RestMethod http://localhost:19001/api/health).status -eq 'ok'){$ready=$true;break}}catch{}
      Start-Sleep -Seconds 1
    }
    if(!$ready){throw 'A instância isolada não respondeu para '+$name}
    if($kind -eq 'node'){
      $seedMount="${qaRoot}:/site/qa:ro"
      & $docker compose -f $composeFile run --rm --no-deps -v $seedMount -e "DB_NAME=$database" -e QA_DISPOSABLE_DATABASE=YES -e "QA_BROWSER_LOGIN=$browserLogin" -e "QA_BROWSER_PASSWORD=$browserPassword" -e AI_FREE_TIER_CONFIRMED=false prototipo python /site/qa/seed_browser_user.py | Out-Null
      if($LASTEXITCODE -ne 0){throw 'Não foi possível criar a conta sintética para '+$name}
    }
    $env:QA_URL='http://localhost:19001';$env:QA_RESULTS_DIR=$suiteDir
    $env:QA_BROWSER_LOGIN=$browserLogin;$env:QA_BROWSER_PASSWORD=$browserPassword
    $env:REAL_PLAYWRIGHT_MODULE=$playwrightRuntime
    $env:PLAYWRIGHT_MODULE=$(if($name -in @('current-fields-blocks','stage4-responsive-current')){$playwrightRuntime}else{$playwrightWrapper})
    $previousErrorPreference=$ErrorActionPreference
    $ErrorActionPreference='Continue'
    if($kind -eq 'node'){
      Push-Location (Split-Path $projectRoot -Parent)
      try {$output=& node (Join-Path $qaRoot ($name+'.cjs')) 2>&1;$code=$LASTEXITCODE} finally {Pop-Location}
    } else {
      $mount="${qaRoot}:/qa:ro"
      $output=& $docker compose -f $composeFile run --rm --no-deps -v $mount -e "DB_NAME=$database" -e QA_DISPOSABLE_DATABASE=YES -e AI_FREE_TIER_CONFIRMED=false prototipo python ('/qa/'+$name) 2>&1
      $code=$LASTEXITCODE
    }
    $ErrorActionPreference=$previousErrorPreference
  } catch {$output=@($output)+$_.Exception.Message;$code=1
  } finally {
    [IO.File]::WriteAllLines($log,@($output|ForEach-Object {$_.ToString()}))
    Remove-Item Env:QA_URL,Env:QA_RESULTS_DIR,Env:QA_BROWSER_LOGIN,Env:QA_BROWSER_PASSWORD,Env:REAL_PLAYWRIGHT_MODULE,Env:PLAYWRIGHT_MODULE -ErrorAction SilentlyContinue
    Stop-Isolated $container $database $started $created
  }
  $script:results+=@{name=$name;kind=$kind;passed=($code -eq 0);exitCode=$code;directory=(Split-Path $suiteDir -Leaf)}
}

$regression=@('record-trash','editorial','beta-editor','photo-optimizer','photo-persistence','shared-storage','ai-review','compact-editor','photo-editor')
$additionalNode=@('current-fields-blocks','stage4-responsive-current','intensive-fields','intensive-edge')
$historicNode=@('etapa1','etapa1-drafts','etapa1-persistence','etapa2-acceptance','etapa3-acceptance','etapa4-responsive','etapa5-ai-simulado','etapa5-fluxo-completo','frontend-validation','undo-last-block','responsive-narrow')
$pythonSuites=@('intensive-api.py','etapa2_auth_api.py','stage4_operational.py','etapa2-validation.py','etapa2-migration.py','etapa3-status.py')
$known=@($regression+$additionalNode+$historicNode+$pythonSuites)
$selected=if($Only.Count){@($Only)}else{$known}
$unknown=@($selected|Where-Object{$_ -notin $known})
if($unknown.Count){throw 'Suíte desconhecida: '+($unknown -join ', ')}

foreach($name in $regression){if($name -in $selected){Run-Isolated $name 'node'}}

# Historic additional verification set: 34 API + 33 fields + 8 edge = 75.
if('intensive-api.py' -in $selected){Run-Isolated 'intensive-api.py' 'python'}
foreach($name in $additionalNode){if($name -in $selected){Run-Isolated $name 'node'}}

foreach($name in $historicNode){if($name -in $selected){Run-Isolated $name 'node'}}
foreach($name in @('etapa2_auth_api.py','stage4_operational.py','etapa2-validation.py','etapa2-migration.py','etapa3-status.py')){if($name -in $selected){Run-Isolated $name 'python'}}

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
$selective=[bool]$Only.Count
$passed=if($selective){$results.Count-eq $selected.Count -and $allScriptsPassed}else{$regressionPassed-eq 9 -and $additionalTotal-eq 75 -and $additionalPassed-eq 75 -and $allScriptsPassed}
$summary=[ordered]@{runId=$runId;mode=$(if($selective){'selective'}else{'full'});selected=$selected;passed=$passed;qaUrl='http://localhost:19001';resultDirectory=$resultDir;regressionRequired=$(if($selective){@($selected|Where-Object{$_ -in $regression}).Count}else{9});regressionPassed=$regressionPassed;additionalRequired=$(if($selective){$null}else{75});additionalObserved=$additionalTotal;additionalPassed=$additionalPassed;allScriptsPassed=$allScriptsPassed;results=$results}
$summary|ConvertTo-Json -Depth 6|Set-Content (Join-Path $resultDir 'summary.json')
$summary|ConvertTo-Json -Depth 4
if(!$passed){exit 1}
