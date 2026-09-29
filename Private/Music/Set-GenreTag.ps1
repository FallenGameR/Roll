<#
.SYNOPSIS
    Переписывает тег Genre одного mp3 на месте, не трогая ни звук, ни
    остальные теги.

.DESCRIPTION
    Раньше это делал ffmpeg: пересобирал файл во временную копию и
    подменял оригинал. Работало всюду, кроме единственного места, где
    нужнее всего - на треке, который звучит прямо сейчас. Winamp держит
    открытым то, что играет, и подмена срывалась невнятным "Cannot
    create a file when that file already exists".

    Оказалось, плеер запрещает не запись в файл, а именно его замену:
    открыть mp3 на запись он даёт. Поэтому правка идёт поверх
    существующего ID3-блока, через Tools\write_genre.py. Отсюда же
    следует, что закрывать Winamp перед тегированием больше не нужно.

    Общая точка для Update-MusicGenreTag (массовый перевод формата) и
    Set-Track (точечная простановка).
#>
function Set-GenreTag {
    param(
        [Parameter(Mandatory)]
        [string]$Ffmpeg,

        [Parameter(Mandatory)]
        [System.IO.FileInfo]$File,

        [Parameter(Mandatory)]
        [AllowEmptyString()]
        [string]$Genre
    )

    # $Ffmpeg здесь больше не нужен, но остаётся в сигнатуре: вызывающие
    # команды передают его, и переписывать их ради одного параметра
    # незачем.
    $writer = Join-Path $script:RollRoot 'Tools\write_genre.py'
    if (-not (Test-Path -LiteralPath $writer)) {
        throw "Не найден $writer"
    }

    $output = & python $writer $File.FullName $Genre 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw ("Не удалось записать Genre в '$($File.FullName)': " +
            ($output -join ' '))
    }
}
