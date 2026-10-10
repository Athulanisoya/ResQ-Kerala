. (Join-Path $PSScriptRoot 'common.ps1')
Set-Location -LiteralPath $ProjectRoot
$processFile = Join-Path $RuntimePath 'processes.json'
$records = @()
$created = @()
try {
    $backend = Find-WorkspaceListener 'backend' 8012
    if (-not $backend) {
        $python = $Setup.python
        $launcher = Start-Process -FilePath $python -ArgumentList @('-m','uvicorn','backend.main:app','--host','127.0.0.1','--port','8012') -WorkingDirectory $ProjectRoot -RedirectStandardOutput (Join-Path $RuntimePath 'backend.log') -RedirectStandardError (Join-Path $RuntimePath 'backend-error.log') -WindowStyle Hidden -PassThru
        Wait-Http 'http://127.0.0.1:8012/health'
        # Windows venv's python.exe is a redirector. Record the actual listener.
        $backend = Find-WorkspaceListener 'backend' 8012
        if (-not $backend) { throw 'The backend listener was not found.' }
        $created += New-ProcessRecord $backend 'backend'
    } else { Wait-Http 'http://127.0.0.1:8012/health' }
    $records += New-ProcessRecord $backend 'backend'
    $records | ConvertTo-Json -AsArray | Set-Content -LiteralPath $processFile -Encoding utf8

    $frontend = Find-WorkspaceListener 'frontend' 5175
    if (-not $frontend) {
        $node = (Get-Command node.exe).Source
        $vite = '"' + (Join-Path $ProjectRoot 'frontend\node_modules\vite\bin\vite.js') + '"'
        $launcher = Start-Process -FilePath $node -ArgumentList @($vite) -WorkingDirectory (Join-Path $ProjectRoot 'frontend') -RedirectStandardOutput (Join-Path $RuntimePath 'frontend.log') -RedirectStandardError (Join-Path $RuntimePath 'frontend-error.log') -WindowStyle Hidden -PassThru
        Wait-Http 'http://127.0.0.1:5175/'
        $frontend = Find-WorkspaceListener 'frontend' 5175
        if (-not $frontend) { throw 'The frontend listener was not found.' }
        $created += New-ProcessRecord $frontend 'frontend'
    } else { Wait-Http 'http://127.0.0.1:5175/' }
    $records += New-ProcessRecord $frontend 'frontend'
    $records | ConvertTo-Json -AsArray | Set-Content -LiteralPath $processFile -Encoding utf8
    if (-not $created.Count) { Write-Host 'Existing project services reused.' }
    Write-Host 'Athul Week 1: http://127.0.0.1:5175'
    Write-Host 'API documentation: http://127.0.0.1:8012/docs'
} catch {
    foreach ($record in $created) { Stop-RecordedProcess $record }
    throw
}
