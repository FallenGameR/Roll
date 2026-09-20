<#
    Остановка Winamp перед правкой его каталога.

    Убивать процесс нельзя: при жёстком завершении Winamp не
    сохраняет ни рейтинги треков, ни базу медиатеки, и расставленные
    во время игры звёзды просто пропадают. Поэтому окну посылается
    обычная команда закрытия, как по нажатию крестика, и только если
    плеер не ответил за десять секунд, применяется сила.
#>
function Stop-WinampGracefully {
    [CmdletBinding()]
    param([int] $TimeoutSeconds = 10)

    $processes = @(Get-Process -Name 'winamp' -ErrorAction SilentlyContinue)
    if (-not $processes) { return $null }

    $path = $processes[0].Path
    foreach ($process in $processes) {
        $null = $process.CloseMainWindow()
    }

    foreach ($attempt in 1..$TimeoutSeconds) {
        Start-Sleep -Seconds 1
        if (-not (Get-Process -Name 'winamp' -ErrorAction SilentlyContinue)) {
            return $path
        }
    }

    Write-Warning ('Winamp не закрылся сам, завершаю принудительно - ' +
        'звёзды этого сеанса могут не сохраниться.')
    foreach ($process in @(Get-Process -Name 'winamp' -ErrorAction SilentlyContinue)) {
        Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Seconds 2
    return $path
}
