# start_ngrok.ps1
# ----------------
# Launches the Feedstock Advisor MCP HTTP server and opens an ngrok tunnel
# to expose it publicly.
#
# Prerequisites
# -------------
#   1. conda environment 'feedstock_advisor' must exist.
#   2. ngrok must be installed and on PATH  →  https://ngrok.com/download
#      After installing, authenticate once:
#        ngrok config add-authtoken <YOUR_NGROK_TOKEN>
#
# Usage
# -----
#   .\start_ngrok.ps1                         # default port 8000
#   .\start_ngrok.ps1 -Port 9000              # custom port
#   .\start_ngrok.ps1 -Port 8000 -NoBrowser   # skip opening ngrok dashboard
#
# What this script does
# ---------------------
#   1. Starts  server_http.py  in a new terminal window (conda env activated).
#   2. Waits up to 10 s for the server to accept connections on localhost.
#   3. Starts  ngrok http <port>  — prints the public HTTPS URL.
#   4. Prints the MCP endpoint URLs for both Streamable-HTTP and SSE clients.

param(
    [int]    $Port      = 8000,
    [string] $Host      = "127.0.0.1",
    [switch] $NoBrowser
)

$ErrorActionPreference = "Stop"

# ── helpers ──────────────────────────────────────────────────────────────────

function Write-Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Write-Ok($msg)   { Write-Host "    [OK] $msg"  -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "    [!!] $msg"  -ForegroundColor Yellow }

# ── 0. check ngrok ───────────────────────────────────────────────────────────

Write-Step "Checking prerequisites"

if (-not (Get-Command ngrok -ErrorAction SilentlyContinue)) {
    Write-Host @"

  ngrok is not installed or not on PATH.

  Install it:
    1. Download from  https://ngrok.com/download  (Windows ZIP)
    2. Extract ngrok.exe to  C:\Windows\System32\  (or any folder on PATH)
    3. Run:  ngrok config add-authtoken <YOUR_TOKEN>
       (Sign up free at https://dashboard.ngrok.com to get a token)

"@ -ForegroundColor Red
    exit 1
}
Write-Ok "ngrok found: $(ngrok version)"

# ── 1. resolve conda Python ──────────────────────────────────────────────────

Write-Step "Resolving conda environment 'feedstock_advisor'"

$condaExe = (Get-Command conda -ErrorAction SilentlyContinue)?.Source
if (-not $condaExe) { $condaExe = "$env:CONDA_EXE" }
if (-not $condaExe) {
    Write-Host "  conda not found on PATH. Activate the environment manually and re-run." -ForegroundColor Red
    exit 1
}

$pythonExe = & conda run -n feedstock_advisor python -c "import sys; print(sys.executable)" 2>$null
if (-not $pythonExe -or -not (Test-Path $pythonExe)) {
    Write-Host "  Could not resolve Python from 'feedstock_advisor' env." -ForegroundColor Red
    exit 1
}
Write-Ok "Python: $pythonExe"

# ── 2. start the MCP HTTP server ─────────────────────────────────────────────

Write-Step "Starting MCP HTTP server on $Host`:$Port"

$serverScript = Join-Path $PSScriptRoot "server_http.py"
$serverArgs   = @(
    "/k",
    "conda activate feedstock_advisor && set MCP_HOST=$Host && set MCP_PORT=$Port && `"$pythonExe`" `"$serverScript`""
)

$serverProc = Start-Process -FilePath "cmd.exe" `
    -ArgumentList $serverArgs `
    -PassThru

Write-Ok "Server process started (PID $($serverProc.Id)) in a new window."

# ── 3. wait for server to be ready ───────────────────────────────────────────

Write-Step "Waiting for server to accept connections…"

$ready    = $false
$deadline = (Get-Date).AddSeconds(15)

while ((Get-Date) -lt $deadline) {
    try {
        $tcp = [System.Net.Sockets.TcpClient]::new()
        $tcp.Connect($Host, $Port)
        $tcp.Close()
        $ready = $true
        break
    } catch {
        Start-Sleep -Milliseconds 500
    }
}

if (-not $ready) {
    Write-Warn "Server did not respond within 15 s — check the server window for errors."
    Write-Warn "Continuing anyway; ngrok tunnel may fail if server is not up."
} else {
    Write-Ok "Server is accepting connections on port $Port."
}

# ── 4. start ngrok tunnel ────────────────────────────────────────────────────

Write-Step "Opening ngrok tunnel → http://$Host`:$Port"

if ($NoBrowser) {
    $ngrokProc = Start-Process -FilePath "ngrok" `
        -ArgumentList @("http", $Port, "--log=stdout") `
        -PassThru -NoNewWindow
} else {
    $ngrokProc = Start-Process -FilePath "ngrok" `
        -ArgumentList @("http", $Port) `
        -PassThru
}

# Give ngrok 3 s to establish the tunnel then query its local API
Start-Sleep -Seconds 3

$ngrokUrl = $null
try {
    $tunnels  = Invoke-RestMethod "http://127.0.0.1:4040/api/tunnels" -ErrorAction Stop
    $ngrokUrl = ($tunnels.tunnels | Where-Object { $_.proto -eq "https" } | Select-Object -First 1).public_url
} catch {
    Write-Warn "Could not query ngrok API (http://127.0.0.1:4040). Check the ngrok window."
}

# ── 5. print summary ─────────────────────────────────────────────────────────

Write-Host ""
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor White
Write-Host "  Feedstock Advisor MCP — Public Endpoints" -ForegroundColor White
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor White

if ($ngrokUrl) {
    Write-Host ""
    Write-Host "  Streamable HTTP (preferred, MCP 2025-03):" -ForegroundColor Green
    Write-Host "    $ngrokUrl/mcp" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  Legacy SSE (for older MCP clients):" -ForegroundColor Green
    Write-Host "    $ngrokUrl/sse" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  ngrok dashboard : http://127.0.0.1:4040" -ForegroundColor DarkGray
} else {
    Write-Host ""
    Write-Host "  ngrok URL could not be determined automatically." -ForegroundColor Yellow
    Write-Host "  Check the ngrok window — the URL looks like:" -ForegroundColor Yellow
    Write-Host "    https://<id>.ngrok-free.app/mcp   (Streamable HTTP)" -ForegroundColor Yellow
    Write-Host "    https://<id>.ngrok-free.app/sse   (Legacy SSE)" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "  Local (no tunnel):" -ForegroundColor DarkGray
Write-Host "    http://$Host`:$Port/mcp" -ForegroundColor DarkGray
Write-Host "    http://$Host`:$Port/sse" -ForegroundColor DarkGray
Write-Host ""
Write-Host "  To stop: close the server window and the ngrok window." -ForegroundColor DarkGray
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor White
Write-Host ""
