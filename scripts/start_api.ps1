# PROJECT TITAN-X -- single-command start.
#
# Brings up EVERYTHING: Docker infrastructure (postgres/redis/qdrant), the
# API server, and the dashboard in your browser. Nothing else to run.
#
# Root must be the directory CONTAINING project_titan_x (i.e. TIS), not
# project_titan_x itself -- uvicorn imports "project_titan_x.api.main",
# which requires TIS on PYTHONPATH. This script's path is
# project_titan_x\scripts\start_api.ps1, so that's three levels up.
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectDir = Split-Path -Parent $ScriptDir
$Root = Split-Path -Parent $ProjectDir
Set-Location $Root
$env:PYTHONPATH = $Root

# The venv's own uvicorn, by absolute path. The previous version called a
# bare `uvicorn`, which only resolves if the venv happens to be activated
# in that shell or uvicorn is installed globally -- neither is true when
# this is launched by double-click, the main way it actually gets used.
$Uvicorn = Join-Path $ProjectDir ".venv\Scripts\uvicorn.exe"
if (-not (Test-Path $Uvicorn)) {
    Write-Host "ERROR: venv uvicorn not found at $Uvicorn" -ForegroundColor Red
    Write-Host "Run: pip install -r project_titan_x\requirements.txt" -ForegroundColor Yellow
    Read-Host "Press Enter to close"
    exit 1
}

# If the server is ALREADY up (a previous run left it running, or this
# script got double-clicked twice), just open the dashboard immediately
# instead of trying -- and failing -- to bind the port again, which used
# to look exactly like "nothing happens for minutes."
try {
    $already = Invoke-WebRequest -Uri "http://localhost:8000/health" -UseBasicParsing -TimeoutSec 2
    if ($already.StatusCode -eq 200) {
        Write-Host "PROJECT TITAN-X is already running -- opening the dashboard now."
        Start-Process "http://localhost:8000/dashboard"
        exit 0
    }
} catch {}

# ---------------------------------------------------------------------
# Infrastructure. Added 2026-09-14: previously this script started only
# the API and left `docker compose up -d postgres redis qdrant` as a
# separate manual step in the README -- so a normal double-click launch
# came up with no database, and the failure showed up later as degraded
# routes rather than as "you forgot a command".
#
# Only the three small pre-built service images are started, never the
# heavy custom `api` build in docker-compose.yml -- that would rebuild a
# full ML image on every launch.
# ---------------------------------------------------------------------
Write-Host "Checking Docker..." -ForegroundColor Cyan
$dockerOk = $false
try {
    docker info 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) { $dockerOk = $true }
} catch {}

if (-not $dockerOk) {
    $dd = "$env:ProgramFiles\Docker\Docker\Docker Desktop.exe"
    if (Test-Path $dd) {
        Write-Host "  Docker not running -- starting Docker Desktop (this takes ~30-60s)..." -ForegroundColor Yellow
        Start-Process $dd | Out-Null
        for ($i = 0; $i -lt 60; $i++) {
            Start-Sleep -Seconds 2
            try {
                docker info 2>&1 | Out-Null
                if ($LASTEXITCODE -eq 0) { $dockerOk = $true; break }
            } catch {}
        }
    } else {
        Write-Host "  Docker Desktop not found at $dd" -ForegroundColor Yellow
    }
}

if ($dockerOk) {
    Write-Host "  Docker ready -- starting postgres/redis/qdrant..." -ForegroundColor Cyan
    Push-Location $ProjectDir
    docker compose up -d postgres redis qdrant 2>&1 | Out-String | Write-Host
    Pop-Location
} else {
    # Deliberately a warning, not a hard stop: the API still starts and
    # most read-only analysis routes work without Postgres. Saying so
    # plainly beats failing silently or refusing to launch at all.
    Write-Host "  WARNING: Docker unavailable -- starting API anyway." -ForegroundColor Yellow
    Write-Host "  Trade journal / persistence routes will not work; analysis routes will." -ForegroundColor Yellow
}

# ---------------------------------------------------------------------
# Bind address. Changed 2026-09-14 from a hardcoded 0.0.0.0.
#
# 0.0.0.0 publishes all 94 routes to every machine on the network. This
# platform has no authentication unless API_KEY is set (see
# core/config/settings.py's own comment: "a single-operator local service
# needs a key"), and docs/PROJECT_AUDIT.md records an unauthenticated
# 0.0.0.0 bind as S1, its highest-severity finding. The README already
# tells people to use 127.0.0.1 for exactly this reason -- this script
# was contradicting it.
#
# So: loopback by default, and 0.0.0.0 ONLY when an API_KEY actually
# exists to protect it. To reach the dashboard from your phone, set
# API_KEY in project_titan_x\.env (any long random string you invent --
# nobody issues it) and relaunch.
# ---------------------------------------------------------------------
$envFile = Join-Path $ProjectDir ".env"
$hasApiKey = $false
if (Test-Path $envFile) {
    $hasApiKey = (Select-String -Path $envFile -Pattern '^\s*API_KEY\s*=\s*\S+' -Quiet)
}
if ($hasApiKey) {
    $BindHost = "0.0.0.0"
    Write-Host "API_KEY is set -- binding 0.0.0.0 (reachable on your network, key required)." -ForegroundColor Cyan
} else {
    $BindHost = "127.0.0.1"
    Write-Host "No API_KEY set -- binding 127.0.0.1 (this machine only)." -ForegroundColor Cyan
    Write-Host "  To reach it from another device: set API_KEY in project_titan_x\.env, then relaunch." -ForegroundColor DarkGray
}

Write-Host ""
Write-Host "Starting PROJECT TITAN-X API on http://localhost:8000" -ForegroundColor Green
Write-Host "Dashboard opens automatically once ready (usually well under a minute)."
Write-Host "The log lines below ARE the server actually starting -- this window is not frozen."
Write-Host ""

# Open the browser only once the server actually responds -- opening
# immediately would just show a connection error. Polls in the
# background while uvicorn's own real startup log prints to THIS window
# in the foreground below, so there's always visible proof of progress.
# 3-minute ceiling as a safety margin for a genuinely slow/cold machine
# (a clean local run measures ~30-40s without --reload).
Start-Job -ScriptBlock {
    for ($i = 0; $i -lt 90; $i++) {
        Start-Sleep -Seconds 2
        try {
            $resp = Invoke-WebRequest -Uri "http://localhost:8000/health" -UseBasicParsing -TimeoutSec 2
            if ($resp.StatusCode -eq 200) { Start-Process "http://localhost:8000/dashboard"; break }
        } catch {}
    }
} | Out-Null

# --reload is a DEV-ONLY convenience (auto-restart on code edits) that
# costs real startup time (a second watcher process, file-tree scanning)
# for zero benefit if you're not actively editing code -- removed from
# the default daily-use launch. Re-add --reload manually if developing.
& $Uvicorn project_titan_x.api.main:app --host $BindHost --port 8000
