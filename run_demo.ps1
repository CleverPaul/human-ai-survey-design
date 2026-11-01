param(
    [string]$Python = 'python',
    [int]$Port = 8765
)
$ErrorActionPreference = 'Stop'
if (-not (Test-Path -LiteralPath $Python)) {
    $Python = (Get-Command python -ErrorAction Stop).Source
}
Write-Host "Open http://127.0.0.1:$Port in your browser. Press Ctrl+C here to stop."
& $Python (Join-Path $PSScriptRoot 'app.py') --port $Port
