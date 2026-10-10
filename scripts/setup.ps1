param([switch]$SkipInstall, [string]$PythonCommand = 'python')
$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $ProjectRoot
New-Item -ItemType Directory -Path '.runtime\tmp' -Force | Out-Null
$env:TEMP = Join-Path $ProjectRoot '.runtime\tmp'
$env:TMP = $env:TEMP
function Assert-Exit([string]$Operation) { if ($LASTEXITCODE -ne 0) { throw "$Operation failed (exit $LASTEXITCODE)." } }
$pythonPath = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
if (-not $SkipInstall) {
    if (-not (Test-Path -LiteralPath $pythonPath)) { & $PythonCommand -m venv .venv; Assert-Exit 'Virtual environment setup' }
    & $pythonPath -m pip install -r requirements.txt --disable-pip-version-check
    Assert-Exit 'Python dependency installation'
    Push-Location -LiteralPath 'frontend'
    try { & npm.cmd ci --no-audit --no-fund; Assert-Exit 'Frontend dependency installation' } finally { Pop-Location }
} elseif (-not (Test-Path -LiteralPath $pythonPath)) {
    $pythonPath = Join-Path (Split-Path -Parent $ProjectRoot) '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $pythonPath)) { throw 'Run setup without -SkipInstall to install dependencies.' }
}
& $pythonPath -m scripts.configure
Assert-Exit 'Local configuration setup'
& $pythonPath -m backend.seed
Assert-Exit 'Authentication account provisioning (PostgreSQL must be running)'
@{python=$pythonPath} | ConvertTo-Json | Set-Content -LiteralPath '.runtime\setup.json' -Encoding utf8
Write-Host 'Athul Week 1 setup complete. Sign-in details: .runtime/demo-accounts.json'
Write-Host 'Run .\scripts\start.ps1 to open the authentication demo on port 5175.'
