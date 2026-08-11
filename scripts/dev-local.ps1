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
  - Ensures demo user (demo@getbeam.fyi; password from BEAM_DEMO_PASSWORD, else password123)
  - Starts uvicorn (:8000) and Next.js (:3000), waits for health
  - Starts the configured Cloudflare named tunnel for a public API_BASE_URL
  - Opens http://localhost:3000/login

.USAGE
  .\scripts\dev-local.ps1
  .\scripts\dev-local.ps1 -SkipInstall
  .\scripts\dev-local.ps1 -MigrateOnly
  .\scripts\dev-local.ps1 -NoBrowser
  .\scripts\dev-local.ps1 -NoTunnel
#>
[CmdletBinding()]
param(
  [switch]$SkipInstall,
  [switch]$MigrateOnly,
  [switch]$NoBrowser,
  [switch]$FullSeed,
  [switch]$NoTunnel,
  [string]$TunnelConfig = (Join-Path $env:USERPROFILE ".cloudflared\config-beam.yml")
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $Root

function Write-Step($msg) { Write-Host "[dev-local] $msg" -ForegroundColor Cyan }
function Write-Warn($msg) { Write-Host "[dev-local] $msg" -ForegroundColor Yellow }
function Write-Fail($msg) { Write-Host "[dev-local] $msg" -ForegroundColor Red }

function Get-EnvValue([string]$Text, [string]$Name) {
  $line = $Text -split "\r?\n" |
    Where-Object { $_ -match "^\s*$([regex]::Escape($Name))=" } |
    Select-Object -Last 1
  if (-not $line) { return "" }
  return (($line -split "=", 2)[1]).Trim()
}

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
    Write-Warn "NEXT_PUBLIC_API_URL looks remote - local JWT login needs http://localhost:8000"
  }
}

# --- Env files ------------------------------------------------
Ensure-EnvFile (Join-Path $Root ".env.example") (Join-Path $Root ".env") ".env"
Ensure-EnvFile (Join-Path $Root "apps\web\.env.example") (Join-Path $Root "apps\web\.env.local") "apps\web\.env.local"
Normalize-WebEnvLocal

$EnvText = Get-Content "$Root\.env" -Raw
$ApiBaseUrl = (Get-EnvValue $EnvText "API_BASE_URL").TrimEnd("/")
$PublicTrackerReady = $false
if ($EnvText -match "supabase|railway\.app|amazonaws\.com") {
  Write-Fail "ABORT: .env DATABASE_URL looks remote. Point it at localhost:5433 for local dev."
  exit 1
}
if ($EnvText -notmatch "localhost:5433" -and $EnvText -match "DATABASE_URL=") {
  Write-Warn "DATABASE_URL should use localhost:5433 (Docker). Native Postgres often owns :5432."
}

# --- Docker ---------------------------------------------------
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
    $tcp = Test-NetConnection -ComputerName 127.0.0.1 -Port 5433 -WarningAction SilentlyContinue
    if ($tcp.TcpTestSucceeded) { $ready = $true; break }
  } catch {}
  Start-Sleep -Seconds 1
}
if (-not $ready) {
  Write-Fail "Postgres not reachable on localhost:5433"
  exit 1
}
Write-Step "Postgres is up on :5433"

# --- Python venv ----------------------------------------------
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

# --- Migrate --------------------------------------------------
Write-Step "Running alembic upgrade head..."
$env:PYTHONPATH = "$Root"
& $VenvPython -m alembic -c apps/api/alembic.ini upgrade head
if ($LASTEXITCODE -ne 0) { Write-Fail "alembic failed"; exit 1 }

Write-Step "Ensuring demo user (demo@getbeam.fyi)..."
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

# --- Web deps -------------------------------------------------
$NodeModules = Join-Path $Root "apps\web\node_modules"
if ((-not $SkipInstall) -or (-not (Test-Path $NodeModules))) {
  Write-Step "Installing web deps (npm)..."
  Push-Location (Join-Path $Root "apps\web")
  npm install
  if ($LASTEXITCODE -ne 0) { Pop-Location; Write-Fail "npm install failed"; exit 1 }
  Pop-Location
}

