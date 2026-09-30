<#
.SYNOPSIS
  Install trns on Windows (PowerShell 5.1+ or 7+).

.DESCRIPTION
  Downloads trns from GitHub into %LOCALAPPDATA%\trns, adds it to your user
  PATH, and verifies the install. No admin rights needed. Re-run to update.

  One-liner:
    irm https://raw.githubusercontent.com/Inpriv/labs/trns/pwa/tools/trns/install.ps1 | iex

  With options:
    & ([scriptblock]::Create((irm https://raw.githubusercontent.com/Inpriv/labs/trns/pwa/tools/trns/install.ps1))) -NoPath
    & ([scriptblock]::Create((irm https://raw.githubusercontent.com/Inpriv/labs/trns/pwa/tools/trns/install.ps1))) -Uninstall

.PARAMETER NoPath
  Install but don't touch PATH.

.PARAMETER Uninstall
  Remove trns, its PATH entry and its config.

.PARAMETER Ref
  Git ref to install (default: trns/pwa; env TRNS_REF also works).

.PARAMETER Source
  Install from a local tools\trns checkout instead of downloading (env TRNS_SRC).
#>
[CmdletBinding()]
param(
    [switch]$NoPath,
    [switch]$Uninstall,
    [string]$Ref = $(if ($env:TRNS_REF) { $env:TRNS_REF } else { 'trns/pwa' }),
    [string]$Source = $env:TRNS_SRC
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'   # makes Invoke-WebRequest much faster on PS 5.1
try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 } catch {}

function Say($m)  { Write-Host "==> $m" -ForegroundColor Cyan }
function Ok($m)   { Write-Host " ok $m" -ForegroundColor Green }
function Fail($m) { Write-Host " !! $m" -ForegroundColor Red; exit 1 }

$root    = if ($env:LOCALAPPDATA) { $env:LOCALAPPDATA } else { Join-Path $HOME 'AppData\Local' }
$dataDir = Join-Path $root 'trns'
$zipUrl  = "https://github.com/Inpriv/labs/archive/refs/heads/$Ref.zip"

# ---- uninstall -----------------------------------------------------------
if ($Uninstall) {
    Say "Removing trns"
    if (Test-Path (Join-Path $dataDir 'trns.py')) {
        try { & python (Join-Path $dataDir 'trns.py') --path-remove 2>$null | Out-Null } catch { }
    }
    if (Test-Path $dataDir) { Remove-Item $dataDir -Recurse -Force }
    $cfgBase = if ($env:TRNS_HOME) { $env:TRNS_HOME } else { $HOME }
    $cfg = Join-Path $cfgBase '.trns'
    if (Test-Path $cfg) { Remove-Item $cfg -Recurse -Force }
    Ok "trns removed. Open a new terminal for PATH to refresh."
    return
}

# ---- python --------------------------------------------------------------
# Try every candidate and keep the first that really runs: PATH often holds
# stale entries or the Microsoft Store "python" stub (which exits non-zero).
$python = $null
$ver = $null
$candidates = @()
foreach ($name in 'python', 'python3') {
    $candidates += @(Get-Command $name -All -ErrorAction SilentlyContinue |
        Where-Object { $_.Source } | ForEach-Object { $_.Source })
}
$candidates += @(Get-ChildItem "$root\Programs\Python\Python3*\python.exe" -ErrorAction SilentlyContinue |
    Sort-Object Name -Descending | ForEach-Object { $_.FullName })
foreach ($c in ($candidates | Select-Object -Unique)) {
    try {
        $v = & $c -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
        if ($LASTEXITCODE -eq 0 -and $v -match '^\d+\.\d+$') { $python = $c; $ver = $v; break }
    } catch { }
}
if (-not $python) {
    Fail "Python 3.9+ was not found. Install it from https://www.python.org/downloads/ (tick 'Add to PATH') and re-run."
}
if ([version]$ver -lt [version]'3.9') { Fail "Python $ver found, but trns needs 3.9 or newer." }

# ---- fetch ---------------------------------------------------------------
$tmp = Join-Path ([IO.Path]::GetTempPath()) ("trns-" + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $tmp | Out-Null
try {
    if ($Source) {
        if (-not (Test-Path (Join-Path $Source 'trns.py'))) { Fail "$Source does not contain trns.py" }
        Say "Installing from local checkout $Source"
        $srcDir = $Source
    } else {
        Say "Downloading trns ($Ref)"
        $zip = Join-Path $tmp 'repo.zip'
        try { Invoke-WebRequest -UseBasicParsing -Uri $zipUrl -OutFile $zip }
        catch { Fail "Could not download $zipUrl - $($_.Exception.Message)" }
        Expand-Archive -Path $zip -DestinationPath (Join-Path $tmp 'x') -Force
        $srcDir = Get-ChildItem (Join-Path $tmp 'x') -Directory |
                  ForEach-Object { Join-Path $_.FullName 'tools\trns' } |
                  Where-Object { Test-Path (Join-Path $_ 'trns.py') } | Select-Object -First 1
        if (-not $srcDir) { Fail "tools/trns not found in '$Ref'. Try -Ref main" }
    }

    # ---- install ---------------------------------------------------------
    Say "Installing to $dataDir"
    if (Test-Path $dataDir) { Remove-Item $dataDir -Recurse -Force }
    New-Item -ItemType Directory -Path $dataDir | Out-Null
    Copy-Item -Path (Join-Path $srcDir '*') -Destination $dataDir -Recurse -Force
    foreach ($junk in 'site', 'tests', 'docs', '__pycache__', 'core\__pycache__', '.git') {
        $p = Join-Path $dataDir $junk
        if (Test-Path $p) { Remove-Item $p -Recurse -Force }
    }
} finally {
    Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
}

# ---- verify --------------------------------------------------------------
$version = & $python (Join-Path $dataDir 'trns.py') --version
if ($LASTEXITCODE -ne 0) { Fail "Install verification failed. Run: python `"$dataDir\trns.py`" --version" }
Ok "$version installed"

# ---- PATH ----------------------------------------------------------------
if ($NoPath) {
    Write-Host "    Skipped PATH. Add it later with:  python `"$dataDir\trns.py`" --path-add"
} else {
    & $python (Join-Path $dataDir 'trns.py') --path-add | Out-Null
    Ok "added to your user PATH"
}

Write-Host ""
Write-Host "  Open a NEW terminal, then try:" -ForegroundColor White
Write-Host "    trns hello world"
Write-Host "    trns                 # interactive"
Write-Host ""
Write-Host "  Uninstall:  & ([scriptblock]::Create((irm https://raw.githubusercontent.com/Inpriv/labs/$Ref/tools/trns/install.ps1))) -Uninstall" -ForegroundColor DarkGray
