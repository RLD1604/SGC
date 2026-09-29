$ErrorActionPreference = 'Stop'
$backupDirectory = Join-Path $PSScriptRoot 'backups'
New-Item -ItemType Directory -Force -Path $backupDirectory | Out-Null
$backupName = 'condominio-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [Guid]::NewGuid().ToString('N') + '.dump'
$backupPath = Join-Path $backupDirectory $backupName
$containerPath = '/tmp/' + $backupName
$portableBackupPath = $backupPath.Replace('\','/')
$linuxBackupPath = wsl -d Ubuntu -- wslpath -a -u $portableBackupPath
if ($LASTEXITCODE -ne 0) { throw 'Não foi possível localizar a pasta de backup no WSL.' }
$linuxBackupPath = $linuxBackupPath.Trim()
wsl -d Ubuntu -- docker exec sistema-gestao-comunicacao-condominio-database-1 pg_dump -U condominio -d condominio -Fc -f $containerPath
if ($LASTEXITCODE -ne 0) { throw 'O PostgreSQL não conseguiu gerar o backup.' }
wsl -d Ubuntu -- docker cp "sistema-gestao-comunicacao-condominio-database-1:$containerPath" $linuxBackupPath
if ($LASTEXITCODE -ne 0) { throw 'Não foi possível copiar o backup. O arquivo permanece em /tmp do contêiner.' }
wsl -d Ubuntu -- docker exec sistema-gestao-comunicacao-condominio-database-1 rm $containerPath
Write-Output "Backup criado: $backupPath"
