<#
.SYNOPSIS
    Останавливает голосовую диктовку.

.DESCRIPTION
    Находит процессы python и pythonw, у которых в командной строке есть
    ptt.py, и останавливает каждый по PID. Venv поднимает два процесса,
    заглушку и базовый интерпретатор, поэтому их обычно два.

.EXAMPLE
    Stop-Dictation
#>
function Stop-Dictation {
    [CmdletBinding()]
    param()

    $found = @(Get-DictationProcess)
    if (-not $found) {
        Write-Host 'Диктовка не запущена.'
        return
    }
    foreach ($process in $found) {
        Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue
    }
    # Без ожидания сразу следующий Start-Dictation ещё видит умирающий процесс
    # и отвечает, что диктовка уже запущена.
    Wait-Process -Id $found.ProcessId -Timeout 10 -ErrorAction SilentlyContinue
    Write-Host "Остановлено процессов: $($found.Count)"
}
