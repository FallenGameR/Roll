<#
    Помощники Export-Playlist: короткая метка ситуации и запись файла.

    В плеере ситуация становится отдельным плейлистом из одного трека,
    поэтому её название должно быть коротким: в дереве Winamp видно
    около сорока символов, а туда ещё уместить имя локации.
#>

<#
.SYNOPSIS
    Короткая метка для названия плейлиста ситуации или эффекта.

.DESCRIPTION
    Возвращает объект с полями Text и Loop. Для ситуации берёт явный
    ярлык в начале строки (`- *Банши.* [Трек](...)`), иначе строит
    метку из ссылки на комнату. Для эффекта берёт название трека без
    служебного префикса `Effect - `, а пометка `- цикл` в строке
    означает петлю, `- фон` - нейтральный фон локации.
#>
function Get-SituationLabel {
    param([string] $Line)

    $loop = $Line -match '[-—]\s*(цикл|фон)\s*$'
    $background = $Line -match '[-—]\s*фон\s*$'

    # Эффект узнаётся по названию файла: в подписи стоит «Effect - X».
    if ($Line -match '\[\s*Effect\s*-\s*([^\]]+?)\s*\]') {
        # Хвост в скобках - это автор, на кнопке он только мешает.
        $text = ($Matches[1] -replace '\s*\([^)]*\)\s*$', '').Trim()
        return [pscustomobject] @{ Text = $text; Loop = $loop; Background = $background }
    }

    # Номер комнаты полезен всегда: по нему Мастер находит место на
    # карте, поэтому подставляем его и к явному ярлыку.
    $number = ''
    if ($Line -match '\[\[#?\s*([\d]+(?:[–\-][\d]+)?)\.') { $number = $Matches[1] }

    # Явный ярлык: курсив сразу после маркера списка.
    if ($Line -match '^\s*[-*]\s+\*([^*]+?)\.?\*\s') {
        $label = $Matches[1].Trim()
        if ($number) { $label = "$number $label" }
        return [pscustomobject] @{ Text = $label; Loop = $loop }
    }

    $anchor = ''
    if ($Line -match '\[\[#?([^\]|]+)') { $anchor = $Matches[1].Trim() }
    if (-not $anchor) {
        # Ссылки нет - берём хвост строки после тире.
        if ($Line -match '—\s*(.+)$') { $anchor = $Matches[1].Trim() }
    }
    if (-not $anchor) {
        return [pscustomobject] @{ Text = 'без имени'; Loop = $loop }
    }

    # Ссылка на другую страницу: «Сокол#Как его играть».
    if ($anchor -match '#') { $anchor = ($anchor -split '#')[-1] }

    if ($anchor -match '^\s*([\d–\-]+)\.\s*(.+)$') {
        $anchor = $Matches[2]
    }

    $anchor = $anchor -replace '^(Улика|Развилка|Дилемма|Чем кончается)[:,]?\s*', ''
    $words = @($anchor -split '[\s,]+' | Where-Object { $_ })

    $skip = 'зал', 'зале', 'пещера', 'пещере', 'комната', 'покои', 'с', 'и',
            'в', 'на', 'для', 'что', 'к', 'из', 'по', 'который', 'которой'
    $meaningful = @($words | Where-Object { $_.ToLower() -notin $skip })
    if (-not $meaningful) { $meaningful = $words }

    $short = ($meaningful | Select-Object -First 2) -join ' '
    if ($number) { $short = "$number $short" }
    return [pscustomobject] @{ Text = $short; Loop = $loop }
}

<#
.SYNOPSIS
    Пишет один .m3u8 и возвращает строку отчёта.
#>
function Write-PlaylistFile {
    param(
        [string] $Title,
        [string[]] $Tracks,
        [string] $Destination
    )

    $safe = $Title -replace '[\\/:*?"<>|]', '-'
    $target = Join-Path $Destination "$safe.m3u8"

    $content = [System.Collections.ArrayList]::new()
    $null = $content.Add('#EXTM3U')
    $missing = 0
    foreach ($track in $Tracks) {
        if (-not (Test-Path -LiteralPath $track)) { $missing++ }
        $null = $content.Add($track)
    }

    # m3u8 обязан быть в UTF-8; BOM Winamp читает нормально, а без него
    # кириллица в путях ломается.
    [System.IO.File]::WriteAllLines($target, $content,
        (New-Object Text.UTF8Encoding $true))

    [pscustomobject] @{
        Плейлист = $Title
        Треков   = $Tracks.Count
        Потеряно = $missing
        Файл     = $target
    }
}
