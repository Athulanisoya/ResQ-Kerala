. (Join-Path $PSScriptRoot 'common.ps1')
Set-Location -LiteralPath $ProjectRoot
& $Setup.python -m scripts.setup_local_db --start-only
if ($LASTEXITCODE -ne 0) { throw 'Workspace PostgreSQL startup failed.' }
$processFile = Join-Path $RuntimePath 'processes.json'
$created = @()
try {
    $web = Find-WorkspaceListener
    if (-not $web) {
        $arguments = @('-m','uvicorn','web.app:app','--host','127.0.0.1','--port','8013','--app-dir',('"' + $ProjectRoot + '"'))
        $launcher = Start-Process -FilePath $Setup.python -ArgumentList $arguments -WorkingDirectory $ProjectRoot -RedirectStandardOutput (Join-Path $RuntimePath 'web.log') -RedirectStandardError (Join-Path $RuntimePath 'web-error.log') -WindowStyle Hidden -PassThru
        $created += New-ProcessRecord $launcher
        Wait-Http 'http://127.0.0.1:8013/health'
        $web = Find-WorkspaceListener
        if (-not $web) { throw 'The Week 1 application listener was not found.' }
        $created += New-ProcessRecord $web
    } else {
        Wait-Http 'http://127.0.0.1:8013/health'
        Write-Host 'Existing workspace application reused.'
    }
    $record = New-ProcessRecord $web
    ConvertTo-Json -InputObject @($record) | Set-Content -LiteralPath $processFile -Encoding utf8
    Wait-Http 'http://127.0.0.1:8013/'
    Write-Host 'ResQ Kerala Week 1: http://127.0.0.1:8013'
    Write-Host 'API documentation: http://127.0.0.1:8013/docs'
} catch {
    if ($created.Count) {
        foreach ($record in $created) { Stop-RecordedProcess $record }
        # A Windows venv redirector can exit before its actual listener is ready.
        try {
            $failedListener = Find-WorkspaceListener
            if ($failedListener) { Stop-RecordedProcess (New-ProcessRecord $failedListener) }
        } catch {}
    }
    throw
}
