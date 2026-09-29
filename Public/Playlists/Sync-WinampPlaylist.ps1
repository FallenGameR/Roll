<#
.SYNOPSIS
    Переносит правки из медиатеки Winamp обратно в файлы кампании.

.DESCRIPTION
    После выгрузки источником правды становится плеер: Мастер удаляет
    там лишние треки и расставляет звёзды прямо во время игры. Команда
    возвращает эти правки в markdown, иначе следующая выгрузка их
    затрёт.

    Что переносится:

    * трек удалён из плейлиста - строка убирается из сцены;
    * плейлист удалён целиком - убирается вся сцена;
    * одна звезда - mp3 уезжает в Music\Excluded, ссылки исчезают;
    * пять звёзд - если трек лежал в Music\Unsorted, он переезжает в
      обычную папку франшизы, звёздочка в markdown снимается.

    Звёзды читаются из тега POPM самого mp3, поэтому в Winamp должна
    быть включена запись рейтингов в файлы. Без этого они остаются во
    внутренней базе плеера и команде не видны.

.PARAMETER Apply
    Записать изменения. Без ключа команда только показывает, что
    сделала бы.

.PARAMETER KeepPlayer
    Не закрывать Winamp. Тогда звёзды текущего сеанса прочитаны не
    будут: плеер держит их в памяти и сбрасывает базу на диск только
    при выходе — проверено экспериментом, за сто секунд работы файл
    базы не менялся.

.EXAMPLE
    Sync-WinampPlaylist

.EXAMPLE
    Sync-WinampPlaylist -Apply
#>
function Sync-WinampPlaylist {
    [CmdletBinding(SupportsShouldProcess)]
    param(
        [switch] $Apply,
        [switch] $KeepPlayer
    )

    $script = Join-Path $script:RollRoot 'Tools\Winamp\sync-from-winamp.py'
    if (-not (Test-Path -LiteralPath $script)) {
        throw "Не найден $script"
    }

    if ($Apply -and -not $PSCmdlet.ShouldProcess('файлы кампании',
            'применить правки из Winamp')) {
        return
    }

    $winampPath = $null
    if (-not $KeepPlayer) {
        $winampPath = Stop-WinampGracefully
    }

    $arguments = @($script)
    if ($Apply) { $arguments += '--apply' }

    $previous = $env:PYTHONIOENCODING
    try {
        $env:PYTHONIOENCODING = 'utf-8'
        Invoke-WithUtf8Console { & python @arguments }
    }
    finally {
        $env:PYTHONIOENCODING = $previous
        if ($winampPath) { Start-Process -FilePath $winampPath }
    }
}
