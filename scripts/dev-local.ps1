<#
.SYNOPSIS
  Start Beam local stack on Windows (Docker PG+Redis + API + Web + demo user).

.DESCRIPTION
  Full local boot for JWT auth (no Clerk required):
  - Ensures .env and apps/web/.env.local exist
  - Clears empty Clerk keys so Next does not half-enable Clerk
  - Starts postgres (:5433) + redis via docker compose
  - Creates/uses .venv, installs deps unless -SkipInstall
  - Runs alembic upgrade head
  - Ensures demo user (demo@getbeam.fyi / password123)
  - Starts uvicorn (:8000) and Next.js (:3000), waits for health
  - Opens http://localhost:3000/login

.USAGE
  .\scripts\dev-local.ps1
  .\scripts\dev-local.ps1 -SkipInstall
  .\scripts\dev-local.ps1 -MigrateOnly
  .\scripts\dev-local.ps1 -NoBrowser
#>
[CmdletBinding()]
param(
  [switch]$SkipInstall,
  [switch]$MigrateOnly,
  [switch]$NoBrowser,
  [switch]$FullSeed
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $Root

function Write-Step($msg) { Write-Host "[dev-local] $msg" -ForegroundColor Cyan }
function Write-Warn($msg) { Write-Host "[dev-local] $msg" -ForegroundColor Yellow }
function Write-Fail($msg) { Write-Host "[dev-local] $msg" -ForegroundColor Red }

function Ensure-EnvFile([string]$Example, [string]$Target, [string]$Label) {
  if (-not (Test-Path $Target)) {
    if (-not (Test-Path $Example)) { Write-Fail "Missing $Example"; exit 1 }
    Copy-Item $Example $Target
    Write-Step "Created $Label from example"
  } else {
    Write-Step "Using existing $Label"
  }
}

function Normalize-WebEnvLocal {
  # Empty NEXT_PUBLIC_CLERK_* can still confuse some tooling; keep keys blank
  # but ensure the file documents local JWT mode.
  $path = Join-Path $Root "apps\web\.env.local"
  $text = Get-Content $path -Raw
  if ($text -notmatch "NEXT_PUBLIC_API_URL=") {
    Write-Fail "apps\web\.env.local missing NEXT_PUBLIC_API_URL"
    exit 1
  }
  # Force localhost API if someone pointed at prod
  if ($text -match "NEXT_PUBLIC_API_URL=https?://(?!localhost|127\.0\.0\.1)") {
    Write-Warn "NEXT_PUBLIC_API_URL looks remote — local JWT login needs http://localhost:8000"
  }
}

# ─── Env files ───────────────────────────────────────────
Ensure-EnvFile (Join-Path $Root ".env.example") (Join-Path $Root ".env") ".env"
Ensure-EnvFile (Join-Path $Root "apps\web\.env.example") (Join-Path $Root "apps\web\.env.local") "apps\web\.env.local"
Normalize-WebEnvLocal

$EnvText = Get-Content "$Root\.env" -Raw
if ($EnvText -match "supabase|railway\.app|amazonaws\.com") {
  Write-Fail "ABORT: .env DATABASE_URL looks remote. Point it at localhost:5433 for local dev."
  exit 1
}
if ($EnvText -notmatch "localhost:5433" -and $EnvText -match "DATABASE_URL=") {
  Write-Warn "DATABASE_URL should use localhost:5433 (Docker). Native Postgres often owns :5432."
}

# ─── Docker ──────────────────────────────────────────────
Write-Step "Starting Docker postgres (:5433) + redis..."
docker compose -f infra/docker-compose.yml up -d postgres redis
if ($LASTEXITCODE -ne 0) {
  Write-Fail "docker compose failed. Is Docker Desktop running?"
  exit 1
}

Write-Step "Waiting for Docker Postgres on :5433..."
$ready = $false
for ($i = 0; $i -lt 40; $i++) {
  try {
    $tcp = Test-NetConnection -ComputerName localhost -Port 5433 -WarningAction SilentlyContinue
    if ($tcp.TcpTestSucceeded) { $ready = $true; break }
  } catch {}
  Start-Sleep -Seconds 1
}
if (-not $ready) {
  Write-Fail "Postgres not reachable on localhost:5433"
  exit 1
}
Write-Step "Postgres is up on :5433"

# ─── Python venv ─────────────────────────────────────────
$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
$VenvPip = Join-Path $Root ".venv\Scripts\pip.exe"
if (-not (Test-Path $VenvPython)) {
  Write-Step "Creating .venv..."
  python -m venv .venv
}
if (-not $SkipInstall) {
  Write-Step "Installing Python deps (requirements.txt)..."
  & $VenvPip install -r (Join-Path $Root "requirements.txt")
  if ($LASTEXITCODE -ne 0) { Write-Fail "pip install failed"; exit 1 }
}

# ─── Migrate ─────────────────────────────────────────────
Write-Step "Running alembic upgrade head..."
$env:PYTHONPATH = "$Root"
& $VenvPython -m alembic -c apps/api/alembic.ini upgrade head
if ($LASTEXITCODE -ne 0) { Write-Fail "alembic failed"; exit 1 }

Write-Step "Ensuring demo user (demo@getbeam.fyi / password123)..."
& $VenvPython -m scripts.ensure_demo_user
if ($LASTEXITCODE -ne 0) { Write-Fail "ensure_demo_user failed"; exit 1 }

if ($FullSeed) {
  Write-Step "Full seed (visitors/campaigns)..."
  & $VenvPython -m scripts.seed
}

if ($MigrateOnly) {
  Write-Step "Migrate + demo user done."
  exit 0
}

# ─── Web deps ────────────────────────────────────────────
$NodeModules = Join-Path $Root "apps\web\node_modules"
if ((-not $SkipInstall) -or (-not (Test-Path $NodeModules))) {
  Write-Step "Installing web deps (npm)..."
  Push-Location (Join-Path $Root "apps\web")
  npm install
  if ($LASTEXITCODE -ne 0) { Pop-Location; Write-Fail "npm install failed"; exit 1 }
  Pop-Location
}

# ─── Stop stale listeners on 8000/3000 (optional best-effort) ─
function Stop-Port([int]$Port) {
  Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
    ForEach-Object {
      try {
        Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue
        Write-Warn "Stopped process on port $Port (pid $($_.OwningProcess))"
      } catch {}
    }
}
Stop-Port 8000
Stop-Port 3000
Start-Sleep -Seconds 1

# ─── Start API + Web in new windows ──────────────────────
$ApiCmd = @"
Set-Location '$Root'
`$env:PYTHONPATH = '$Root'
Write-Host '[API] http://localhost:8000/health' -ForegroundColor Green
& '$VenvPython' -m uvicorn apps.api.main:app --reload --host 0.0.0.0 --port 8000
"@

$WebCmd = @"
Set-Location '$Root\apps\web'
Write-Host '[WEB] http://localhost:3000/login  (JWT local auth)' -ForegroundColor Green
npm run dev
"@

Write-Step "Opening API window (uvicorn :8000)..."
Start-Process powershell -ArgumentList "-NoExit", "-Command", $ApiCmd

Write-Step "Waiting for API /health..."
$apiOk = $false
for ($i = 0; $i -lt 60; $i++) {
  try {
    $r = Invoke-WebRequest -Uri "http://localhost:8000/health" -UseBasicParsing -TimeoutSec 2
    if ($r.StatusCode -eq 200) { $apiOk = $true; break }
  } catch {}
  Start-Sleep -Seconds 1
}
if (-not $apiOk) { Write-Warn "API health not ready yet — continuing; check the API window" }
else { Write-Step "API is healthy" }

Write-Step "Opening Web window (Next.js :3000)..."
Start-Process powershell -ArgumentList "-NoExit", "-Command", $WebCmd

Write-Step "Waiting for Web :3000..."
$webOk = $false
for ($i = 0; $i -lt 90; $i++) {
  try {
    $r = Invoke-WebRequest -Uri "http://localhost:3000/login" -UseBasicParsing -TimeoutSec 2
    if ($r.StatusCode -eq 200) { $webOk = $true; break }
  } catch {}
  Start-Sleep -Seconds 1
}
if (-not $webOk) { Write-Warn "Web not ready yet — open http://localhost:3000/login when Next finishes compiling" }
else { Write-Step "Web is up" }

if (-not $NoBrowser) {
  Start-Process "http://localhost:3000/login"
}

Write-Host ""
Write-Step "Local stack ready."
Write-Host "  API:   http://localhost:8000/health"
Write-Host "  Login: http://localhost:3000/login"
Write-Host "  Demo:  demo@getbeam.fyi / password123"
Write-Host "  (Clerk empty → JWT local auth. Set NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY for Clerk.)"
Write-Host ""
Write-Warn "Close the two PowerShell windows to stop API/Web. Docker: docker compose -f infra/docker-compose.yml stop"
