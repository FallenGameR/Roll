<#
.SYNOPSIS
    Запускает Kenku FM так, чтобы звук меньше рвался.

.DESCRIPTION
    Запуск из меню Пуск даёт голый процесс: Windows переводит скрытое
    окно плеера в энергосбережение, а Chromium ставит его рендереру
    приоритет Idle. Эта команда запускает Kenku с флагами против
    фонового режима, сразу снимает троттлинг и открывает отладочный
    порт, чтобы New-Playlist потом цеплялась к уже запущенному
    экземпляру, а не перезапускала его посреди сессии.

    Если Kenku уже работает, команда его не трогает: только чинит
    приоритеты. Заикание это уменьшает, но не убирает совсем — оно
    заложено в самом плеере.

.PARAMETER Restart
    Перезапустить Kenku, даже если он уже работает. Нужно, когда он
    был запущен из меню Пуск и потому без флагов.

.PARAMETER NoCardStyle
    Не накладывать патч оформления карточек (двухстрочные подписи с
    обводкой). Нужен только при отладке самого патча.

.PARAMETER NoWatch
    Не запускать сторожа приоритетов. По умолчанию сторож работает
    фоном и повторяет лечение раз в полминуты: Windows возвращает
    процессам энергосбережение, а Chromium создаёт новые потоки с
    низким приоритетом, поэтому разовая правка выдыхается за пару
    минут.

.EXAMPLE
    Start-Kenku

.EXAMPLE
    Start-Kenku -Restart
#>
function Start-Kenku {
    [CmdletBinding(SupportsShouldProcess)]
    param(
        [switch] $Restart,
        [switch] $NoCardStyle,
        [switch] $NoWatch,
        [int] $Port = 9222
    )

    $running = @(Get-Process -Name 'kenku-fm' -ErrorAction SilentlyContinue)

    if ($running -and -not $Restart) {
        if (Test-KenkuDebugPort -Port $Port) {
            Write-Verbose 'Kenku уже запущен с отладочным портом.'
            if (-not $NoCardStyle) { Set-KenkuTitleStyle }
        }        else {
            Write-Warning ('Kenku запущен без флагов - вероятно, из меню ' +
                'Пуск. Приоритеты починю, но для флагов нужен ' +
                '-Restart.')
        }
        if (-not $NoWatch) { Start-KenkuAudioWatcher }
        return Repair-KenkuAudio
    }

    if (-not $PSCmdlet.ShouldProcess('Kenku FM', 'запустить')) { return }

    # Патч оформления живёт в HTML окна плеера и переживает
    # перезапуски, поэтому «не накладывать» его не убирает — снимать
    # нужно явно, и обязательно до старта окна.
    if ($NoCardStyle) { Set-KenkuTitleStyle -Disable }
    else { Set-KenkuTitleStyle }

    Start-KenkuDebugSession -Port $Port
    if (-not $NoWatch) { Start-KenkuAudioWatcher }
    Repair-KenkuAudio
}
