<#
.SYNOPSIS
  Local observability snapshot for Beam Lab / pixel debugging (Windows).

.DESCRIPTION
  Prints three sections: SERVICE (API health + logs + docker), DB (recent
  Postgres rows for a site), and BEAM LAB (site/pixel hosts + optional tail).
  Read-only snapshot - never mutates data, never crashes if docker/PG is down.

.USAGE
  .\scripts\watch-local-logs.ps1
  .\scripts\watch-local-logs.ps1 -Limit 50
  .\scripts\watch-local-logs.ps1 -Watch
  .\scripts\watch-local-logs.ps1 -TailBeamLab
#>
[CmdletBinding()]
param(
  [string]$SiteId = "site_92e8f1f8a71c",   # beamlab
  [int]$Limit = 20,
  [switch]$Watch,                          # refresh DB section every 5s until Ctrl+C
  [switch]$TailBeamLab,                     # after snapshot, run wrangler pages deployment tail
  [int]$ApiLogLines = 40
)

$ErrorActionPreference = "Continue"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$PgContainer = "infra-postgres-1"
$PgUser = "retarget"
$PgDb = "retarget_agent"
$PgPassword = "retarget_dev"

function Write-Header($msg) { Write-Host "`n=== $msg ===" -ForegroundColor Cyan }
function Write-Sub($msg)    { Write-Host "-- $msg" -ForegroundColor DarkCyan }
function Write-Ok($msg)     { Write-Host $msg -ForegroundColor Green }
function Write-Warn2($msg)  { Write-Host $msg -ForegroundColor Yellow }
function Write-Fail2($msg)  { Write-Host $msg -ForegroundColor Red }

function Test-DockerPg {
  try {
    docker exec $PgContainer pg_isready -U $PgUser 2>&1 | Out-Null
    return ($LASTEXITCODE -eq 0)
  } catch { return $false }
}

function Invoke-Psql([string]$Sql, [string]$Title) {
  Write-Sub $Title
  try {
    $out = docker exec -e PGPASSWORD=$PgPassword $PgContainer `
      psql -U $PgUser -d $PgDb -P pager=off -c $Sql 2>&1
    if ($LASTEXITCODE -ne 0) {
      Write-Warn2 "  (query failed) $out"
    } else {
      $out | ForEach-Object { Write-Host "  $_" }
    }
  } catch {
    Write-Warn2 "  (query error) $($_.Exception.Message)"
  }
}

# -------------------------------------------------------------
# A) SERVICE
# -------------------------------------------------------------
function Show-Service {
  Write-Header "A) SERVICE"

  # API health
  try {
    $r = Invoke-WebRequest -Uri "http://127.0.0.1:8000/health" -UseBasicParsing -TimeoutSec 3
    if ($r.StatusCode -eq 200) { Write-Ok "API /health: ok (200)" }
    else { Write-Warn2 "API /health: unexpected status $($r.StatusCode)" }
  } catch {
    Write-Fail2 "API /health: fail ($($_.Exception.Message))"
  }

  # API log tail
  $ApiLog = Join-Path $Root ".dev-local-api.log"
  if (Test-Path $ApiLog) {
    Write-Sub "API log (last $ApiLogLines lines: $ApiLog)"
    Get-Content $ApiLog -Tail $ApiLogLines | ForEach-Object { Write-Host "  $_" }
  } else {
    Write-Warn2 "API log not found: $ApiLog (start API via dev-local.ps1)"
  }

  # Cloudflared tunnel log tail
  $TunnelLog = Join-Path $env:TEMP "beam-cloudflared.log"
  if (Test-Path $TunnelLog) {
    Write-Sub "cloudflared log (last 20 lines: $TunnelLog)"
    Get-Content $TunnelLog -Tail 20 | ForEach-Object { Write-Host "  $_" }
  }

  # Docker compose status
  Write-Sub "docker compose ps (infra)"
  try {
    $ps = docker compose -f (Join-Path $Root "infra/docker-compose.yml") ps 2>&1
    if ($LASTEXITCODE -ne 0) { Write-Warn2 "  docker not available: $ps" }
    else { $ps | ForEach-Object { Write-Host "  $_" } }
  } catch {
    Write-Warn2 "  docker error: $($_.Exception.Message)"
  }

  # ClickHouse :8123 note (optional)
  try {
    $ch = Test-NetConnection -ComputerName 127.0.0.1 -Port 8123 -WarningAction SilentlyContinue
    if (-not $ch.TcpTestSucceeded) { Write-Warn2 "ClickHouse :8123 down (optional for pixel debugging)" }
  } catch {}
}

# -------------------------------------------------------------
# B) DB
# -------------------------------------------------------------
function Show-Db {
  Write-Header "B) DB (site $SiteId)"
  if (-not (Test-DockerPg)) {
    Write-Warn2 "Postgres container '$PgContainer' not reachable - skipping DB section."
    Write-Warn2 "Start it: docker compose -f infra/docker-compose.yml up -d postgres"
    return
  }

  $eventsSql = @"
SELECT created_at, event_type, left(url,60) AS url, visitor_id, ip_address, link_marker
FROM events WHERE site_id = '$SiteId'
ORDER BY created_at DESC LIMIT $Limit;
"@
  Invoke-Psql $eventsSql "Recent events (LIMIT $Limit)"

  $visitorsSql = @"
SELECT visitor_id, first_seen, last_seen, total_pageviews, is_bot_suspect, intent_score
FROM visitors WHERE site_id = '$SiteId'
ORDER BY last_seen DESC LIMIT 10;
"@
  Invoke-Psql $visitorsSql "Recent visitors (LIMIT 10)"

  $fetchSql = @"
SELECT created_at, vendor, raw_ua_token, tier, page_path, link_marker
FROM agent_fetch_events WHERE site_id = '$SiteId'
ORDER BY created_at DESC LIMIT 10;
"@
  Invoke-Psql $fetchSql "Recent agent_fetch_events (LIMIT 10)"

  $reqSql = @"
SELECT created_at, status_code, reason, site_id, duration_ms
FROM request_logs WHERE path ILIKE '%ingest%' OR site_id = '$SiteId'
ORDER BY created_at DESC LIMIT 10;
"@
  Invoke-Psql $reqSql "Recent request_logs (ingest OR site, LIMIT 10)"
}

# -------------------------------------------------------------
# C) BEAM LAB
# -------------------------------------------------------------
function Show-BeamLab {
  Write-Header "C) BEAM LAB"
  Write-Host "  Site URL:   https://beamlab.nhantown.com"
  Write-Host "  site_id:    $SiteId"
  Write-Host "  Pixel host: beam-dev.nhantown.com"
  if ($TailBeamLab) {
    Write-Sub "Tailing beam-lab Pages deployment (Ctrl+C to stop)"
    Push-Location (Join-Path $Root "infra/cloudflare/beam-lab")
    try {
      npx wrangler pages deployment tail --project-name beam-lab
    } finally {
      Pop-Location
    }
  } else {
    Write-Host "  Tail logs:  cd infra/cloudflare/beam-lab; npx wrangler pages deployment tail --project-name beam-lab"
    Write-Host "              (or re-run this script with -TailBeamLab)"
  }
}

# -------------------------------------------------------------
# Main
# -------------------------------------------------------------
Show-Service
if ($Watch) {
  Write-Warn2 "`n-Watch: refreshing DB section every 5s (Ctrl+C to stop)"
  while ($true) {
    Show-Db
    Start-Sleep -Seconds 5
  }
} else {
  Show-Db
  Show-BeamLab
}
