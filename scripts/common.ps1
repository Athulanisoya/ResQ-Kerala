$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$RuntimePath = Join-Path $ProjectRoot '.runtime'
$setupPath = Join-Path $RuntimePath 'setup.json'
if (-not (Test-Path -LiteralPath $setupPath)) { throw 'Run .\scripts\setup.ps1 first.' }
$Setup = Get-Content -LiteralPath $setupPath -Raw | ConvertFrom-Json
$expectedPython = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
if ([IO.Path]::GetFullPath($Setup.python) -ne [IO.Path]::GetFullPath($expectedPython)) {
    throw 'The saved Python path belongs to another workspace. Run setup again.'
}
function Test-WorkspaceProcess([int]$ProcessId) {
    $info = Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId" -ErrorAction SilentlyContinue
    if (-not $info -or -not $info.CommandLine) { return $false }
    return $info.CommandLine.Contains('web.app:app') -and $info.CommandLine.Contains('--port 8013') -and $info.CommandLine.Contains($ProjectRoot) -and $info.CommandLine.Contains('--app-dir')
}
function Find-WorkspaceListener {
    $listeners = @(Get-NetTCPConnection -LocalPort 8013 -State Listen -ErrorAction SilentlyContinue)
    if (-not $listeners.Count) { return $null }
    $serviceId = $listeners[0].OwningProcess
    if (-not (Test-WorkspaceProcess $serviceId)) { throw 'Port 8013 is occupied by another application.' }
    return Get-Process -Id $serviceId
}
function New-ProcessRecord($Process) {
    return @{name='web'; id=$Process.Id; started_ticks=$Process.StartTime.ToUniversalTime().Ticks.ToString()}
}
function Stop-RecordedProcess($Record) {
    $process = Get-Process -Id $Record.id -ErrorAction SilentlyContinue
    if ($process -and $Record.started_ticks -and $process.StartTime.ToUniversalTime().Ticks.ToString() -eq $Record.started_ticks -and (Test-WorkspaceProcess $Record.id)) {
        Stop-Process -Id $Record.id
    }
}
function Wait-Http([string]$Url) {
    $deadline = [DateTime]::UtcNow.AddSeconds(25)
    do {
        try { if ((Invoke-WebRequest $Url -TimeoutSec 2 -UseBasicParsing).StatusCode -eq 200) { return } } catch {}
        Start-Sleep -Milliseconds 350
    } while ([DateTime]::UtcNow -lt $deadline)
    throw "Service did not become ready: $Url. Check .runtime/web-error.log and .runtime/postgres.log."
}
