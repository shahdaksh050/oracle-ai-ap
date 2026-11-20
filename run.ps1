[CmdletBinding()]
param(
    [ValidateRange(1, 65535)]
    [int] $Port = 8765,
    [switch] $Desktop
)

$ErrorActionPreference = 'Stop'
$url = "http://127.0.0.1:$Port"
$previousConfig = $env:AP_CONFIG

function Invoke-Checked([string] $Program, [string[]] $Arguments) {
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Program $($Arguments -join ' ') exited with code $LASTEXITCODE."
    }
}

Push-Location -LiteralPath $PSScriptRoot
try {
    $env:AP_CONFIG = Join-Path $PSScriptRoot '.runtime\app.json'
    $listeners = [Net.NetworkInformation.IPGlobalProperties]::GetIPGlobalProperties().GetActiveTcpListeners()
    $inUse = $listeners | Where-Object { $_.Port -eq $Port -and $_.Address.ToString() -in '127.0.0.1', '0.0.0.0', '::' }
    if ($inUse) {
        try {
            $schema = Invoke-RestMethod "$url/openapi.json" -TimeoutSec 3
            $dashboard = Invoke-WebRequest $url -UseBasicParsing -TimeoutSec 3
            $appRunning = $schema.info.title -like 'Enterprise Oracle * Accounts Payable' -and $dashboard.Content -match '<div id="root">'
        } catch {
            $appRunning = $false
        }
        if (-not $appRunning) {
            throw "Port $Port is occupied. Choose another web port with .\run.ps1 -Port 8766."
        }
    }

    Invoke-Checked 'uv' @('sync', '--frozen', '--group', 'dev')
    $python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
    Invoke-Checked $python @('-m', 'ap.admin', 'init')
    if (-not (Test-Path -LiteralPath '.runtime\supplier-invoice.pdf' -PathType Leaf)) {
        Invoke-Checked $python @('-m', 'ap.admin', 'sample', '--number', 'DEMO-1001')
    }

    Write-Host "Sign-in keys: $(Join-Path $PSScriptRoot '.runtime\demo-keys.json')"
    if ($inUse) {
        Write-Host "The workspace is already running at $url"
        if ($Desktop) {
            & $python desktop.py
        }
        return
    }

    Invoke-Checked 'npm.cmd' @('ci', '--prefix', 'web', '--no-audit', '--no-fund')
    Invoke-Checked 'npm.cmd' @('run', 'build', '--prefix', 'web')
    if ($Desktop) {
        Start-Process -FilePath $python -ArgumentList "-m uvicorn ap.api:app --host 127.0.0.1 --port $Port --no-access-log" -WindowStyle Hidden
        & $python desktop.py
        return
    }
    Write-Host "Open $url when Uvicorn reports startup complete. Press Ctrl+C here to stop the web server."
    Invoke-Checked $python @('-m', 'uvicorn', 'ap.api:app', '--host', '127.0.0.1', '--port', "$Port", '--no-access-log')
} finally {
    $env:AP_CONFIG = $previousConfig
    Pop-Location
}
