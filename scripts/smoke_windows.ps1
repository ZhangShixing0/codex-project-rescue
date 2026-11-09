param([string]$Executable = (Join-Path (Split-Path $PSScriptRoot -Parent) 'dist/CodexProjectRescue.exe'))
$ErrorActionPreference = 'Stop'
$resolvedExecutable = (Resolve-Path -LiteralPath $Executable).Path
$demoRoot = Join-Path ([System.IO.Path]::GetTempPath()) ('rescue-smoke-' + [Guid]::NewGuid().ToString('N'))
$null = New-Item -ItemType Directory -Path $demoRoot
$previousCodexHome = $env:CODEX_HOME
$previousLocalAppData = $env:LOCALAPPDATA
try {
    $env:CODEX_HOME = Join-Path $demoRoot 'empty-profile'
    $env:LOCALAPPDATA = $demoRoot
    $launch = Start-Process -FilePath $resolvedExecutable -PassThru -WindowStyle Hidden
    $windowProcess = $null
    for ($attempt = 0; $attempt -lt 75; $attempt++) {
        $owned = @(Get-CimInstance Win32_Process -Filter "Name='CodexProjectRescue.exe'" |
            Where-Object { $_.ProcessId -eq $launch.Id -or $_.ParentProcessId -eq $launch.Id })
        foreach ($entry in $owned) {
            if ($entry.ExecutablePath -ne $resolvedExecutable) { continue }
            $candidate = Get-Process -Id $entry.ProcessId -ErrorAction SilentlyContinue
            if ($candidate -and $candidate.MainWindowHandle -ne 0) {
                $windowProcess = $candidate
                break
            }
        }
        if ($windowProcess) { break }
        Start-Sleep -Milliseconds 200
    }
    if (-not $windowProcess) { throw 'Packaged tool did not display a window.' }
    if ($windowProcess.MainWindowTitle -ne 'Codex项目恢复助手') { throw 'Unexpected preview window title.' }
    if (Test-Path -LiteralPath $env:CODEX_HOME) { throw 'Opening the tool unexpectedly created profile data.' }
    # Close only the exact executable launched by this check, never Codex itself.
    if (-not $windowProcess.CloseMainWindow()) { throw 'Cannot close the task-owned preview normally.' }
    if (-not $launch.WaitForExit(10000)) { throw 'Task-owned preview did not exit normally.' }
    if ($launch.ExitCode -ne 0) { throw ('Preview exit code: ' + $launch.ExitCode) }
    Write-Output 'Packaged GUI opened and exited normally; no real Codex profile was accessed.'
} finally {
    $env:CODEX_HOME = $previousCodexHome
    $env:LOCALAPPDATA = $previousLocalAppData
}
