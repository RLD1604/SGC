[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'Medium')]
param(
    [string]$BackupDirectory,
    [string]$ExternalDirectory,
    [switch]$RequireExternalCopy
)

# Compativel com Windows PowerShell 5.1. Nao restaura nem altera o banco.
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
if ([string]::IsNullOrWhiteSpace($BackupDirectory)) {
    $BackupDirectory = Join-Path $projectRoot 'backups/operacional'
}
$composeFile = Join-Path $projectRoot 'compose.yaml'
$runId = [Guid]::NewGuid().ToString('N')
$timestamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$backupName = 'condominio-' + $timestamp + '-' + $runId + '.dump'
$manifestName = $backupName + '.manifest.json'
$containerDump = '/tmp/' + $backupName
$lockPath = Join-Path ([System.IO.Path]::GetTempPath()) 'condominio-backup-operacional.lock'
$lockStream = $null
$databaseContainer = $null
$hostPartial = $null
$manifestPartial = $null
$externalPartial = $null
$externalManifestPartial = $null

function Invoke-Docker {
    param([Parameter(Mandatory = $true)][string[]]$DockerArgs)
    $oldPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try { $output = & docker @DockerArgs 2>&1 } finally { $ErrorActionPreference = $oldPreference }
    if ($LASTEXITCODE -ne 0) {
        throw ('Falha no Docker: ' + ($output -join [Environment]::NewLine))
    }
    return $output
}

function Resolve-FullPath {
    param([Parameter(Mandatory = $true)][string]$Path)
    if ([System.IO.Path]::IsPathRooted($Path)) { return [System.IO.Path]::GetFullPath($Path) }
    return [System.IO.Path]::GetFullPath((Join-Path (Get-Location) $Path))
}

if ($RequireExternalCopy -and [string]::IsNullOrWhiteSpace($ExternalDirectory)) {
    throw 'Informe -ExternalDirectory quando usar -RequireExternalCopy.'
}
if (-not (Test-Path -LiteralPath $composeFile -PathType Leaf)) {
    throw "Arquivo Compose nao encontrado: $composeFile"
}

