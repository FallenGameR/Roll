<#
.SYNOPSIS
    Выгружает плейлисты из файла кампании в .m3u8 для обычного плеера.

.DESCRIPTION
    Фонотека живёт в Winamp: он играет те же файлы без разрывов на
    коротких кусках звука и умеет медиатеку с рейтингами.

    Раздел с музыкой ищется по заголовку любого уровня со словом Music
    или Музыка, сценой считается вложенный заголовок, треком - любая
    ссылка на локальный файл.

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

    if (-not $scenes.Count) {
        Write-Warning "В файле не нашлось раздела музыки: $full"
        return
    }

    if (-not (Test-Path -LiteralPath $Destination)) {
        $null = New-Item -ItemType Directory -Path $Destination -Force
    }

    foreach ($key in $scenes.Keys) {
        if ($Scene -and $key -notin $Scene) { continue }

        # Ситуация и эффект - разовые вещи, и в плеере каждая нужна
        # отдельной строкой: в дереве видно название, а внутри списка
        # из одного трека искать нечего.
        if ($key -eq 'Ситуации' -or $key -eq 'Эффекты') {
            for ($i = 0; $i -lt $scenes[$key].Count; $i++) {
                $label = $labels[$key][$i]
                $kind = if ($key -eq 'Ситуации') { 'Ситуация' } else { 'Эффект' }
                $title = "$name - $kind - $($label.Text)"
                Write-PlaylistFile -Title $title -Tracks @($scenes[$key][$i]) `
                    -Destination $Destination
            }
            continue
        }

        $title = if ($key) { "$name - $key" } else { $name }
        Write-PlaylistFile -Title $title -Tracks $scenes[$key] `
            -Destination $Destination
    }
}