# --- Stop stale listeners on 8000/3000 (optional best-effort) -
function Stop-Port([int]$Port) {
  # Killing only the socket owner is not enough for `uvicorn --reload`: it runs a
  # supervisor plus a worker, and on a Store-Python install the worker shows up as
  # python3.11.exe (spawned via `-c "from multiprocessing.spawn import ..."`) while
  # the supervisor is the venv python. Kill the owner alone and the supervisor
  # respawns a worker that keeps serving with the OLD settings — .env is read once
  # at import, so an edited API_BASE_URL silently never takes effect and the pixel
  # snippet keeps advertising a hostname that no longer resolves. The symptom is
  # brutal to diagnose because /health still answers 200.
  #
  # So: kill every process whose command line mentions uvicorn (supervisor and its
  # PowerShell host), then the port owner, then confirm the port is actually free.
  Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -and $_.CommandLine -match 'uvicorn' -and $_.ProcessId -ne $PID } |
    ForEach-Object {
      try {
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
        Write-Warn "Stopped uvicorn process (pid $($_.ProcessId))"
      } catch {}
    }
  # Reload workers are spawned via multiprocessing and carry no 'uvicorn' text.
  Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object {
      $_.Name -like 'python*' -and $_.CommandLine -and
      $_.CommandLine -match 'multiprocessing\.spawn'
    } |
    ForEach-Object {
      try {
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
        Write-Warn "Stopped reload worker (pid $($_.ProcessId))"
      } catch {}
    }
  for ($attempt = 0; $attempt -lt 5; $attempt++) {
    $owners = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
    if (-not $owners) { return }
    foreach ($o in $owners) {
      try {
        Stop-Process -Id $o.OwningProcess -Force -ErrorAction SilentlyContinue
        Write-Warn "Stopped process on port $Port (pid $($o.OwningProcess))"
      } catch {}
    }
    Start-Sleep -Seconds 2
  }
  if (@(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)) {
    Write-Warn "Port $Port is STILL held after 5 attempts. A stale server there will serve the OLD .env - check for a detached python process before trusting anything it returns."
  }
}
Stop-Port 8000
Stop-Port 3000
Start-Sleep -Seconds 1

# --- Start API + Web in new windows ---------------------------
# Tee uvicorn stdout/stderr into $Root\.dev-local-api.log (mirrors dev-local.sh)
# so scripts\watch-local-logs.ps1 can read the current API session while the
# output still shows live in the API PowerShell window.
$ApiLog = Join-Path $Root '.dev-local-api.log'
$ApiCmd = @"
Set-Location '$Root'
`$env:PYTHONPATH = '$Root'
Write-Host '[API] http://localhost:8000/health' -ForegroundColor Green
Write-Host '[API] logging to $ApiLog' -ForegroundColor DarkGray
# Truncate on each start so watchers see a fresh session.
Set-Content -Path '$ApiLog' -Value "[`$(Get-Date -Format o)] API starting"
& '$VenvPython' -m uvicorn apps.api.main:app --reload --host 0.0.0.0 --port 8000 *>&1 |
  ForEach-Object { `$line = `$_.ToString(); Add-Content -Path '$ApiLog' -Value `$line; `$_ }
"@

$WebCmd = @"
Set-Location '$Root\apps\web'
Write-Host '[WEB] http://localhost:3000/login  (JWT local auth)' -ForegroundColor Green
npm run dev
"@

Write-Step "Opening API window (uvicorn :8000)..."
Start-Process powershell -ArgumentList "-NoExit", "-Command", $ApiCmd
Write-Step "API logs tee'd to $ApiLog (view: .\scripts\watch-local-logs.ps1)"

Write-Step "Waiting for API /health..."
$apiOk = $false
for ($i = 0; $i -lt 60; $i++) {
  try {
    $r = Invoke-WebRequest -Uri "http://127.0.0.1:8000/health" -UseBasicParsing -TimeoutSec 2
    if ($r.StatusCode -eq 200) { $apiOk = $true; break }
  } catch {}
  Start-Sleep -Seconds 1
}
if (-not $apiOk) { Write-Warn "API health not ready yet - continuing; check the API window" }
else { Write-Step "API is healthy" }

