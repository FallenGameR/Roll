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
    results are cached to a TSV file next to this script and reused on
    subsequent runs. Use -Refresh to force re-scanning (e.g. after editing
    tags in Mp3tag or re-running the annotation pipeline).

.PARAMETER Root
    Root of the music library to scan. Defaults to the RPG Music library.

.PARAMETER CacheFile
    Where to store/read the cached TSV listing.

.PARAMETER Refresh
    Force re-reading tags from every file instead of using the cache.

.EXAMPLE
    .\list-tracks-for-fzf.ps1 | fzf --delimiter="`t" --with-nth=1,2,3

.EXAMPLE
    .\list-tracks-for-fzf.ps1 -Refresh | fzf
#>

param(
    [string]$Root = "C:\vaults\Music",
    [string]$CacheFile = "$PSScriptRoot\tracks-fzf-cache.tsv",
    [switch]$Refresh
)

$ErrorActionPreference = "Stop"

function Find-WingetTool([string]$packageGlob, [string]$exeName) {
    $found = Get-ChildItem "$env:LOCALAPPDATA\Microsoft\WinGet\Packages\$packageGlob" `
        -Recurse -Filter $exeName -ErrorAction SilentlyContinue |
        Select-Object -First 1 -ExpandProperty FullName
    if (-not $found) { throw "Could not find $exeName under WinGet packages matching '$packageGlob'." }
    return $found
}

if (-not $Refresh -and (Test-Path -LiteralPath $CacheFile)) {
    Get-Content -LiteralPath $CacheFile -Encoding utf8
    return
}

$ffprobe = Join-Path (Split-Path (Find-WingetTool "Gyan.FFmpeg_*" "ffmpeg.exe")) "ffprobe.exe"

$files = Get-ChildItem -LiteralPath $Root -Recurse -Filter *.mp3 -File

$lines = foreach ($f in $files) {
    $tags = & $ffprobe -v error -show_entries format_tags=genre,comment -of default=noprint_wrappers=1 -- $f.FullName
    $genre = ($tags | Where-Object { $_ -match '^TAG:genre=' }) -replace '^TAG:genre='
    $commentLines = $tags | Where-Object { $_ -match '^TAG:comment=' -or ($_ -notmatch '^TAG:') }
    $comment = ($commentLines -join "`n") -replace '^TAG:comment='

    # Flatten to one line: turn blank-line paragraph breaks into " | " so
    # the whole comment (situation / description / source) stays visible
    # on a single fzf row instead of being cut off after the first line.
    $flatComment = ($comment -replace "(`r`n|`r|`n)+", " | ").Trim()

    $title = [System.IO.Path]::GetFileNameWithoutExtension($f.Name)
    "$title`t$genre`t$flatComment"
}

$lines | Set-Content -LiteralPath $CacheFile -Encoding utf8
$lines
