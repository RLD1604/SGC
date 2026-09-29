[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'High')]
param(
    [string]$BackupDirectory,
    [ValidateRange(1, 366)][int]$KeepDaily = 14,
    [ValidateRange(0, 104)][int]$KeepWeekly = 8,
    [ValidateRange(0, 120)][int]$KeepMonthly = 12,
    [ValidateRange(1, 20)][int]$MinimumValidated = 2,
    [switch]$AllowDeleteWithoutExternalCopy
)

# Remove apenas pares dump/manifesto reconhecidos, integros e fora da politica.
$ErrorActionPreference = 'Stop'
if ([string]::IsNullOrWhiteSpace($BackupDirectory)) {
    $BackupDirectory = Join-Path (Split-Path $PSScriptRoot -Parent) 'backups/operacional'
}
$backupRoot = [System.IO.Path]::GetFullPath($BackupDirectory)
if (-not (Test-Path -LiteralPath $backupRoot -PathType Container)) {
    throw "Diretorio de backups nao encontrado: $backupRoot"
}

$valid = @()
$ignored = @()
$manifestFiles = Get-ChildItem -LiteralPath $backupRoot -File -Filter 'condominio-*.dump.manifest.json'
foreach ($manifestFile in $manifestFiles) {
    try {
        $manifest = Get-Content -LiteralPath $manifestFile.FullName -Raw | ConvertFrom-Json
        if ($manifest.formatVersion -ne 1) { throw 'versao de manifesto desconhecida' }
        $dumpLeaf = [string]$manifest.dump.file
        if ($dumpLeaf -notmatch '^condominio-[0-9]{8}T[0-9]{6}Z-[a-f0-9]{32}\.dump$') { throw 'nome de dump invalido' }
        $expectedManifest = $dumpLeaf + '.manifest.json'
        if ($manifestFile.Name -ne $expectedManifest) { throw 'manifesto nao corresponde ao dump' }
        $dumpPath = Join-Path $backupRoot $dumpLeaf
        if (-not (Test-Path -LiteralPath $dumpPath -PathType Leaf)) { throw 'dump ausente' }
        $dumpInfo = Get-Item -LiteralPath $dumpPath
        if ([int64]$manifest.dump.bytes -ne $dumpInfo.Length) { throw 'tamanho divergente' }
        $actualHash = (Get-FileHash -LiteralPath $dumpPath -Algorithm SHA256).Hash.ToUpperInvariant()
        if ($actualHash -ne ([string]$manifest.dump.sha256).ToUpperInvariant()) { throw 'SHA-256 divergente' }
        $created = [DateTimeOffset]::Parse([string]$manifest.createdAtUtc).ToUniversalTime()
        $externalVerified = ([string]$manifest.externalCopy.status -eq 'verified')
        $valid += [pscustomobject]@{
            CreatedAt = $created
            DumpPath = $dumpPath
            ManifestPath = $manifestFile.FullName
            Key = $dumpLeaf
            ExternalVerified = $externalVerified
        }
    } catch {
        $ignored += [pscustomobject]@{ Manifest = $manifestFile.FullName; Reason = $_.Exception.Message }
    }
}

$valid = @($valid | Sort-Object CreatedAt -Descending)
if ($valid.Count -lt $MinimumValidated) {
    throw "Existem somente $($valid.Count) backups locais validos; o minimo exigido e $MinimumValidated. Nada foi removido."
}

$calendar = [System.Globalization.CultureInfo]::InvariantCulture.Calendar
$weekRule = [System.Globalization.CalendarWeekRule]::FirstFourDayWeek
$monday = [DayOfWeek]::Monday
$keep = @{}

$valid | Select-Object -First $MinimumValidated | ForEach-Object { $keep[$_.Key] = $true }
$valid | Group-Object { $_.CreatedAt.ToString('yyyy-MM-dd') } | Sort-Object Name -Descending | Select-Object -First $KeepDaily | ForEach-Object {
    $_.Group | Sort-Object CreatedAt -Descending | Select-Object -First 1 | ForEach-Object { $keep[$_.Key] = $true }
}
if ($KeepWeekly -gt 0) {
    $valid | Group-Object {
        $d = $_.CreatedAt.UtcDateTime
        $mondayBasedDay = (([int]$d.DayOfWeek + 6) % 7)
        $weekYear = $d.AddDays(3 - $mondayBasedDay).Year
        '{0:D4}-W{1:D2}' -f $weekYear, $calendar.GetWeekOfYear($d, $weekRule, $monday)
    } | Sort-Object Name -Descending | Select-Object -First $KeepWeekly | ForEach-Object {
        $_.Group | Sort-Object CreatedAt -Descending | Select-Object -First 1 | ForEach-Object { $keep[$_.Key] = $true }
    }
}
if ($KeepMonthly -gt 0) {
    $valid | Group-Object { $_.CreatedAt.ToString('yyyy-MM') } | Sort-Object Name -Descending | Select-Object -First $KeepMonthly | ForEach-Object {
        $_.Group | Sort-Object CreatedAt -Descending | Select-Object -First 1 | ForEach-Object { $keep[$_.Key] = $true }
    }
}

$deleted = @()
$protected = @()
$eligible = @()
foreach ($item in $valid) {
    if ($keep.ContainsKey($item.Key)) { continue }
    if (-not $item.ExternalVerified -and -not $AllowDeleteWithoutExternalCopy) {
        $protected += [pscustomobject]@{ Dump = $item.DumpPath; Reason = 'copia externa nao confirmada' }
        continue
    }
    $eligible += $item.DumpPath
    if ($PSCmdlet.ShouldProcess($item.DumpPath, 'Remover backup fora da politica de retencao')) {
        Remove-Item -LiteralPath $item.DumpPath -Force
        Remove-Item -LiteralPath $item.ManifestPath -Force
        $deleted += $item.DumpPath
    }
}

[ordered]@{
    passed = $true
    validBackups = $valid.Count
    retained = @($valid | Where-Object { $keep.ContainsKey($_.Key) }).Count
    eligibleForDeletion = $eligible
    deleted = $deleted
    protected = $protected
    ignored = $ignored
    policy = [ordered]@{
        daily = $KeepDaily
        weekly = $KeepWeekly
        monthly = $KeepMonthly
        minimumValidated = $MinimumValidated
        externalCopyRequiredForDeletion = -not [bool]$AllowDeleteWithoutExternalCopy
    }
} | ConvertTo-Json -Depth 8
