<#
    Сторож приоритетов Kenku: Windows и Chromium возвращают процессам
    энергосбережение и опускают вновь созданные потоки, поэтому разовое
    лечение выдыхается за пару минут работы плеера.

    Сторож живёт отдельным скрытым процессом и умирает вместе с Kenku.

    Опознаётся по PID-файлу, а не по подстроке в командной строке:
    поиск по подстроке находит и саму вызывающую сессию PowerShell (в
    её команде это слово тоже встречается), из-за чего сессия убивала
    сама себя, а дубли сторожей всё равно плодились.
#>
function Get-KenkuWatcherPidPath {
    Join-Path $env:TEMP 'roll-kenku-watcher.pid'
}

function Get-KenkuWatcher {
    $path = Get-KenkuWatcherPidPath
    if (-not (Test-Path -LiteralPath $path)) { return $null }

    $id = 0
    if (-not [int]::TryParse((Get-Content -LiteralPath $path -Raw).Trim(), [ref]$id)) {
        return $null
    }

    $process = Get-Process -Id $id -ErrorAction SilentlyContinue
    if ($process -and $process.ProcessName -eq 'pwsh') { return $process }
    return $null
}

function Start-KenkuAudioWatcher {
    [CmdletBinding()]
    param([int] $IntervalSeconds = 10)

    if (Get-KenkuWatcher) {
        Write-Verbose 'Сторож уже работает.'
        return
    }

    $pwsh = Join-Path $env:LOCALAPPDATA 'Microsoft\WindowsApps\pwsh.exe'
    if (-not (Test-Path -LiteralPath $pwsh)) {
        $pwsh = (Get-Command pwsh -ErrorAction SilentlyContinue).Source
    }
    if (-not $pwsh) {
        Write-Warning 'PowerShell 7 не найден, сторож не запущен.'
        return
    }

    $pidPath = Get-KenkuWatcherPidPath
    $script = @"
Set-Content -LiteralPath '$pidPath' -Value `$PID
Import-Module C:\vaults\Roll\Roll.psd1 -Force
while (Get-Process -Name 'kenku-fm' -ErrorAction SilentlyContinue) {
    Repair-KenkuAudio -ErrorAction SilentlyContinue | Out-Null
    Start-Sleep -Seconds $IntervalSeconds
}
Remove-Item -LiteralPath '$pidPath' -ErrorAction SilentlyContinue
"@

    Start-Process -FilePath $pwsh -WindowStyle Hidden -ArgumentList @(
        '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', $script)
    Write-Verbose "Сторож запущен, интервал $IntervalSeconds с."
}

function Stop-KenkuAudioWatcher {
    [CmdletBinding()]
    param()

    $watcher = Get-KenkuWatcher
    if (-not $watcher) { return }
    Stop-Process -Id $watcher.Id -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath (Get-KenkuWatcherPidPath) -ErrorAction SilentlyContinue
}
