<#
    Kenku FM debugging session helpers used by New-Playlist.

    Playlists can only be written while the app is running with a Chrome
    DevTools Protocol port open, so these two take care of getting it
    into that state and of not losing data while doing so.
#>

<#
.SYNOPSIS
    True if Kenku FM is reachable over CDP and its player window exists.

.DESCRIPTION
    Checking the port alone isn't enough: Chromium opens the debugging
    port a few seconds before Kenku creates its player window, and that
    window is the one holding the persist:player LocalStorage key, so a
    write attempted in between fails with "no such target".
#>
function Test-KenkuDebugPort {
    param([int]$Port = 9222)

    try {
        $response = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/json/list" `
            -UseBasicParsing -TimeoutSec 2
        $targets = $response.Content | ConvertFrom-Json
        return [bool]($targets | Where-Object { $_.title -eq 'Kenku FM Player' })
    }
    catch {
        return $false
    }
}

<#
.SYNOPSIS
    Restarts Kenku FM with the CDP port open, backing up LocalStorage first.

.DESCRIPTION
    Kenku FM keeps its playlists in redux and flushes them to LocalStorage,
    so a running instance started without the port has to be stopped before
    we can attach - otherwise it would overwrite our write on exit. The
    LocalStorage folder is copied aside beforehand so a botched write can
    always be rolled back by restoring the newest .bak-* folder.
#>
function Start-KenkuDebugSession {
    param([int]$Port = 9222)

    $ErrorActionPreference = 'Stop'

    $exe = Join-Path $env:LOCALAPPDATA 'kenku-fm-win32-x64\kenku-fm.exe'
    if (-not (Test-Path -LiteralPath $exe)) {
        throw "Kenku FM not found: $exe"
    }

    foreach ($process in @(Get-Process -Name 'kenku-fm' -ErrorAction SilentlyContinue)) {
        # Дочерние процессы уходят вслед за главным, поэтому к моменту
        # своей очереди часть из них уже мертва.
        Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Seconds 2

    $storage = Join-Path $env:APPDATA 'Kenku FM\Local Storage'
    if (Test-Path -LiteralPath $storage) {
        $backup = "$storage.bak-$(Get-Date -Format yyyyMMdd-HHmmss)"
        Copy-Item -LiteralPath $storage -Destination $backup -Recurse -Force
        Write-Verbose "LocalStorage backed up to $backup"
    }

    # Флагов Chromium здесь намеренно нет. Замеры показали, что ни
    # --disable-gpu, ни отключение фонового режима рендереров не
    # помогают (скорее наоборот), а --audio-buffer-size с любым
    # значением от 2048 глушит звук совсем. Работает другое - приоритеты
    # и ядра, этим занимается Repair-KenkuAudio.
    Start-Process -FilePath $exe -ArgumentList "--remote-debugging-port=$Port"

    foreach ($attempt in 1..30) {
        Start-Sleep -Seconds 1
        if (Test-KenkuDebugPort -Port $Port) {
            Repair-KenkuAudio -ErrorAction SilentlyContinue | Out-Null
            return
        }
    }

    throw "Kenku FM player window did not answer on port $Port within 30 seconds"
}
