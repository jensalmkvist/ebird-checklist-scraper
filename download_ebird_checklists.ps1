
<#
.SYNOPSIS
    Batch-download eBird checklists month-by-month using your Selenium script.

.DESCRIPTION
    - Ensures Python venv (.venv) exists; creates it if not.
    - Installs required packages (selenium) if not already installed.
    - Activates the venv.
    - Iterates from a start date up to the last full month (excludes the current month),
      creating downloads_[YYYY]_[MM] for each month and calling ebird_month_download.py.

.PARAMETER Username
    eBird/Cornell Lab username.

.PARAMETER Password
    eBird/Cornell Lab password.

.PARAMETER Region
    eBird region code used by the filtered My Checklists URL (default: SE).

.PARAMETER StartDate
    The starting date (any day in the first month to include), e.g. 2024-09-01.

.PARAMETER ScriptPath
    Path to ebird_month_download.py (default: .\ebird_month_download.py).

.PARAMETER Headless
    Switch: run Chrome headless. Omit to watch the browser.

.EXAMPLE
    .\run_ebird_months.ps1 -Username YOUR_USERNAME -Password "YOUR_PASSWORD" `
        -Region SE -StartDate "2024-09-01" -Headless
#>

param(
  [Parameter(Mandatory=$true)][string]$Username,
  [Parameter(Mandatory=$true)][string]$Password,
  [string]$Region = "SE",
  [Parameter(Mandatory=$true)][DateTime]$StartDate,
  [string]$ScriptPath = ".\ebird_month_download.py",
  [switch]$Headless
)

# --- Helper: Write status
function Write-Info($msg)
{ Write-Host "[INFO] $msg" -ForegroundColor Cyan 
}
function Write-Warn($msg)
{ Write-Host "[WARN] $msg" -ForegroundColor Yellow 
}
function Write-Err($msg)
{ Write-Host "[ERROR] $msg" -ForegroundColor Red 
}

# --- Ensure we are in project root (optional)
# (comment out if you prefer running from elsewhere)
Write-Info "Current directory: $(Get-Location)"

# --- Ensure venv exists
$venvDir = ".\.venv"
$venvActivate = ".\.venv\Scripts\Activate.ps1"
if (!(Test-Path $venvDir))
{
  Write-Info "Creating Python venv in $venvDir ..."
  python -m venv $venvDir
  if ($LASTEXITCODE -ne 0)
  { Write-Err "Failed to create venv."; exit 1 
  }
} else
{
  Write-Info "Found existing venv at $venvDir."
}

# --- Activate venv
if (!(Test-Path $venvActivate))
{
  Write-Err "Could not find venv activation script at $venvActivate"
  exit 1
}
Write-Info "Activating venv ..."
& $venvActivate

# --- Ensure dependencies
Write-Info "Ensuring Python dependencies ..."
python -c "import selenium" 2>$null
if ($LASTEXITCODE -ne 0)
{
  Write-Info "Installing selenium ..."
  pip install --upgrade pip
  pip install selenium
  if ($LASTEXITCODE -ne 0)
  { Write-Err "pip install selenium failed."; exit 1 
  }
} else
{
  Write-Info "Selenium already available."
}

# --- Confirm the Python script exists
if (!(Test-Path $ScriptPath))
{
  Write-Err "Python script not found at path: $ScriptPath"
  exit 1
}

# --- Determine month range: from StartDate to LAST FULL MONTH (exclude current month)
# Current date/time from system
$now = Get-Date
# The last full month ends at midnight on the first day of the current month minus one day.
# If today is 2026-01-07, last full month is 2025-12.
$lastFullMonthStart = Get-Date -Year $now.Year -Month $now.Month -Day 1
$lastFullMonthEnd   = $lastFullMonthStart.AddDays(-1)      # last day of previous month
$lastYear  = $lastFullMonthEnd.Year
$lastMonth = $lastFullMonthEnd.Month

# Normalize StartDate to first of its month to avoid partial-month edge cases.
$startYear  = $StartDate.Year
$startMonth = $StartDate.Month
$startAnchor = Get-Date -Year $startYear -Month $startMonth -Day 1

Write-Info "Planning monthly downloads from $($startAnchor.ToString('yyyy-MM')) up to $($lastYear)-$("{0:00}" -f $lastMonth) (excluding current month)."

# --- Iterate months
$year = $startAnchor.Year
$month = $startAnchor.Month

# Safety: if StartDate is in/after current month, nothing to do.
if (($year -gt $lastYear) -or (($year -eq $lastYear) -and ($month -gt $lastMonth)))
{
  Write-Warn "Start month ($($startAnchor.ToString('yyyy-MM'))) is after the last full month ($lastYear-$("{0:00}" -f $lastMonth)). Nothing to download."
  exit 0
}

while (($year -lt $lastYear) -or (($year -eq $lastYear) -and ($month -le $lastMonth)))
{
  $outDir = "downloads_{0}_{1}" -f $year, ("{0:00}" -f $month)
  Write-Info "Processing $year-$("{0:00}" -f $month) → $outDir"

  if (!(Test-Path $outDir))
  {
    New-Item -ItemType Directory -Path $outDir | Out-Null
  }

  # Build the Python command
  $pythonArgs = @(
    $ScriptPath,
    "--username", $Username,
    "--password", $Password,
    "--region", $Region,
    "--year", $year,
    "--month", $month,
    "--out", $outDir
  )
  if ($Headless)
  { $pythonArgs += "--headless" 
  }

  Write-Info ("Running: python " + ($pythonArgs -join " "))
  python $pythonArgs
  if ($LASTEXITCODE -ne 0)
  {
    Write-Warn "Python script returned non-zero exit code for $year-$("{0:00}" -f $month). Check logs above."
  }

  # Advance to next month
  if ($month -eq 12)
  {
    $month = 1
    $year += 1
  } else
  {
    $month += 1
  }
}

Write-Info "All done."

