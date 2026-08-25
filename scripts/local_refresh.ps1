<#
.SYNOPSIS
    Run the monthly NHS GP ingestion from this machine and push the refreshed data to origin/main.

.DESCRIPTION
    Cloudflare, in front of digital.nhs.uk, returns 403 to GitHub-hosted runners regardless of
    User-Agent, so the scrape has to originate from a residential IP. The publication page must be
    scraped rather than reconstructed: download URLs carry an opaque per-file hex segment
    (e.g. /45/E255E0/gp-reg-pat-prac-all.zip) that changes every month, so there is no derivable
    direct link. Everything downstream of the scrape is offline-safe and can stay in CI.

    Safe to run daily. If the target month has already been ingested successfully on origin/main,
    the script exits 0 without touching the network — so a machine that was switched off on the
    publication day simply catches up on its next run.

.PARAMETER RepoPath
    Dedicated clone used only by this task. Must NOT be your development checkout: the script hard-
    resets to origin/main and would discard uncommitted work. Created on first run if absent.

.PARAMETER Python
    Interpreter to use. Must be 3.11+ — pipeline/backfill.py imports datetime.UTC, which does not
    exist on 3.9, so an inherited Anaconda base interpreter fails at import time.

.PARAMETER Month
    Target month name or number. Defaults, with -Year, to the current month (matching pipeline.monthly).

.PARAMETER Year
    Target year. Must be supplied together with -Month.

.PARAMETER Force
    Re-ingest even if the target month is already recorded as successful on origin/main.

.PARAMETER NoPush
    Do everything except the final push. Useful for a first supervised run.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\local_refresh.ps1 -NoPush

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\local_refresh.ps1 -Month july -Year 2026 -Force
#>
[CmdletBinding()]
param(
    [string]$RepoPath = (Join-Path $env:LOCALAPPDATA 'nhs-gp-refresh\repo'),
    [string]$Python = (Join-Path $env:USERPROFILE 'anaconda3\envs\nhs-gp\python.exe'),
    [string]$RemoteUrl = 'https://github.com/jad-22/nhs-gp-analytics.git',
    [string]$Month,
    [int]$Year,
    [string]$LogDir = (Join-Path $env:LOCALAPPDATA 'nhs-gp-refresh\logs'),
    [switch]$Force,
    [switch]$NoPush
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# Exit codes are what Task Scheduler surfaces in its "Last Run Result" column, so they are kept
# meaningful: 0 covers every expected outcome (ingested / not published yet / already done) and a
# non-zero code always means something genuinely needs looking at.
$EXIT_OK = 0
$EXIT_FAILED = 1
$EXIT_PRECONDITION = 2

if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir -Force | Out-Null }
$logFile = Join-Path $LogDir ("refresh-{0}.log" -f (Get-Date -Format 'yyyy-MM'))

function Write-Log {
    param([string]$Message, [string]$Level = 'INFO')
    $line = "{0} [{1}] {2}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Level, $Message
    Write-Host $line
    Add-Content -Path $logFile -Value $line -Encoding utf8
}

function Invoke-Git {
    # Args are taken as an explicit array and splatted rather than collected via
    # ValueFromRemainingArguments: PowerShell swallows a bare `--` as its own end-of-parameters
    # token, which would silently strip git's pathspec separator from `clean`/`add`.
    #
    # Native stderr is deliberately not redirected: in Windows PowerShell 5.1, `2>&1` on a native
    # exe wraps each stderr line in an ErrorRecord and trips $ErrorActionPreference='Stop' even
    # when git exited 0 (git writes routine progress to stderr).
    param([Parameter(Mandatory = $true)][string[]]$GitArgs)
    $output = & git -C $RepoPath @GitArgs
    if ($LASTEXITCODE -ne 0) {
        throw ("git {0} failed with exit code {1}" -f ($GitArgs -join ' '), $LASTEXITCODE)
    }
    return $output
}

function Get-LatestLogRecord {
    param([string]$LogPath, [string]$TargetMonth, [int]$TargetYear)
    if (-not (Test-Path $LogPath)) { return $null }
    try {
        $records = Get-Content -Path $LogPath -Raw -Encoding utf8 | ConvertFrom-Json
    } catch {
        Write-Log "Could not parse $LogPath ($($_.Exception.Message)); treating as empty." 'WARN'
        return $null
    }
    if ($null -eq $records) { return $null }
    # A single-element JSON array deserialises to a bare object, not an array.
    if ($records -isnot [System.Array]) { $records = @($records) }
    $matched = @($records | Where-Object { $_.month -eq $TargetMonth -and [int]$_.year -eq $TargetYear })
    if ($matched.Count -eq 0) { return $null }
    return $matched[-1]
}

