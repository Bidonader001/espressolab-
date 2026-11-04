# Fills a missing or placeholder .env so docker compose can start.
# A newly generated administrator password is written to the notice file once.
param(
    [string]$EnvFile = "",
    [string]$NoticeFile = ""
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
if (-not $EnvFile) { $EnvFile = Join-Path $root ".env" }
if (-not $NoticeFile) { $NoticeFile = Join-Path $env:TEMP "espressolab-new-admin.txt" }
if (Test-Path $NoticeFile) { Remove-Item $NoticeFile -Force }

function New-Token([int]$Size) {
    $bytes = New-Object byte[] $Size
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    return ([Convert]::ToBase64String($bytes).TrimEnd("=").Replace("+", "-").Replace("/", "_"))
}

function New-FernetKey {
    $bytes = New-Object byte[] 32
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    return ([Convert]::ToBase64String($bytes).Replace("+", "-").Replace("/", "_"))
}

$weakSecrets = @(
    "",
    "replace-with-a-long-random-string",
    "espressolab-dev-secret-change-me",
    "change-me"
)
$weakPasswords = @("", "change-me-now", "ChangeMe-EspressoLab-2026")

$lines = @()
if (Test-Path $EnvFile) {
    $lines = [System.IO.File]::ReadAllLines($EnvFile)
}

$map = @{}
foreach ($line in $lines) {
    if ($line -match '^\s*#' -or $line -notmatch "=") { continue }
    $pair = $line.Split("=", 2)
    $map[$pair[0].Trim()] = $pair[1].Trim().Trim('"').Trim("'")
}

$updates = @{}

$secret = ""
if ($map.ContainsKey("SECRET_KEY")) { $secret = [string]$map["SECRET_KEY"] }
if (($weakSecrets -contains $secret) -or ($secret.Length -lt 32)) {
    $updates["SECRET_KEY"] = New-Token 48
}

$fernet = ""
if ($map.ContainsKey("FERNET_KEY")) { $fernet = [string]$map["FERNET_KEY"] }
if ([string]::IsNullOrWhiteSpace($fernet)) {
    $updates["FERNET_KEY"] = New-FernetKey
}

$postgres = ""
if ($map.ContainsKey("POSTGRES_PASSWORD")) { $postgres = [string]$map["POSTGRES_PASSWORD"] }
if ([string]::IsNullOrWhiteSpace($postgres)) {
    $updates["POSTGRES_PASSWORD"] = New-Token 24
}

$admin = ""
if ($map.ContainsKey("ADMIN_PASSWORD")) { $admin = [string]$map["ADMIN_PASSWORD"] }
if ($weakPasswords -contains $admin) {
    $fresh = New-Token 18
    $updates["ADMIN_PASSWORD"] = $fresh
    [System.IO.File]::WriteAllText($NoticeFile, $fresh)
}

$username = ""
if ($map.ContainsKey("ADMIN_USERNAME")) { $username = [string]$map["ADMIN_USERNAME"] }
if ([string]::IsNullOrWhiteSpace($username)) {
    $updates["ADMIN_USERNAME"] = "admin"
}

$cors = ""
if ($map.ContainsKey("CORS_ORIGINS")) { $cors = [string]$map["CORS_ORIGINS"] }
if ([string]::IsNullOrWhiteSpace($cors) -or ($cors -notmatch "https://")) {
    $origins = New-Object System.Collections.Generic.List[string]
    [void]$origins.Add("https://localhost")
    [void]$origins.Add("https://127.0.0.1")
    $machine = ""
    try { $machine = [System.Net.Dns]::GetHostName() } catch { $machine = "" }
    if ($machine -match '^[A-Za-z0-9.-]+$' -and $machine -notin @("localhost", "127.0.0.1")) {
        [void]$origins.Add("https://$machine")
    }
    $updates["CORS_ORIGINS"] = ($origins -join ",")
}

if ($updates.Count -eq 0) { exit 0 }

$ordered = @(
    "ADMIN_USERNAME",
    "ADMIN_PASSWORD",
    "POSTGRES_PASSWORD",
    "SECRET_KEY",
    "FERNET_KEY",
    "CORS_ORIGINS"
)
$seen = @{}
$result = New-Object System.Collections.Generic.List[string]
foreach ($line in $lines) {
    if ($line -match '^\s*$' -or $line -match '^\s*#' -or $line -notmatch "=") {
        [void]$result.Add($line)
        continue
    }
    $key = $line.Split("=", 2)[0].Trim()
    if ($updates.ContainsKey($key)) {
        [void]$result.Add("$key=$($updates[$key])")
        $seen[$key] = $true
    } else {
        [void]$result.Add($line)
    }
}
foreach ($key in $ordered) {
    if ($updates.ContainsKey($key) -and -not $seen.ContainsKey($key)) {
        [void]$result.Add("$key=$($updates[$key])")
    }
}

$utf8 = New-Object System.Text.UTF8Encoding $false
[System.IO.File]::WriteAllLines($EnvFile, $result.ToArray(), $utf8)
