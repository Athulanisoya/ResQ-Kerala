$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$RuntimePath = Join-Path $ProjectRoot '.runtime'
$setupPath = Join-Path $RuntimePath 'setup.json'
if (-not (Test-Path -LiteralPath $setupPath)) { throw 'Run .\scripts\setup.ps1 first.' }
$Setup = Get-Content -LiteralPath $setupPath -Raw | ConvertFrom-Json
function Test-WorkspaceProcess([int]$ProcessId, [string]$Name) {
    $info = Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId" -ErrorAction SilentlyContinue
    if (-not $info -or -not $info.CommandLine) { return $false }
    if ($Name -eq 'backend') { return $info.CommandLine.Contains($Setup.python) -and $info.CommandLine.Contains('backend.main:app') -and $info.CommandLine.Contains('--port 8012') }
    return $info.CommandLine.Contains((Join-Path $ProjectRoot 'frontend\node_modules\vite\bin\vite.js'))
}
function Find-WorkspaceListener([string]$Name, [int]$Port) {
    $listeners = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
    if (-not $listeners.Count) { return $null }
    $serviceId = $listeners[0].OwningProcess
    if (-not (Test-WorkspaceProcess $serviceId $Name)) { throw "Port $Port is occupied by another application." }
    return Get-Process -Id $serviceId
}
function New-ProcessRecord($Process, [string]$Name) {
    return @{name=$Name; id=$Process.Id; started_ticks=$Process.StartTime.ToUniversalTime().Ticks.ToString()}
}
function Stop-RecordedProcess($Record) {
    $process = Get-Process -Id $Record.id -ErrorAction SilentlyContinue
    if ($process -and $Record.started_ticks -and $process.StartTime.ToUniversalTime().Ticks.ToString() -eq $Record.started_ticks -and (Test-WorkspaceProcess $Record.id $Record.name)) { Stop-Process -Id $Record.id }
}
function Wait-Http([string]$Url) {
    $deadline = [DateTime]::UtcNow.AddSeconds(25)
    do {
        try { if ((Invoke-WebRequest $Url -TimeoutSec 2 -UseBasicParsing).StatusCode -eq 200) { return } } catch {}
        Start-Sleep -Milliseconds 350
    } while ([DateTime]::UtcNow -lt $deadline)
    throw "Service did not become ready: $Url. Check .runtime log files and PostgreSQL availability."
}