Write-Log "=== NHS GP local refresh starting ==="

# --- Preconditions ------------------------------------------------------------------------------

if (-not (Test-Path $Python)) {
    Write-Log "Python interpreter not found at '$Python'." 'ERROR'
    exit $EXIT_PRECONDITION
}

$versionOutput = & $Python --version
if ($LASTEXITCODE -ne 0) {
    Write-Log "Could not execute '$Python'." 'ERROR'
    exit $EXIT_PRECONDITION
}
if ($versionOutput -notmatch 'Python 3\.(1[1-9]|[2-9][0-9])') {
    Write-Log "Need Python 3.11+, found '$versionOutput'. pipeline.backfill imports datetime.UTC." 'ERROR'
    exit $EXIT_PRECONDITION
}
Write-Log "Interpreter: $Python ($versionOutput)"

if (($PSBoundParameters.ContainsKey('Month')) -ne ($PSBoundParameters.ContainsKey('Year'))) {
    Write-Log "Provide both -Month and -Year together, or neither." 'ERROR'
    exit $EXIT_PRECONDITION
}

# Guard against being pointed at a development checkout. The hard reset below is unrecoverable for
# uncommitted work, and the dev checkout typically sits on a feature branch with dirty files.
$devCheckout = 'D:\GitHub\nhs-gp-analytics'
if ((Test-Path $RepoPath) -and (Test-Path $devCheckout)) {
    $resolvedRepo = (Resolve-Path $RepoPath).Path.TrimEnd('\')
    $resolvedDev = (Resolve-Path $devCheckout).Path.TrimEnd('\')
    if ($resolvedRepo -eq $resolvedDev) {
        Write-Log "-RepoPath points at the development checkout ($resolvedDev). Refusing: this script hard-resets to origin/main." 'ERROR'
        exit $EXIT_PRECONDITION
    }
}

# --- Sync the dedicated clone to origin/main ------------------------------------------------------

if (-not (Test-Path (Join-Path $RepoPath '.git'))) {
    Write-Log "No clone at '$RepoPath'; cloning $RemoteUrl"
    $parent = Split-Path -Parent $RepoPath
    if (-not (Test-Path $parent)) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
    & git clone $RemoteUrl $RepoPath
    if ($LASTEXITCODE -ne 0) {
        Write-Log "Clone failed with exit code $LASTEXITCODE." 'ERROR'
        exit $EXIT_FAILED
    }
}

Write-Log "Syncing '$RepoPath' to origin/main"
Invoke-Git @('fetch', 'origin', '--prune') | Out-Null
Invoke-Git @('checkout', '-B', 'main', 'origin/main') | Out-Null
Invoke-Git @('reset', '--hard', 'origin/main') | Out-Null
# Leftover archives from an interrupted run would otherwise accumulate in data/raw.
Invoke-Git @('clean', '-fd', '--', 'data/raw') | Out-Null
Write-Log ("origin/main is at {0}" -f (Invoke-Git @('log', '--oneline', '-1')))

# --- Resolve the target month ---------------------------------------------------------------------

if ($PSBoundParameters.ContainsKey('Month')) {
    $targetMonth = $Month.ToLower()
    $targetYear = $Year
} else {
    $now = Get-Date
    $targetMonth = $now.ToString('MMMM', [System.Globalization.CultureInfo]::InvariantCulture).ToLower()
    $targetYear = $now.Year
}
Write-Log "Target publication: $targetMonth $targetYear"

$pipelineLog = Join-Path $RepoPath 'data\pipeline_log.json'

if (-not $Force) {
    $existing = Get-LatestLogRecord -LogPath $pipelineLog -TargetMonth $targetMonth -TargetYear $targetYear
    if ($null -ne $existing -and $existing.status -eq 'success') {
        Write-Log "$targetMonth $targetYear already ingested on origin/main (run_at $($existing.run_at)). Nothing to do."
        Write-Log "=== Finished: already up to date ==="
        exit $EXIT_OK
    }
}

# --- Ingest ----------------------------------------------------------------------------------------

Write-Log "Running pipeline.monthly"
Push-Location $RepoPath
try {
    & $Python -m pipeline.monthly --month $targetMonth --year $targetYear
    $pipelineExit = $LASTEXITCODE
} finally {
    Pop-Location
}
Write-Log "pipeline.monthly exited with $pipelineExit"

# pipeline.monthly returns 1 for both "failed" and "not_published", so the exit code alone cannot
# distinguish a real problem from running before NHS Digital has published. The log record can.
$record = Get-LatestLogRecord -LogPath $pipelineLog -TargetMonth $targetMonth -TargetYear $targetYear
if ($null -eq $record) {
    Write-Log "pipeline.monthly wrote no log record for $targetMonth $targetYear." 'ERROR'
    exit $EXIT_FAILED
}

switch ($record.status) {
    'not_published' {
        Write-Log "$targetMonth $targetYear is not published yet. Will retry on the next scheduled run."
        Write-Log "=== Finished: not published ==="
        exit $EXIT_OK
    }
    'failed' {
        Write-Log "Ingestion failed: $($record.error)" 'ERROR'
        exit $EXIT_FAILED
    }
    'success' {
        Write-Log "Ingested $($record.practices_ingested) practices."
    }
    default {
        Write-Log "Unexpected pipeline status '$($record.status)'." 'ERROR'
        exit $EXIT_FAILED
    }
}

# --- Re-join enrichment ------------------------------------------------------------------------------

# pipeline.monthly writes the newly ingested month's mapping rows straight from the NHS extract, which
# carries no IMD or ONSPD columns. Without this step IMD_DECILE is entirely NaN for the latest
# snapshot, and build_dashboard_cache.py dies in cluster_practices: SimpleImputer silently drops an
# all-NaN column, so the imputed matrix has fewer columns than the frame it is rebuilt with
# ("Shape of passed values is (6129, 2), indices imply (6129, 3)"). join_enrichment.py rewrites
# data/processed/mapping.parquet in place, re-enriching every month including the new one.
Write-Log "Re-joining IMD/ONSPD enrichment"
Push-Location $RepoPath
try {
    & $Python scripts/join_enrichment.py
    $enrichExit = $LASTEXITCODE
} finally {
    Pop-Location
}
if ($enrichExit -ne 0) {
    Write-Log "join_enrichment.py failed with exit code $enrichExit; not committing an unenriched refresh." 'ERROR'
    exit $EXIT_FAILED
}

# --- Rebuild the dashboard cache -------------------------------------------------------------------

Write-Log "Rebuilding dashboard cache"
Push-Location $RepoPath
try {
    & $Python scripts/build_dashboard_cache.py --skip-anomalies
    $cacheExit = $LASTEXITCODE
} finally {
    Pop-Location
}
if ($cacheExit -ne 0) {
    Write-Log "build_dashboard_cache.py failed with exit code $cacheExit; not committing a partial refresh." 'ERROR'
    exit $EXIT_FAILED
}

# --- Commit and push --------------------------------------------------------------------------------

& git -C $RepoPath diff --quiet -- data/processed/ data/pipeline_log.json
$hasChanges = ($LASTEXITCODE -ne 0)
if (-not $hasChanges) {
    Write-Log "Pipeline succeeded but produced no data changes. Nothing to commit."
    Write-Log "=== Finished: no changes ==="
    exit $EXIT_OK
}

Invoke-Git @('config', 'user.name', 'nhs-gp-refresh (local)') | Out-Null
Invoke-Git @('config', 'user.email', 'jasonadarsono@gmail.com') | Out-Null
Invoke-Git @('add', '--', 'data/processed/', 'data/pipeline_log.json') | Out-Null

# No [skip ci] here, unlike the old CI-side commit: this push is what a downstream forecast-cache
# workflow needs to trigger on.
$message = "data: monthly pipeline refresh ($targetMonth $targetYear)"
Invoke-Git @('commit', '-m', $message) | Out-Null
Write-Log "Committed: $message"

if ($NoPush) {
    Write-Log "-NoPush set; leaving the commit local at '$RepoPath'."
    Write-Log "=== Finished: committed, not pushed ==="
    exit $EXIT_OK
}

Invoke-Git @('push', 'origin', 'main') | Out-Null
Write-Log "Pushed to origin/main."
Write-Log "=== Finished: refreshed ==="
exit $EXIT_OK
