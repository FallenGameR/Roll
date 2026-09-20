<#
.SYNOPSIS
    Rewrites just the Genre id3 tag of a single mp3 file in place, without
    touching any other tag or re-encoding the audio.

.DESCRIPTION
    Re-muxes the file into a temp copy via ffmpeg with `-codec copy
    -map_metadata 0 -metadata genre=<value>` (audio untouched, every other
    tag such as Comment/Title preserved, only Genre differs), then swaps
    the temp copy in atomically once ffmpeg confirms success. Shared by
    Update-MusicGenreTag (bulk reformat) and Set-Track (targeted tagging).
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

    $tempFile = Join-Path $File.DirectoryName "$([guid]::NewGuid()).mp3"
    try {
        & $Ffmpeg -y -v error -i $File.FullName -map_metadata 0 -metadata "genre=$Genre" -codec copy -- $tempFile

        if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $tempFile)) {
            throw "ffmpeg failed to rewrite Genre tag for '$($File.FullName)'"
        }

        # Move-Item -Force не перезаписывает файл, который держит другой
        # процесс: Winamp с открытым плейлистом даёт невнятное "Cannot
        # create a file when that file already exists". Говорим об этом
        # прямо, иначе следующий раз снова искать полчаса.
        try {
            Move-Item -LiteralPath $tempFile -Destination $File.FullName `
                -Force -ErrorAction Stop
        }
        catch {
            throw ("Не удалось заменить '$($File.FullName)': файл занят " +
                "другим процессом. Закрой Winamp (он держит треки из " +
                "открытых плейлистов) и повтори. Исходная ошибка: " +
                $_.Exception.Message)
        }
    }
    finally {
        # Временный файл остаётся после любого провала после ffmpeg, а не
        # только при его собственной неудаче.
        if (Test-Path -LiteralPath $tempFile) {
            Remove-Item -LiteralPath $tempFile -Force -ErrorAction SilentlyContinue
        }
    }
}
