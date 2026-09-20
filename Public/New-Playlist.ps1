<#
.SYNOPSIS
    Publishes the "Music" section of a campaign markdown file to Kenku
    FM: continuous scenes become playlists, point sounds become
    soundboards.

.DESCRIPTION
    Kenku FM has no import feature and its Remote API only does playback
    (play/pause/next/volume) - it can't create playlists. Both playlists
    and soundboards live in the player window's LocalStorage under the
    redux-persist key "persist:player", inside a Chromium LevelDB store.

    Rather than hand-craft LevelDB write batches (binary format, CRC32C
    with masking, and the app would overwrite them from its in-memory
    redux state on exit anyway), New-Playlist drives the app itself: it
    starts Kenku FM with --remote-debugging-port, attaches over the
    Chrome DevTools Protocol, and calls the ordinary
    localStorage.setItem the app would have called, then reloads the
    player window so redux-persist rehydrates from the new value. That
    keeps the write on a supported code path and survives app exit.

    Source of truth is the markdown itself: every "- [Title](file:///...)"
    bullet under a sub-heading of "# Music"/"## Music" becomes a track,
    and each sub-heading becomes a card named "<Prefix> - <Scene>".
    Because the campaign links are already percent-encoded (including the
    %28/%29 parentheses), they are used verbatim as Kenku URLs.

    By default the scenes are split the way they are used at the table:
    'Фон' and 'Бой' become playlists that run on their own, while
    'Ситуации' and 'Эффекты' become soundboards the DM triggers by hand
    over whatever music is playing. Every card gets the location
    illustration as its background, so one location reads as one group.

    Re-running is safe: a card whose title already exists is updated in
    place instead of duplicated, and tracks are matched by URL so the
    same file is never added twice. That means the normal workflow is to
    edit the markdown and just run New-Playlist again.

.PARAMETER Path
    Campaign markdown file holding the Music section.

.PARAMETER Scene
    Scene sub-headings to publish as playlists, e.g. 'Фон', 'Бой'.
    Defaults to those two. Use -ListScene to see what's available.

.PARAMETER Soundboard
    Scene names to publish as Kenku soundboards instead of playlists.
    Defaults to 'Ситуации' and 'Эффекты': those are point sounds the DM
    triggers by hand, and a soundboard plays them over the music instead
    of replacing it. Lines marked "— цикл" become looping sounds.

.PARAMETER Remove
    Scene names whose playlists should be deleted from Kenku instead of
    published, e.g. -Remove 'Эффекты'. Tracks are left alone: they are
    shared between playlists.

.PARAMETER RemoveTitle
    Full card titles to delete, for cases the scene name can't describe:
    typically the markdown file was renamed and the old card is still
    there under its previous name.

.PARAMETER Background
    Kenku playlist artwork: either one of the 23 bundled names (autumn,
    beach, butterflys, castle, cathedral, dragon, haunted, lines,
    mountain, sand, skulls, sky, smoke, sparks, stars, tavern, texture,
    town, tree, veins, volcano, war, winter) or a path to an image file.
    Defaults to the location illustration in `_img\locations`, found by
    the English alias in the page frontmatter. Kenku renders any
    background string it doesn't recognise as an image URL, which is
    what makes a custom picture possible.

.PARAMETER Prefix
    Playlist title prefix. Defaults to the markdown file's base name, so
    "Логово Скальной Пасти.md" yields "Логово Скальной Пасти - Фон".

.PARAMETER Section
    Regex matching the heading that holds the music, at any heading level.
    Defaults to "Music" or "Музыка". If no such heading matches, every
    local-file link in the document is used instead, grouped by whatever
    heading precedes it - so a restructured file still yields playlists.

.PARAMETER Font
    CSS font-family for playlist card titles, e.g. 'Georgia, serif'. The
    value is stored inside the patch, so later runs keep it - pass it
    once to change the look, not on every call.

.PARAMETER ListScene
    Only list the scenes and their track counts; writes nothing.

.PARAMETER Port
    Debugging port to talk to Kenku FM on. Default 9222.

.EXAMPLE
    New-Playlist '...\Локации\Логово Скальной Пасти.md' -ListScene
    Shows the scenes in the file without touching Kenku FM.
.EXAMPLE
    New-Playlist '...\Локации\Логово Скальной Пасти.md'
    Publishes the whole location: Фон and Бой as playlists, Ситуации and
    Эффекты as soundboards, all four carrying the location illustration.
