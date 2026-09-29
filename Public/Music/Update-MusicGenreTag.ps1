<#
.SYNOPSIS
    Rewrites the Genre id3 tag of every mp3 under Path from the legacy
    free-form format into the canonical self-describing
    "Category:value1,value2" format (see Private/Music/ConvertTo-GenreCategory.ps1),
    without changing any other tag or re-encoding the audio.

.DESCRIPTION
    For each file, the current Genre tag is parsed via
    ConvertTo-GenreCategory (same logic Get-Track uses) and re-serialized
    via ConvertTo-GenreTagString into the canonical, order-independent
    form, e.g.:
      "Background Dread/Secrets Anomaly Modern/SciFi"
      -> "Intensity:Background Emotion:Dread,Secrets Scene:Anomaly Game:Modern,SciFi"

    Files whose Genre already round-trips to the same string (already
    migrated, or has no Genre tag) are skipped.

    By default this is a dry run: it only reports what would change. Pass
    -Apply to actually rewrite the files. The rewrite uses ffmpeg with
    `-codec copy -map_metadata 0` so audio is untouched and all other
    tags (Comment, Title, ...) are preserved; only the Genre tag differs.
    Each file is written to a temp copy first and only replaces the
    original once ffmpeg succeeds.

.PARAMETER Path
    Folder to scan for mp3s. Defaults to the RPG Music library root.
    Pass "." to scan the current working directory instead (handy for a
    quick, safe test run from a small subfolder before running against
    the whole library).

.PARAMETER Apply
    Actually rewrite the Genre tag in place. Without this switch, the
    function only reports Name/Old/New for tracks that would change.

.EXAMPLE
    Update-MusicGenreTag .
    Dry run against the current folder: shows what would change.
.EXAMPLE
    Update-MusicGenreTag . -Apply
    Actually rewrites the Genre tag for every mp3 in the current folder.
.EXAMPLE
    Update-MusicGenreTag -Apply
    Migrates the whole RPG Music library in place.
#>
function Update-MusicGenreTag {
    param(
        [string]$Path = "C:\vaults\Music",
        [switch]$Apply
    )

    $ErrorActionPreference = "Stop"

    if ($Path -eq '.') {
        $Path = (Get-Location).Path
    }

    $ffmpegDir = Split-Path (Find-WingetTool "Gyan.FFmpeg_*" "ffmpeg.exe")
    $ffmpeg = Join-Path $ffmpegDir "ffmpeg.exe"
    $ffprobe = Join-Path $ffmpegDir "ffprobe.exe"

    $files = Get-ChildItem -LiteralPath $Path -Recurse -Filter *.mp3 -File

    foreach ($f in $files) {
        $json = & $ffprobe -v error -show_entries format_tags=genre -of json -- $f.FullName
        $genre = ($json -join "`n" | ConvertFrom-Json).format.tags.genre

        if (-not $genre) {
            continue
        }

        $category = ConvertTo-GenreCategory -Genre $genre
        $newGenre = ConvertTo-GenreTagString -Category $category

        if ($newGenre -eq $genre) {
            continue
        }

        [PSCustomObject]@{
            Name = [System.IO.Path]::GetFileNameWithoutExtension($f.Name)
            Old  = $genre
            New  = $newGenre
        }

        if (-not $Apply) {
            continue
        }

        try {
            Set-GenreTag -Ffmpeg $ffmpeg -File $f -Genre $newGenre
        }
        catch {
            Write-Error $_
        }
    }
}
