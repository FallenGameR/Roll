<#
.SYNOPSIS
    Регистрирует плейлисты кампании в медиатеке Winamp.

.DESCRIPTION
    Export-Playlist кладёт .m3u8 в C:\vaults\Music\_playlists, но в
    разделе Playlists медиатеки они сами не появляются: Winamp держит
    свой каталог в Plugins\ml\playlists (файлы + индекс playlists.xml).
    Команда копирует туда списки и правит индекс.

    Winamp перезаписывает индекс при выходе, поэтому правку делаем при
    закрытом плеере: если он запущен, команда его закрывает и по
    окончании запускает обратно (отключается ключом -NoRestart).

    Повторный запуск обновляет уже добавленные списки по названию, а не
    плодит дубли.

.PARAMETER Path
    Файлы .m3u8. По умолчанию всё из C:\vaults\Music\_playlists.

.PARAMETER NoRestart
    Не запускать Winamp обратно после правки.

.PARAMETER Prune
    Убрать из каталога записи, которых нет среди импортируемых. Нужен
    после переименования сцен: иначе прежние названия остаются висеть.

.EXAMPLE
    Import-WinampPlaylist -Prune

.EXAMPLE
    Export-Playlist '...\Аксхольм.md' | ForEach-Object { $_.Файл } |
        Import-WinampPlaylist
#>
function Import-WinampPlaylist {
    [CmdletBinding(SupportsShouldProcess)]
    param(
        [Parameter(ValueFromPipeline)]
        [string[]] $Path,

        [string] $Source = 'C:\vaults\Music\_playlists',

        [switch] $NoRestart,

        [switch] $Prune
    )

    begin {
        $ErrorActionPreference = 'Stop'
        $collected = [System.Collections.ArrayList]::new()
    }

    process {
        foreach ($item in $Path) { $null = $collected.Add($item) }
    }

    end {
        if (-not $collected.Count) {
            $collected = @(Get-ChildItem -LiteralPath $Source -Filter '*.m3u8' |
                Select-Object -ExpandProperty FullName)
        }
        if (-not $collected.Count) {
            Write-Warning "Нет файлов .m3u8 в $Source"
            return
        }

        $store = Join-Path $env:APPDATA 'Winamp\Plugins\ml\playlists'
        if (-not (Test-Path -LiteralPath $store)) {
            $null = New-Item -ItemType Directory -Path $store -Force
        }
        $index = Join-Path $store 'playlists.xml'

        $winampPath = $null
        if (Get-Process -Name 'winamp' -ErrorAction SilentlyContinue) {
            if (-not $PSCmdlet.ShouldProcess('Winamp',
                    'закрыть на время правки каталога')) {
                return
            }
            # Именно закрыть, а не убить: при жёстком завершении
            # пропадают рейтинги, расставленные за этот сеанс.
            $winampPath = Stop-WinampGracefully
        }

        $durations = Get-TrackDurationCache
        $entries = [ordered] @{}
        $incoming = [System.Collections.Generic.HashSet[string]]::new()
        foreach ($file in $collected) {
            $null = $incoming.Add(
                [System.IO.Path]::GetFileNameWithoutExtension($file))
        }

        # Уже зарегистрированные списки читаем, чтобы обновлять их, а не
        # плодить дубли с тем же названием.
        if (Test-Path -LiteralPath $index) {
            [xml] $existing = Get-Content -LiteralPath $index -Raw
            foreach ($node in $existing.playlists.playlist) {
                if ($Prune -and -not $incoming.Contains($node.title)) {
                    Remove-Item -LiteralPath (Join-Path $store $node.filename) `
                        -ErrorAction SilentlyContinue
                    continue
                }
                $entries[$node.title] = @{
                    filename = $node.filename
                    id       = $node.id
                    songs    = $node.songs
                    seconds  = $node.seconds
                }
            }
        }

        $result = foreach ($file in $collected) {
            $title = [System.IO.Path]::GetFileNameWithoutExtension($file)
            $tracks = @(Get-Content -LiteralPath $file |
                Where-Object { $_ -and -not $_.StartsWith('#') })

            $seconds = 0
            foreach ($track in $tracks) {
                $seconds += Get-TrackDuration -Path $track -Cache $durations
            }

            $known = $entries[$title]
            $name = if ($known) { $known.filename }
                    else { 'roll{0:x}.m3u8' -f (Get-Random -Maximum 0xFFFFFF) }
            $id = if ($known) { $known.id }
                  else { '{' + [guid]::NewGuid().ToString().ToUpper() + '}' }

            Copy-Item -LiteralPath $file -Destination (Join-Path $store $name) -Force

            $entries[$title] = @{
                filename = $name
                id       = $id
                songs    = $tracks.Count
                seconds  = [int] $seconds
            }

            [pscustomobject] @{
                Плейлист   = $title
                Треков     = $tracks.Count
                Длительность = [timespan]::FromSeconds([int]$seconds).ToString('hh\:mm\:ss')
                Обновлён   = [bool] $known
            }
        }

        Save-TrackDurationCache -Cache $durations

        $xml = [System.Text.StringBuilder]::new()
        $null = $xml.AppendLine('<?xml version="1.0" encoding="UTF-8" ?>')
        $null = $xml.AppendLine("<playlists playlists=""$($entries.Count)"">")
        foreach ($title in $entries.Keys) {
            $e = $entries[$title]
            $safe = [System.Security.SecurityElement]::Escape($title)
            $null = $xml.AppendLine(
                "  <playlist filename=""$($e.filename)"" title=""$safe"" " +
                "id=""$($e.id)"" songs=""$($e.songs)"" seconds=""$($e.seconds)"" />")
        }
        $null = $xml.AppendLine('</playlists>')

        [System.IO.File]::WriteAllText($index, $xml.ToString(),
            (New-Object Text.UTF8Encoding $false))

        if ($winampPath -and -not $NoRestart) {
            Start-Process -FilePath $winampPath
        }

        $result
    }
}
