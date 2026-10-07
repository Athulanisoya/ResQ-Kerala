$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location -LiteralPath $projectRoot
try {
    & "$projectRoot\.venv\Scripts\python.exe" "$PSScriptRoot\start_local.py"
    if ($LASTEXITCODE -ne 0) { throw 'Application startup failed.' }
} finally {
    Pop-Location
}
