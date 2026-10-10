. (Join-Path $PSScriptRoot 'common.ps1')
Set-Location -LiteralPath $ProjectRoot
$recordFile = Join-Path $RuntimePath 'processes.json'
if (Test-Path -LiteralPath $recordFile) {
    foreach ($record in (Get-Content -LiteralPath $recordFile -Raw | ConvertFrom-Json)) { Stop-RecordedProcess $record }
    Remove-Item -LiteralPath $recordFile
}
& $Setup.python -m scripts.setup_local_db --stop
if ($LASTEXITCODE -ne 0) { throw 'Workspace PostgreSQL shutdown failed.' }
Write-Host 'Recorded Week 1 application and workspace PostgreSQL stopped.'
