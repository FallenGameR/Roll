<#
.SYNOPSIS
    Lists every mp3 in the RPG Music library with its Genre and Comment
    id3 tags, one line per track, ready to pipe into fzf.

.DESCRIPTION
    Output format (tab-separated): Title<TAB>Genre<TAB>Comment
      - Title   = filename without the .mp3 extension
      - Genre   = the tag taxonomy string written by the annotation
                  pipeline (e.g. "Background Dread Urban Modern Intro")
      - Comment = situation + description + source URL, flattened to a
                  single line (embedded blank-line breaks replaced with
                  " | ") so each track stays on exactly one line for fzf.

    Reading id3 tags for ~580 files via ffprobe takes a little while, so
    results are cached to a TSV file in the module folder and reused on
    subsequent runs. Use -Refresh to force re-scanning (e.g. after editing
    tags in Mp3tag or re-running the annotation pipeline).

.PARAMETER Root
    Root of the music library to scan. Defaults to the RPG Music library.

.PARAMETER CacheFile
    Where to store/read the cached TSV listing.

.PARAMETER Refresh
    Force re-reading tags from every file instead of using the cache.

.EXAMPLE
    Get-MusicTrackList | fzf --delimiter="`t" --with-nth=1,2,3
.EXAMPLE
    Get-MusicTrackList -Refresh | fzf
#>
function Get-MusicTrackList {
    param(
        [string]$Root = "C:\vaults\Music",
        [string]$CacheFile = "$script:RollRoot\tracks-fzf-cache.tsv",
        [switch]$Refresh
    )

    $ErrorActionPreference = "Stop"

    if (-not $Refresh -and (Test-Path -LiteralPath $CacheFile)) {
        Get-Content -LiteralPath $CacheFile -Encoding utf8
        return
    }

    $ffprobe = Join-Path (Split-Path (Find-WingetTool "Gyan.FFmpeg_*" "ffmpeg.exe")) "ffprobe.exe"

    $files = Get-ChildItem -LiteralPath $Root -Recurse -Filter *.mp3 -File

    $lines = foreach ($f in $files) {
        $genre = & $ffprobe -v error -show_entries format_tags=genre -of default=noprint_wrappers=1:nokey=1 -- $f.FullName
        $commentRaw = & $ffprobe -v error -show_entries format_tags=comment -of default=noprint_wrappers=1:nokey=1 -- $f.FullName
        $comment = ($commentRaw -join "`n").Trim()

        # Flatten to one line: turn blank-line paragraph breaks into " | "
        # so the whole comment (situation / description / source) stays
        # visible on a single fzf row instead of being cut off after the
        # first line.
        $flatComment = ($comment -replace "(`r`n|`r|`n)+", " | ").Trim()

        $title = [System.IO.Path]::GetFileNameWithoutExtension($f.Name)
        "$title`t$genre`t$flatComment"
    }

    $lines | Set-Content -LiteralPath $CacheFile -Encoding utf8
    $lines
}
