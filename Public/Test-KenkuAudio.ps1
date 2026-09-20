<#
.SYNOPSIS
    Показывает, лечится ли звук у запущенного Kenku FM.

.DESCRIPTION
    Отвечает на вопрос «этот плеер открыт правильно или мимо нашего
    ярлыка»: есть ли поднятые приоритеты, прижаты ли процессы к
    производительным ядрам, жив ли сторож и открыт ли отладочный порт,
    без которого New-Playlist вынуждена перезапускать плеер.

    Если что-то не так, чинится без перезапуска: Start-Kenku.

.EXAMPLE
    Test-KenkuAudio
#>
function Test-KenkuAudio {
    [CmdletBinding()]
    param([int] $Port = 9222)

    $processes = @(Get-Process -Name 'kenku-fm' -ErrorAction SilentlyContinue)
    if (-not $processes) {
        return [pscustomobject] @{
            Запущен  = $false
            Вердикт  = 'Kenku не запущен'
        }
    }

    $lowPriority = @($processes |
        Where-Object { $_.PriorityClass -in 'Idle', 'BelowNormal', 'Normal' }).Count
    $lowThreads = 0
    foreach ($process in $processes) {
        $lowThreads += @($process.Threads |
            Where-Object { $_.PriorityLevel -ne 'Highest' }).Count
    }

    $watcher = Get-KenkuWatcher
    $debugPort = [bool] (Test-KenkuDebugPort -Port $Port)

    $problems = @()
    if (-not $watcher) { $problems += 'нет сторожа' }
    if (-not $debugPort) { $problems += 'нет отладочного порта' }
    if ($lowPriority) { $problems += "процессов с низким приоритетом: $lowPriority" }

    [pscustomobject] @{
        Запущен          = $true
        Процессов        = $processes.Count
        НизкийПриоритет  = $lowPriority
        ПотоковНеПоднято = $lowThreads
        Сторож           = [bool] $watcher
        ОтладочныйПорт   = $debugPort
        Вердикт          = if ($problems) {
            ($problems -join ', ') + '; выполни Start-Kenku'
        }
        else { 'всё в порядке' }
    }
}
