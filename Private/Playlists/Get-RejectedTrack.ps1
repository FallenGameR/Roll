<#
.SYNOPSIS
    Журнал отказов Мастера: какие треки он выкинул из каких плейлистов.

.DESCRIPTION
    Журнал ведёт sync-from-winamp.py: трек, удалённый из сцены в плеере,
    попадает в Music\Rejected.csv с колонками Date, Playlist, Track.
    Возвращает таблицу «название плейлиста -> множество путей в нижнем
    регистре». Пустая таблица, если журнала ещё нет.
#>
function Get-RejectedTrack {
    param(
        [string] $Path = 'C:\vaults\Music\Rejected.csv'
    )

    $result = @{}
    if (-not (Test-Path -LiteralPath $Path)) { return $result }
    foreach ($row in Import-Csv -LiteralPath $Path -Encoding utf8) {
        if (-not $result.ContainsKey($row.Playlist)) {
            $result[$row.Playlist] = [System.Collections.Generic.HashSet[string]]::new()
        }
        $null = $result[$row.Playlist].Add($row.Track.ToLowerInvariant())
    }
    $result
}