$backupRoot = Resolve-FullPath $BackupDirectory
$externalRoot = if ([string]::IsNullOrWhiteSpace($ExternalDirectory)) { $null } else { Resolve-FullPath $ExternalDirectory }
if ($RequireExternalCopy -and $externalRoot) {
    $localVolume = [System.IO.Path]::GetPathRoot($backupRoot)
    $externalVolume = [System.IO.Path]::GetPathRoot($externalRoot)
    if ([string]::Equals($localVolume, $externalVolume, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw 'A copia externa obrigatoria deve ficar em outro volume ou compartilhamento de rede.'
    }
}
$finalDump = Join-Path $backupRoot $backupName
$finalManifest = Join-Path $backupRoot $manifestName
$hostPartial = $finalDump + '.partial'
$manifestPartial = $finalManifest + '.partial'

if (-not $PSCmdlet.ShouldProcess($finalDump, 'Criar e validar backup operacional do PostgreSQL')) {
    [ordered]@{
        planned = $true
        dump = $finalDump
        manifest = $finalManifest
        externalDirectory = $externalRoot
        externalRequired = [bool]$RequireExternalCopy
    } | ConvertTo-Json -Depth 4
    return
}

try {
    $lockStream = [System.IO.File]::Open($lockPath, 'OpenOrCreate', 'ReadWrite', 'None')
} catch {
    throw 'Ja existe outro backup operacional em execucao.'
}

try {
    New-Item -ItemType Directory -Force -Path $backupRoot | Out-Null
    if ($externalRoot) { New-Item -ItemType Directory -Force -Path $externalRoot | Out-Null }

    $databaseContainer = (Invoke-Docker @('compose', '-f', $composeFile, 'ps', '-q', 'database') | Select-Object -Last 1).Trim()
    if (-not $databaseContainer) { throw 'O container PostgreSQL do Compose nao esta em execucao.' }

    $health = (Invoke-Docker @('inspect', '--format', '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}', $databaseContainer) | Select-Object -Last 1).Trim()
    if ($health -ne 'healthy' -and $health -ne 'running') {
        throw "O PostgreSQL nao esta saudavel (estado: $health)."
    }

    Invoke-Docker @('exec', $databaseContainer, 'pg_dump', '-U', 'condominio', '-d', 'condominio', '-Fc', '--no-owner', '--no-privileges', '-f', $containerDump) | Out-Null
    $toc = Invoke-Docker @('exec', $databaseContainer, 'pg_restore', '--list', $containerDump)
    $tocEntries = @($toc | Where-Object { $_ -and -not $_.ToString().StartsWith(';') }).Count
    if ($tocEntries -lt 1) { throw 'O arquivo criado nao contem entradas restauraveis.' }

    Invoke-Docker @('cp', ($databaseContainer + ':' + $containerDump), $hostPartial) | Out-Null
    $dumpInfo = Get-Item -LiteralPath $hostPartial
    if ($dumpInfo.Length -lt 1) { throw 'O arquivo copiado esta vazio.' }
    $hash = (Get-FileHash -LiteralPath $hostPartial -Algorithm SHA256).Hash.ToUpperInvariant()

    $schemaOutput = Invoke-Docker @('exec', $databaseContainer, 'psql', '-U', 'condominio', '-d', 'condominio', '-tA', '-c', 'SELECT COALESCE(max(version),0) FROM schema_versions')
    $schemaVersion = [int](($schemaOutput | Select-Object -Last 1).Trim())
    $imageId = (Invoke-Docker @('inspect', '--format', '{{.Image}}', $databaseContainer) | Select-Object -Last 1).Trim()
    $applicationVersion = $null
    $versionFile = Join-Path $projectRoot 'public/version.json'
    if (Test-Path -LiteralPath $versionFile -PathType Leaf) {
        $applicationVersion = Get-Content -LiteralPath $versionFile -Raw | ConvertFrom-Json
    }

    $externalStatus = 'not-configured'
    $externalDump = $null
    if ($externalRoot) {
        $externalDump = Join-Path $externalRoot $backupName
        $externalPartial = $externalDump + '.partial'
        Copy-Item -LiteralPath $hostPartial -Destination $externalPartial -Force
        $externalHash = (Get-FileHash -LiteralPath $externalPartial -Algorithm SHA256).Hash.ToUpperInvariant()
        if ($externalHash -ne $hash) { throw 'A copia externa nao coincide com o SHA-256 local.' }
        Move-Item -LiteralPath $externalPartial -Destination $externalDump
        $externalStatus = 'verified'
    }
    if ($RequireExternalCopy -and $externalStatus -ne 'verified') {
        throw 'A copia externa obrigatoria nao foi confirmada.'
    }

    $manifest = [ordered]@{
        formatVersion = 1
        createdAtUtc = (Get-Date).ToUniversalTime().ToString('o')
        database = 'condominio'
        dump = [ordered]@{
            file = $backupName
            format = 'postgres-custom'
            bytes = $dumpInfo.Length
            sha256 = $hash
            tocEntries = $tocEntries
        }
        source = [ordered]@{
            composeFile = 'compose.yaml'
            databaseService = 'database'
            databaseImageId = $imageId
            schemaVersion = $schemaVersion
            application = $applicationVersion
        }
        externalCopy = [ordered]@{
            status = $externalStatus
            file = if ($externalDump) { [System.IO.Path]::GetFileName($externalDump) } else { $null }
        }
        validation = [ordered]@{
            pgRestoreList = 'passed'
            sha256 = 'passed'
        }
    }
    $manifest | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $manifestPartial -Encoding UTF8

    if ($externalRoot) {
        $externalManifest = Join-Path $externalRoot $manifestName
        $externalManifestPartial = $externalManifest + '.partial'
        Copy-Item -LiteralPath $manifestPartial -Destination $externalManifestPartial -Force
        Move-Item -LiteralPath $externalManifestPartial -Destination $externalManifest
    }
    Move-Item -LiteralPath $hostPartial -Destination $finalDump
    Move-Item -LiteralPath $manifestPartial -Destination $finalManifest

    [ordered]@{
        passed = $true
        dump = $finalDump
        manifest = $finalManifest
        bytes = $dumpInfo.Length
        sha256 = $hash
        externalCopy = $externalStatus
    } | ConvertTo-Json -Depth 4
}
finally {
    if ($databaseContainer -and $containerDump -match '^/tmp/condominio-[0-9]{8}T[0-9]{6}Z-[a-f0-9]{32}\.dump$') {
        try { Invoke-Docker @('exec', $databaseContainer, 'rm', '-f', $containerDump) | Out-Null } catch { Write-Warning $_.Exception.Message }
    }
    foreach ($partial in @($hostPartial, $manifestPartial, $externalPartial, $externalManifestPartial)) {
        if ($partial -and (Test-Path -LiteralPath $partial -PathType Leaf)) { Remove-Item -LiteralPath $partial -Force }
    }
    if ($lockStream) { $lockStream.Dispose() }
}
