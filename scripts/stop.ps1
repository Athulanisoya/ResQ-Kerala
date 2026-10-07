$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$processFile = Join-Path $projectRoot '.runtime\api-process.json'
if (Test-Path -LiteralPath $processFile) {
    $saved = Get-Content -LiteralPath $processFile -Raw | ConvertFrom-Json
    $apiProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $($saved.pid)"
    if ($apiProcess -and $apiProcess.CommandLine.Contains($projectRoot) -and
        $apiProcess.CommandLine.Contains('uvicorn backend.main:app')) {
        $children = Get-CimInstance Win32_Process -Filter "ParentProcessId = $($saved.pid)"
        foreach ($child in $children) {
            if ($child.Name -eq 'python.exe' -and $child.CommandLine.Contains('uvicorn backend.main:app')) {
                Stop-Process -Id $child.ProcessId -Force
            }
        }
        Stop-Process -Id $apiProcess.ProcessId -Force -ErrorAction SilentlyContinue
    }
    Remove-Item -LiteralPath $processFile
}
$dataDirectory = Join-Path $projectRoot '.runtime\postgres'
if (Test-Path -LiteralPath (Join-Path $dataDirectory 'PG_VERSION')) {
    $pgControl = 'C:\Program Files\PostgreSQL\18\bin\pg_ctl.exe'
    & $pgControl -D $dataDirectory status *> $null
    if ($LASTEXITCODE -eq 0) {
        & $pgControl -D $dataDirectory -m fast -w stop
        if ($LASTEXITCODE -ne 0) { throw 'Project database did not stop.' }
    }
}
Write-Host 'Project API and local database stopped.'