# --- Optional stable public API tunnel ------------------------
if (-not $NoTunnel -and $ApiBaseUrl -match "^https://") {
  $ApiHost = ([uri]$ApiBaseUrl).Host
  $Cloudflared = Get-Command cloudflared -ErrorAction SilentlyContinue
  if (-not $Cloudflared) {
    Write-Warn "cloudflared not found; public API URL was not started: $ApiBaseUrl"
  } elseif (-not (Test-Path $TunnelConfig)) {
    Write-Warn "Tunnel config not found: $TunnelConfig"
  } else {
    $ResolvedTunnelConfig = (Resolve-Path $TunnelConfig).Path
    $TunnelText = Get-Content $ResolvedTunnelConfig -Raw
    if ($TunnelText -notmatch "(?m)^\s*-\s*hostname:\s*$([regex]::Escape($ApiHost))\s*$") {
      Write-Warn "Tunnel config does not route $ApiHost; skipping public tunnel"
    } else {
      & $Cloudflared.Source tunnel --config $ResolvedTunnelConfig ingress validate | Out-Host
      if ($LASTEXITCODE -ne 0) {
        Write-Warn "Tunnel ingress validation failed; public tunnel was not started"
      } else {
        $RequiredPaths = @("/pixel/tracker.js", "/api/v1/events/ingest", "/health/ready")
        $TunnelRulesSafe = $true
        foreach ($path in $RequiredPaths) {
          $rule = (& $Cloudflared.Source tunnel --config $ResolvedTunnelConfig ingress rule "$ApiBaseUrl$path" 2>&1 | Out-String)
          if ($LASTEXITCODE -ne 0 -or $rule -match "service:\s*http_status:404") {
            Write-Warn "Tunnel config does not expose required path: $path"
            $TunnelRulesSafe = $false
          }
        }
        $blockedRule = (& $Cloudflared.Source tunnel --config $ResolvedTunnelConfig ingress rule "$ApiBaseUrl/api/v1/auth/login" 2>&1 | Out-String)
        if ($LASTEXITCODE -ne 0 -or $blockedRule -notmatch "service:\s*http_status:404") {
          Write-Warn "Tunnel config exposes more than the pixel surface; public tunnel was not started"
          $TunnelRulesSafe = $false
        }
        # Parse the ingress list into rule objects so the shape checks can be
        # scoped to ONE hostname. The config now carries three hostnames with very
        # different blast radii - the locked-down pixel host, the full UAT API, and
        # the dashboard - so counting rules across the whole file (what this did
        # before) would reject a valid config, and the natural response to that is
        # to loosen the check until it stops checking anything. The invariant worth
        # keeping is narrower and stronger: the host named by API_BASE_URL exposes
        # exactly the three pixel paths and 404s everything else. Other hostnames
        # are deliberately none of this check's business.
        $Rules = @()
        $Current = $null
        foreach ($line in ($TunnelText -split "`r?`n")) {
          if ($line -match "^\s*-\s+hostname:\s*(.+?)\s*$") {
            if ($Current) { $Rules += $Current }
            $Current = [pscustomobject]@{ Hostname = $Matches[1].Trim(); Path = $null; Service = $null }
          } elseif ($line -match "^\s*-\s+service:\s*(.+?)\s*$") {
            if ($Current) { $Rules += $Current }
            $Current = [pscustomobject]@{ Hostname = $null; Path = $null; Service = $Matches[1].Trim() }
          } elseif ($Current -and $line -match "^\s+path:\s*(.+?)\s*$") {
            $Current.Path = $Matches[1].Trim()
          } elseif ($Current -and $line -match "^\s+service:\s*(.+?)\s*$") {
            $Current.Service = $Matches[1].Trim()
          }
        }
        if ($Current) { $Rules += $Current }

        $PixelRules = @($Rules | Where-Object { $_.Hostname -eq $ApiHost })
        $PixelPathRules = @($PixelRules | Where-Object { $_.Path })
        $ConfiguredPaths = @($PixelPathRules | ForEach-Object { $_.Path })
        $ExpectedPaths = @(
          "^/pixel/tracker\.js$",
          "^/api/v1/events/ingest$",
          "^/health/ready$"
        )
        $UnexpectedPaths = @($ConfiguredPaths | Where-Object { $_ -notin $ExpectedPaths })
        $MissingPaths = @($ExpectedPaths | Where-Object { $_ -notin $ConfiguredPaths })
        $BadOrigins = @($PixelPathRules | Where-Object { $_.Service -ne "http://127.0.0.1:8000" })
        # Per-host catch-all, not just the file's final rule: with several
        # hostnames present, relying on the trailing 404 means a rule added later
        # for another host could silently start answering for this one.
        $PixelCatchAll = @($PixelRules | Where-Object { (-not $_.Path) -and $_.Service -eq "http_status:404" })
        $FinalRule = $Rules[-1]
        if (
          $ConfiguredPaths.Count -ne 3 -or
          $UnexpectedPaths.Count -ne 0 -or $MissingPaths.Count -ne 0 -or
          $BadOrigins.Count -ne 0 -or $PixelCatchAll.Count -ne 1 -or
          $FinalRule.Hostname -or $FinalRule.Service -ne "http_status:404"
        ) {
          Write-Warn "Tunnel config must expose exactly the three pixel paths on $ApiHost and 404 the rest"
          $TunnelRulesSafe = $false
        }

        if ($TunnelRulesSafe) {
          $ConfigPattern = [regex]::Escape($ResolvedTunnelConfig)
          $TunnelProcess = Get-CimInstance Win32_Process -Filter "Name = 'cloudflared.exe'" -ErrorAction SilentlyContinue |
            Where-Object { $_.CommandLine -match $ConfigPattern } |
            Select-Object -First 1
          if ($TunnelProcess -and (Get-Item $ResolvedTunnelConfig).LastWriteTime -gt $TunnelProcess.CreationDate) {
            Write-Warn "Tunnel config changed after process start; restarting pid $($TunnelProcess.ProcessId)"
            Stop-Process -Id $TunnelProcess.ProcessId -Force
            Start-Sleep -Seconds 1
            $TunnelProcess = $null
          }
          $TunnelMayBeRunning = $true
          if ($TunnelProcess) {
            Write-Step "Reusing Cloudflare tunnel (pid $($TunnelProcess.ProcessId))"
          } else {
            $TunnelLog = Join-Path $env:TEMP "beam-cloudflared.log"
            try {
              Start-Process -FilePath $Cloudflared.Source -ArgumentList @(
                "tunnel", "--config", "`"$ResolvedTunnelConfig`"",
                "--logfile", "`"$TunnelLog`"", "--loglevel", "info", "run"
              ) -WindowStyle Hidden
              Write-Step "Started Cloudflare tunnel (log: $TunnelLog)"
            } catch {
              Write-Warn "Could not start Cloudflare tunnel: $($_.Exception.Message)"
              $TunnelMayBeRunning = $false
            }
          }

          if ($TunnelMayBeRunning) {
            $publicOk = $false
            for ($i = 0; $i -lt 30; $i++) {
              try {
                $r = Invoke-WebRequest -Uri "$ApiBaseUrl/health/ready" -UseBasicParsing -TimeoutSec 3
                if ($r.StatusCode -eq 200) { $publicOk = $true; break }
              } catch {}
              Start-Sleep -Seconds 1
            }
            if ($publicOk) {
              try {
              $tracker = Invoke-WebRequest -Uri "$ApiBaseUrl/pixel/tracker.js" -UseBasicParsing -TimeoutSec 5
              if ($tracker.StatusCode -eq 200 -and $tracker.Headers["Content-Type"] -match "javascript") {
                $blockedStatus = $null
                try {
                  $blocked = Invoke-WebRequest -Uri "$ApiBaseUrl/api/v1/auth/login" -UseBasicParsing -TimeoutSec 5
                  $blockedStatus = [int]$blocked.StatusCode
                } catch {
                  if ($_.Exception.Response) {
                    $blockedStatus = [int]$_.Exception.Response.StatusCode
                  }
                }
                if ($blockedStatus -eq 404) {
                  $PublicTrackerReady = $true
                  Write-Step "Public pixel surface ready; non-pixel API routes are blocked"
                } else {
                  Write-Warn "Public tunnel safety check failed: auth route returned $blockedStatus instead of 404"
                }
              } else {
                  Write-Warn "Public API is ready, but tracker response is unexpected: $ApiBaseUrl/pixel/tracker.js"
                }
              } catch {
                Write-Warn "Public API is ready, but tracker could not be loaded: $($_.Exception.Message)"
              }
            } else {
              Write-Warn "Public API is not ready yet: $ApiBaseUrl (check cloudflared log)"
            }
          }
        } else {
          Write-Warn "Expected path-scoped tunnel rules; see docs/deployment-guide.md"
        }
      }
    }
  }
} elseif ($NoTunnel) {
  Write-Step "Skipping Cloudflare tunnel (-NoTunnel)"
}

