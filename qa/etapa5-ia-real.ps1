param()
$ErrorActionPreference='Stop'
$projectRoot=Split-Path $PSScriptRoot -Parent
$composeFile=Join-Path $projectRoot 'compose.yaml'
$runId=[Guid]::NewGuid().ToString('N')
$database='sqa_ai_real_'+$runId
$container='sqa-ai-real-'+$runId.Substring(0,12)
$created=$false;$started=$false
try {
  docker compose -f $composeFile exec -T database createdb -U condominio $database | Out-Null
  if($LASTEXITCODE -ne 0){throw 'Não foi possível criar o banco descartável da IA.'}
  $created=$true
  docker compose -f $composeFile run -d --no-deps --name $container -p 127.0.0.1:19001:8080 -e "DB_NAME=$database" -e AI_FREE_TIER_CONFIRMED=true prototipo | Out-Null
  if($LASTEXITCODE -ne 0){throw 'Não foi possível iniciar a candidata isolada da IA.'}
  $started=$true;$ready=$false
  for($attempt=0;$attempt -lt 30;$attempt++){try{if((Invoke-RestMethod http://localhost:19001/api/health).status -eq 'ok'){$ready=$true;break}}catch{};Start-Sleep -Seconds 1}
  if(!$ready){throw 'A candidata isolada não ficou saudável.'}
  $status=Invoke-RestMethod http://localhost:19001/api/ai/status
  if(!$status.enabled){throw 'A chave da IA não está disponível para o teste real.'}
  $body=@{consent=$true;segments=@(@{id=0;text='O elevador foram revisado ontem.'})}|ConvertTo-Json -Depth 4
  $response=Invoke-RestMethod -Method Post -Uri http://localhost:19001/api/ai/review -ContentType 'application/json' -Body $body
  if($null -eq $response.changes){throw 'A IA real não retornou a estrutura esperada.'}
  $audit=docker compose -f $composeFile exec -T database psql -U condominio -d $database -tA -c "SELECT status || '|' || characters FROM ai_requests ORDER BY created_at DESC LIMIT 1"
  if($LASTEXITCODE -ne 0 -or !$audit){throw 'A auditoria mínima da IA não foi registrada.'}
  [ordered]@{passed=$true;enabled=$status.enabled;changes=@($response.changes).Count;audit=($audit|Select-Object -Last 1).Trim();contentLogged=$false}|ConvertTo-Json
} finally {
  if($started -and $container -match '^sqa-ai-real-[a-f0-9]{12}$'){docker rm -f $container | Out-Null}
  if($created -and $database -match '^sqa_ai_real_[a-f0-9]{32}$'){docker compose -f $composeFile exec -T database dropdb -U condominio $database | Out-Null}
}
