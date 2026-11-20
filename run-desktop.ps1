[CmdletBinding()]
param(
    [ValidateRange(1, 65535)]
    [int] $Port = 8765
)

$ErrorActionPreference = 'Stop'
Push-Location -LiteralPath $PSScriptRoot
try {
    $python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path $python)) {
        .\run.ps1 -Port $Port
    } else {
        $env:PORT = "$Port"
        & $python desktop.py
    }
} finally {
    Pop-Location
}