Write-Step "Opening Web window (Next.js :3000)..."
Start-Process powershell -ArgumentList "-NoExit", "-Command", $WebCmd

Write-Step "Waiting for Web :3000..."
$webOk = $false
for ($i = 0; $i -lt 90; $i++) {
  try {
    $r = Invoke-WebRequest -Uri "http://127.0.0.1:3000/login" -UseBasicParsing -TimeoutSec 2
    if ($r.StatusCode -eq 200) { $webOk = $true; break }
  } catch {}
  Start-Sleep -Seconds 1
}
if (-not $webOk) { Write-Warn "Web not ready yet - open http://localhost:3000/login when Next finishes compiling" }
else { Write-Step "Web is up" }

if (-not $NoBrowser) {
  Start-Process "http://localhost:3000/login"
}

Write-Host ""
Write-Step "Local stack ready."
Write-Host "  API:   http://localhost:8000/health"
if ($PublicTrackerReady) { Write-Host "  Pixel: $ApiBaseUrl/pixel/tracker.js" }
Write-Host "  Login: http://localhost:3000/login"
$DemoPwLine = if ($EnvText -match "(?m)^\s*BEAM_DEMO_PASSWORD\s*=\s*\S") {
  "  Demo:  demo@getbeam.fyi / (BEAM_DEMO_PASSWORD from .env)"
} else {
  "  Demo:  demo@getbeam.fyi / password123"
}
Write-Host $DemoPwLine
Write-Host "  (Clerk empty -> JWT local auth. Set NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY for Clerk.)"
Write-Host ""
Write-Warn "Close the two PowerShell windows to stop API/Web. Docker: docker compose -f infra/docker-compose.yml stop"
