<#
.SYNOPSIS
    Выгружает плейлисты из файла кампании в .m3u8 для обычного плеера.

.DESCRIPTION
    Фонотека живёт в Winamp: он играет те же файлы без разрывов на
    коротких кусках звука и умеет медиатеку с рейтингами.

    Раздел с музыкой ищется по заголовку любого уровня со словом Music
    или Музыка, сценой считается вложенный заголовок, треком - любая
    ссылка на локальный файл.

    Темы NPC берутся из свойства `music` карточек в Adventure\NPC, чей
    `location` ведёт на эту страницу: каждая едет отдельным списком
    `<Локация> - НПС - <Имя>`.

    Треки, которые Мастер уже выкидывал из этого же списка в плеере (журнал
    Music\Rejected.csv ведёт Sync-WinampPlaylist), выгружаются с
    предупреждением.

.PARAMETER Path
    Файл кампании с разделом музыки.

.PARAMETER Scene
    Выгрузить только эти сцены. По умолчанию все.

.PARAMETER Destination
    Куда складывать списки. По умолчанию C:\vaults\Music\_playlists.

.EXAMPLE
    Export-Playlist '...\Locations\Логово Скальной Пасти.md'

.EXAMPLE
    Export-Playlist '...\Погоня.md' -Scene 'Фон' | Invoke-Item
#>
function Export-Playlist {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory, Position = 0)]
        [string] $Path,

        [string[]] $Scene,

        [string] $Destination = 'C:\vaults\Music\_playlists',

        [string] $Section = 'Music|Музыка'
    )

    $ErrorActionPreference = 'Stop'
    $full = (Resolve-Path -LiteralPath $Path).Path

    # Отыгранная локация лежит в Done, и её музыка в плеере уже не нужна.
    if ($full -match '\\Done\\') {
        Write-Warning "Страница в Done, в плеер не выгружается: $full"
        return
    }

    $lines = [System.IO.File]::ReadAllLines($full)

    # Имя в дереве плеера: свойство `fn` из шапки, иначе имя файла.
    $name = Get-PlaylistBaseName -Path $full

    $inSection = $false
    $sectionLevel = 0
    $current = ''
    $scenes = [ordered] @{}
    $labels = [ordered] @{}

    foreach ($line in $lines) {
        if ($line -match '^(#{1,6})\s+(.*)$') {
            $level = $Matches[1].Length
            $title = $Matches[2].Trim()

            if ($inSection -and $level -le $sectionLevel) {
                $inSection = $false          # раздел музыки закончился
            }
            elseif ($inSection) {
                $current = $title            # вложенный заголовок - сцена
                continue
            }

            if ($title -match "^($Section)$") {
                $inSection = $true
                $sectionLevel = $level
                $current = ''
            }
            continue
        }

        if (-not $inSection) { continue }

        foreach ($match in [regex]::Matches($line, '\(file:///([^)]+)\)')) {
            $file = [uri]::UnescapeDataString($match.Groups[1].Value) `
                -replace '/', '\'
            if (-not $scenes.Contains($current)) {
                $scenes[$current] = [System.Collections.ArrayList]::new()
                $labels[$current] = [System.Collections.ArrayList]::new()
            }
            $null = $scenes[$current].Add($file)
            $null = $labels[$current].Add((Get-SituationLabel -Line $line))
        }
    }

    # Темы NPC живут в шапках их карточек (`music`), а не в разделе
    # локации. В плеер они едут вместе с локацией, куда указывает
    # `location` карточки, отдельным списком на персонажа.
    $npcs = [ordered] @{}
    $root = Split-Path $full -Parent
    while ($root -and -not (Test-Path -LiteralPath (Join-Path $root 'Adventure\NPC'))) {
        $root = Split-Path $root -Parent
    }
    if ($root) {
        $page = [System.IO.Path]::GetFileNameWithoutExtension($full)
        foreach ($card in Get-ChildItem -LiteralPath (Join-Path $root 'Adventure\NPC') -Filter '*.md') {
            $front = Get-FrontMatterValue -Path $card.FullName -Key 'location', 'music'
            $here = $front['location'] | Where-Object {
                $_ -match '\[\[([^\]|#]+)' -and $Matches[1].Trim() -eq $page
            }
            if (-not $here) { continue }
            $tracks = foreach ($value in $front['music']) {
                foreach ($match in [regex]::Matches($value, '\(file:///([^)]+)\)')) {
                    [uri]::UnescapeDataString($match.Groups[1].Value) -replace '/', '\'
                }
            }
            if ($tracks) {
                # Имя до запятой: "Незнар, Чёрный Паук" в дереве плеера длинно.
                $npcs[($card.BaseName -split ',')[0].Trim()] = @($tracks)
            }
        }
    }

    if (-not $scenes.Count -and -not $npcs.Count) {
        Write-Warning "В файле не нашлось раздела музыки: $full"
        return
    }

    if (-not (Test-Path -LiteralPath $Destination)) {
        $null = New-Item -ItemType Directory -Path $Destination -Force
    }

    # Что Мастер уже выкидывал из сцен: такие треки выгружаются с
    # предупреждением, чтобы не вернуть их туда незаметно.
    $rejected = Get-RejectedTrack

    foreach ($key in $scenes.Keys) {
        if ($Scene -and $key -notin $Scene) { continue }

        # Ситуация и эффект - разовые вещи, и в плеере каждая нужна
        # отдельной строкой: в дереве видно название, а внутри списка
        # из одного трека искать нечего.
        if ($key -eq 'Ситуации' -or $key -eq 'Эффекты') {
            for ($i = 0; $i -lt $scenes[$key].Count; $i++) {
                $label = $labels[$key][$i]
                $kind = if ($key -eq 'Ситуации') { 'Ситуация' }
                        elseif ($label.Background) { 'Фон' }
                        else { 'Эффект' }
                $title = "$name - $kind - $($label.Text)"
                Write-PlaylistFile -Title $title -Tracks @($scenes[$key][$i]) `
                    -Destination $Destination -Rejected $rejected
            }
            continue
        }

        $title = if ($key) { "$name - $key" } else { $name }
        Write-PlaylistFile -Title $title -Tracks $scenes[$key] `
            -Destination $Destination -Rejected $rejected
    }

    if (-not $Scene -or 'НПС' -in $Scene) {
        foreach ($npc in $npcs.Keys) {
            Write-PlaylistFile -Title "$name - НПС - $npc" -Tracks $npcs[$npc] `
                -Destination $Destination -Rejected $rejected
        }
    }
}
