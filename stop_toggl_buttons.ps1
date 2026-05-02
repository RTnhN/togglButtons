$patterns = @(
    'toggl_buttons\.main',
    'run_toggl_buttons_hidden\.vbs',
    'run_toggl_buttons\.cmd',
    'toggl-buttons'
)

$processes = Get-CimInstance Win32_Process | Where-Object {
    $commandLine = $_.CommandLine
    if ([string]::IsNullOrWhiteSpace($commandLine)) {
        return $false
    }

    foreach ($pattern in $patterns) {
        if ($commandLine -match $pattern) {
            return $true
        }
    }

    return $false
}

if (-not $processes) {
    Write-Host 'No toggl-buttons process found.'
    exit 0
}

foreach ($process in $processes) {
    Write-Host ("Stopping PID {0} ({1})" -f $process.ProcessId, $process.Name)
    Stop-Process -Id $process.ProcessId -Force
}
