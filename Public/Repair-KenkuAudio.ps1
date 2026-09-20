<#
.SYNOPSIS
    Снимает энергосбережение с процессов Kenku FM (лечит заикание звука).

.DESCRIPTION
    Windows 11 переводит фоновые процессы в efficiency mode (EcoQoS):
    поток исполняется на пониженной частоте и с фоновым приоритетом.
    Chromium сам просит об этом для окон, которые не видны, а окно
    плеера Kenku скрыто всегда — поэтому именно оно, отдающее звук в
    драйвер, и оказывается задушенным. Данные при этом подаются вовремя
    (буфер уходит на десятки секунд вперёд, событий waiting нет), но
    рендер в устройство не успевает, и слышны микрообрывы.

    Команда отключает троттлинг через SetProcessInformation и поднимает
    класс приоритета. Chromium может вернуть троттлинг при смене
    видимости окон, поэтому команду вызывает и New-Playlist после
    каждой публикации.

.PARAMETER Priority
    Класс приоритета для процессов Kenku. По умолчанию AboveNormal;
    High имеет смысл, только если заикание осталось.

.PARAMETER AllCores
    Не ограничивать процессы производительными ядрами. По умолчанию
    Kenku прижимается к ним: у гибридных процессоров планировщик
    ссылает фоновые потоки на низкопроизводительные ядра, и звук на
    них не успевает. Нативные плееры такого не требуют — они просят у
    Windows класс Pro Audio через MMCSS, а Chromium для скрытого окна
    этого не делает.

.PARAMETER TimeCritical
    Поднимать потоки до предельного приоритета вместо высокого. Мера
    крайняя: такой поток вытесняет почти всё остальное.

.EXAMPLE
    Repair-KenkuAudio
#>
function Repair-KenkuAudio {
    [CmdletBinding(SupportsShouldProcess)]
    param(
        [ValidateSet('Normal', 'AboveNormal', 'High')]
        [string] $Priority = 'AboveNormal',

        [switch] $AllCores,

        [switch] $TimeCritical
    )

    $processes = @(Get-Process -Name 'kenku-fm' -ErrorAction SilentlyContinue)
    if (-not $processes) {
        Write-Warning 'Kenku FM не запущен.'
        return
    }

    Add-KenkuThrottlingType
    $mask = if ($AllCores) { 0 } else { Get-PerformanceCoreMask }

    foreach ($process in $processes) {
        if (-not $PSCmdlet.ShouldProcess("kenku-fm (PID $($process.Id))",
                'снять энергосбережение')) {
            continue
        }

        $was = $process.PriorityClass
        $throttled = $null
        $cleared = [Roll.ProcessPower]::DisableThrottling($process.Id, [ref]$throttled)

        try { $process.PriorityClass = $Priority }
        catch { Write-Verbose "приоритет не сменился: $($_.Exception.Message)" }

        if ($mask) {
            try { $process.ProcessorAffinity = [IntPtr] $mask }
            catch { Write-Verbose "affinity не сменилась: $($_.Exception.Message)" }
        }

        # Класс процесса потоки не поднимает: Chromium держит часть
        # своих потоков в фоновом режиме, и звук страдает именно от
        # этого.
        $raised = 0
        $process.Refresh()
        foreach ($thread in $process.Threads) {
            if ([Roll.ProcessPower]::RaiseThread($thread.Id, $TimeCritical)) {
                $raised++
            }
        }

        [pscustomobject] @{
            Id           = $process.Id
            WasPriority  = $was
            WasThrottled = $throttled
            Throttling   = if ($cleared) { 'снято' } else { 'не удалось' }
            Priority     = $process.PriorityClass
            Cores        = '0x{0:X}' -f [int64]$process.ProcessorAffinity
            Threads      = '{0}/{1}' -f $raised, $process.Threads.Count
        }
    }
}
