. (Join-Path $PSScriptRoot 'common.ps1')
$recordFile = Join-Path $RuntimePath 'processes.json'
if (Test-Path -LiteralPath $recordFile) {
    foreach ($record in (Get-Content -LiteralPath $recordFile -Raw | ConvertFrom-Json)) { Stop-RecordedProcess $record }
    Remove-Item -LiteralPath $recordFile
}
Write-Host 'Recorded Athul authentication services stopped.'
