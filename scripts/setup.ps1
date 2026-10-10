param([switch]$SkipInstall, [string]$PythonCommand = 'python')
$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $ProjectRoot
New-Item -ItemType Directory -Path '.runtime\tmp' -Force | Out-Null
$env:TEMP = Join-Path $ProjectRoot '.runtime\tmp'
$env:TMP = $env:TEMP
function Assert-Exit([string]$Operation) { if ($LASTEXITCODE -ne 0) { throw "$Operation failed (exit $LASTEXITCODE)." } }
$pythonPath = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    if ($SkipInstall) { throw 'Run setup without -SkipInstall to create this workspace virtual environment.' }
    & $PythonCommand -m venv .venv
    Assert-Exit 'Virtual environment creation'
}
if (-not $SkipInstall) {
    & $pythonPath -m pip --version *> $null
    if ($LASTEXITCODE -ne 0) {
        & $pythonPath -m ensurepip --upgrade
        Assert-Exit 'Virtual environment pip recovery'
    }
    & $pythonPath -m pip install -r requirements.txt --disable-pip-version-check
    Assert-Exit 'Python dependency installation'
    & $pythonPath -m pip check
    Assert-Exit 'Python dependency validation'
}
& $pythonPath -m scripts.setup_local_db
Assert-Exit 'Workspace PostgreSQL setup'
& $pythonPath -m backend.seed
Assert-Exit 'Week 1 demonstration account and team provisioning'
@{python=$pythonPath; port=8013; database_port=5443; project_root=$ProjectRoot} | ConvertTo-Json | Set-Content -LiteralPath '.runtime\setup.json' -Encoding utf8
Write-Host 'ResQ Kerala Week 1 setup complete. Private sign-in details: .runtime/demo-accounts.json'
Write-Host 'Run .\scripts\start.ps1 to start http://127.0.0.1:8013.'