.EXAMPLE
    New-Playlist '...\Локации\Замок Скальной Пасти.md' -Remove 'Атмосфера' `
        -Soundboard 'Эффекты'
    Moves a scene from a playlist to a soundboard: the removal and the
    publish must share one call.
#>
function New-Playlist {
    [CmdletBinding(SupportsShouldProcess)]
    param(
        [Parameter(Mandatory, Position = 0)]
        [string]$Path,

        [string[]]$Scene,

        [string[]]$Soundboard,

        [string[]]$Remove,

        [string[]]$RemoveTitle,

        [string]$Background,

        [string]$Prefix,

        [string]$Section,

        [string]$Font,

        [switch]$ListScene,

        # Не трогать оформление карточек. Пригодится, если понадобится
        # сравнить поведение плеера с патчем и без него.
        [switch]$NoCardStyle,

        [int]$Port = 9222
    )

    $ErrorActionPreference = 'Stop'

    if (-not (Test-Path -LiteralPath $Path)) {
        throw "Markdown file not found: $Path"
    }

    $script = Join-Path $script:RollRoot 'Private\new-kenku-playlist.py'
    $python = (Get-Command python -ErrorAction SilentlyContinue).Source
    if (-not $python) { throw "python not found in PATH" }

    # The CDP client needs websocket-client; install it once on demand.
    & $python -c "import websocket" 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Verbose "Installing websocket-client"
        & $python -m pip install --quiet websocket-client | Out-Null
    }

    $arguments = @($script, $Path)
    if ($Section) { $arguments += @('--section', $Section) }
    if ($ListScene) {
        $arguments += '--list'
    }
    else {
        # Конвенция раздела Music: непрерывные сцены — плейлисты, точечные
        # — соундборды. Заданное явно всегда важнее конвенции.
        if (-not $Scene -and -not $Soundboard -and -not $Remove) {
            $available = (New-Playlist -Path $Path -Section $Section -ListScene).Scene
            $Scene = @('Фон', 'Бой') | Where-Object { $available -contains $_ }
            $Soundboard = @('Ситуации', 'Эффекты') | Where-Object { $available -contains $_ }
        }

        # Фон по умолчанию — иллюстрация локации: у всех её карточек один
        # и тот же вид, поэтому они читаются как одна группа. Папку с
        # картинками ищем вверх от файла, а не отсчитываем уровни: так
        # перестройка дерева страниц ничего не ломает.
        if (-not $Background) {
            $alias = Get-LocationAlias -Path $Path
            $folder = Split-Path -Parent (Resolve-Path -LiteralPath $Path)
            while ($alias -and $folder) {
                $picture = Join-Path $folder "_img\locations\$alias.jpg"
                if (Test-Path -LiteralPath $picture) { $Background = $picture; break }
                $folder = Split-Path -Parent $folder
            }
        }

        # Патч стиля переживает перезапуск приложения, но слетает при его
        # обновлении, поэтому применяется каждый раз; перезагрузка окна в
        # конце записи подхватит его без рестарта Kenku.
        if ($NoCardStyle) {
            Set-KenkuTitleStyle -Disable
            # Патч живёт в HTML окна, а окно уже загружено со старой
            # версией: без перезагрузки снятие ничего не изменит, и
            # сравнение «с оформлением и без» окажется бессмысленным.
            $arguments += '--reload'
        }
        else {
            Set-KenkuTitleStyle -Font $Font
        }

        if (-not (Test-KenkuDebugPort -Port $Port)) {
            if (-not $PSCmdlet.ShouldProcess("Kenku FM",
                    "restart with --remote-debugging-port=$Port")) {
                return
            }
            Start-KenkuDebugSession -Port $Port
        }

        if ($Background) {
            # Своя картинка задаётся путём к файлу: Kenku показывает
            # любую строку, не совпадающую с именем встроенного фона,
            # прямо как URL картинки.
            $value = $Background
            if (Test-Path -LiteralPath $Background) {
                $full = (Resolve-Path -LiteralPath $Background).Path
                $value = 'file:///' + ($full -replace '\\', '/' -replace ' ', '%20')
            }
            $arguments += @('--background', $value)
        }
        foreach ($s in $Scene) { $arguments += @('--scene', $s) }
        foreach ($b in $Soundboard) { $arguments += @('--soundboard', $b) }
        foreach ($r in $Remove) { $arguments += @('--remove', $r) }
        foreach ($r in $RemoveTitle) { $arguments += @('--remove-title', $r) }
        if ($Prefix) { $arguments += @('--prefix', $Prefix) }
    }

    $previous = [Console]::OutputEncoding
    try {
        [Console]::OutputEncoding = [Text.Encoding]::UTF8
        $output = & $python @arguments
        if ($LASTEXITCODE -ne 0) { throw ($output -join [Environment]::NewLine) }
    }
    finally {
        [Console]::OutputEncoding = $previous
    }

    if (-not $ListScene) {
        # Windows возвращает процессу энергосбережение при смене
        # видимости окон, а публикация как раз перерисовывает интерфейс.
        Repair-KenkuAudio -ErrorAction SilentlyContinue | Out-Null
    }

    if ($ListScene) {
        foreach ($line in $output) {
            $parts = $line -split ':\s*', 2
            [PSCustomObject]@{ Scene = $parts[0]; Tracks = [int]$parts[1] }
        }
    }
    else {
        ($output -join '') | ConvertFrom-Json | ForEach-Object {
            [PSCustomObject]@{
                # В самом плейлисте локация и сцена разделены переводом
                # строки; в консоли он превратил бы таблицу в кашу.
                Title   = ($_.title -replace '\s*\r?\n\s*', ' - ')
                Tracks  = $_.tracks
                Updated = $_.replaced
            }
        }
    }
}
