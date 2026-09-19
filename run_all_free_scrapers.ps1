param(
    [switch]$IncludeHN
)

$ErrorActionPreference = "Continue"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    $Python = Join-Path $ProjectRoot "venv\Scripts\python.exe"
}

if (-not (Test-Path $ProjectRoot)) {
    Write-Host "ERROR: Project root not found: $ProjectRoot"
    exit 1
}

if (-not (Test-Path $Python)) {
    Write-Host "ERROR: venv Python not found: $Python"
    exit 1
}

Set-Location $ProjectRoot

$LogDir = Join-Path $ProjectRoot "logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$Stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$LogFile = Join-Path $LogDir "free_scrapers_$Stamp.log"

$Scrapers = @(
    "reddit",
    "news",
    "arxiv",
    "jobs",
    "github",
    "huggingface",
    "stackoverflow",
    "paperswithcode",
    "packages",
    "yc"
)

if ($IncludeHN) {
    $Scrapers = @("hn") + $Scrapers
}

$Results = @()

Write-Host ""
Write-Host "============================================================"
Write-Host " AI Opportunity Radar - Free/No-Extra-Key Scraper Run"
Write-Host "============================================================"
Write-Host "Project: $ProjectRoot"
Write-Host "Log:     $LogFile"
Write-Host "HN:      $(if ($IncludeHN) {'included'} else {'skipped (already populated)'})"
Write-Host ""

"=== FREE SCRAPER RUN START $(Get-Date -Format o) ===" | Out-File $LogFile -Encoding utf8

foreach ($Scraper in $Scrapers) {
    $Start = Get-Date

    Write-Host ""
    Write-Host "------------------------------------------------------------"
    Write-Host "RUNNING: $Scraper"
    Write-Host "START:   $($Start.ToString('yyyy-MM-dd HH:mm:ss'))"
    Write-Host "------------------------------------------------------------"

    "`n=== SCRAPER: $Scraper | START $($Start.ToString('o')) ===" |
        Out-File $LogFile -Append -Encoding utf8

    & $Python "main.py" "--scraper" $Scraper 2>&1 |
        Tee-Object -FilePath $LogFile -Append

    $ExitCode = $LASTEXITCODE
    $End = Get-Date
    $Elapsed = [math]::Round(($End - $Start).TotalSeconds, 1)

    if ($ExitCode -eq 0) {
        $Status = "PASS"
        Write-Host "RESULT: PASS ($Elapsed sec)"
    }
    else {
        $Status = "FAIL"
        Write-Host "RESULT: FAIL (exit code $ExitCode, $Elapsed sec)"
        Write-Host "Continuing to the next source..."
    }

    $Results += [PSCustomObject]@{
        Scraper = $Scraper
        Status = $Status
        ExitCode = $ExitCode
        Seconds = $Elapsed
    }

    "=== SCRAPER: $Scraper | END | STATUS=$Status | EXIT=$ExitCode | SECONDS=$Elapsed ===" |
        Out-File $LogFile -Append -Encoding utf8
}

Write-Host ""
Write-Host "============================================================"
Write-Host " Running local sentiment on any newly collected posts"
Write-Host "============================================================"

$SentimentStart = Get-Date
& $Python "main.py" "--processor" "sentiment" 2>&1 |
    Tee-Object -FilePath $LogFile -Append
$SentimentExit = $LASTEXITCODE
$SentimentElapsed = [math]::Round(((Get-Date) - $SentimentStart).TotalSeconds, 1)

$Results += [PSCustomObject]@{
    Scraper = "processor:sentiment"
    Status = $(if ($SentimentExit -eq 0) {"PASS"} else {"FAIL"})
    ExitCode = $SentimentExit
    Seconds = $SentimentElapsed
}

Write-Host ""
Write-Host "============================================================"
Write-Host " FINAL DATABASE SUMMARY"
Write-Host "============================================================"

& $Python "main.py" "--summary" 2>&1 |
    Tee-Object -FilePath $LogFile -Append

Write-Host ""
Write-Host "============================================================"
Write-Host " RUN RESULTS"
Write-Host "============================================================"
$Results | Format-Table -AutoSize

Write-Host ""
Write-Host "Finished."
Write-Host "Full log saved to:"
Write-Host $LogFile
Write-Host ""
Write-Host "If any source says FAIL, do NOT rerun everything."
Write-Host "Send the final RUN RESULTS plus the error section for that source."
