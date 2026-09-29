$ErrorActionPreference = 'Stop'
Write-Host 'Crie uma chave em https://console.groq.com/keys usando uma conta no plano Free.'
Write-Host 'Este script nao ativa cobranca nem altera seu plano na Groq. Verifique o plano no painel.'
$confirmation = Read-Host 'Confirma que a chave pertence a uma conta no plano gratuito? Digite SIM'
if ($confirmation -cne 'SIM') { throw 'Configuracao cancelada, sem alteracoes.' }
$secureKey = Read-Host 'Cole a chave Groq (entrada oculta)' -AsSecureString
$keyPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureKey)
try {
    $plainKey = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($keyPointer).Trim()
    if (-not $plainKey.StartsWith('gsk_') -or $plainKey.Length -lt 20) { throw 'Formato de chave Groq invalido.' }
    $secretDir = Join-Path $PSScriptRoot '.secrets'
    New-Item -ItemType Directory -Path $secretDir -Force | Out-Null
    [IO.File]::WriteAllText((Join-Path $secretDir 'groq_api_key'),$plainKey)
} finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($keyPointer)
    $plainKey = $null
}
$envPath = Join-Path $PSScriptRoot '.env'
$existingEnv = if (Test-Path -LiteralPath $envPath) { Get-Content -LiteralPath $envPath | Where-Object { $_ -notmatch '^AI_FREE_TIER_CONFIRMED=' } } else { @() }
[IO.File]::WriteAllLines($envPath, @($existingEnv) + 'AI_FREE_TIER_CONFIRMED=true')
$composePath = (Join-Path $PSScriptRoot 'compose.yaml').Replace('\','/')
$linuxComposePath = wsl -d Ubuntu -- wslpath -a -u $composePath
if ($LASTEXITCODE -ne 0) { throw 'Chave salva; falha ao localizar Compose no WSL.' }
wsl -d Ubuntu -- docker compose -f $linuxComposePath.Trim() up -d --wait --wait-timeout 90
if ($LASTEXITCODE -ne 0) { throw 'Chave salva; verifique o Docker.' }
Write-Host 'Configuracao concluida. Abra um texto e clique em Revisar com IA.'
