<#
.SYNOPSIS
    Reorganizes the RPG Music library into flat folders named after each
    track's "album" id3 tag (already cleaned up by the user), for use as
    Kenku FM playlists.

.DESCRIPTION
    Every mp3 in the library already has an "album" tag identifying which
    soundtrack/mix/game it came from. This script:
      1. Reads the album tag of every mp3 (recursively).
      2. Normalizes a handful of known duplicate/typo album names to one
         canonical spelling (see $albumAliases below).
      3. Moves each file into "<Root>\<sanitized album name>\<filename>",
         flattening the current folder structure (numbered playlist
         folders, per-mix chapter-split subfolders, etc. all disappear -
         only album folders remain directly under Root).
      4. Sanitizes album names for use as Windows folder names using the
         same fullwidth-character substitutions yt-dlp already used
         elsewhere in this library (so folder naming stays consistent).
      5. Resolves filename collisions within a target album folder by
         appending " (n)" before the extension.
      6. Removes any now-empty folders left behind under Root.

    This script only reads the "album" tag - it does not modify any
    audio/tags. Run resize-thumbnails.ps1 separately if needed.

.PARAMETER Root
    Root of the music library. Defaults to the RPG Music library.

.PARAMETER WhatIf
    If set, only prints planned moves without touching any files.
#>

param(
    [string]$Root = "C:\Users\alexk\OneDrive\Projects\RPG\Music",
    [switch]$WhatIf
)

$ErrorActionPreference = "Stop"

function Find-WingetTool([string]$packageGlob, [string]$exeName) {
    $found = Get-ChildItem "$env:LOCALAPPDATA\Microsoft\WinGet\Packages\$packageGlob" `
        -Recurse -Filter $exeName -ErrorAction SilentlyContinue |
        Select-Object -First 1 -ExpandProperty FullName
    if (-not $found) { throw "Could not find $exeName under WinGet packages matching '$packageGlob'." }
    return $found
}
$ffprobe = Join-Path (Split-Path (Find-WingetTool "Gyan.FFmpeg_*" "ffmpeg.exe")) "ffprobe.exe"

# Known duplicate / typo / language-variant album names -> canonical name.
# Only exact known collisions go here; ambiguous cases (e.g. different
# games in the same series) are intentionally left alone.
$albumAliases = @{
    "Order, The"        = "The Order"
    "Castelvania"        = "Castlevania"
    "Medal Of Honor"     = "Medal of Honor"
    "Lord of the Rings"  = "The Lord of the Rings"
    "Шерлок Холмс"       = "Sherlock Holmes"
    "Dune "              = "Dune"
}

# Windows-forbidden filename characters, replaced with the same fullwidth
# lookalikes yt-dlp already uses elsewhere in this library, so folder
# naming stays visually consistent with existing mix subfolders.
function Get-SafeName([string]$name) {
    $name = $name.Trim()
    $map = @{
        '\' = '⧹'; '/' = '⧸'; ':' = '：'; '*' = '＊'
        '?' = '？'; '"' = '＂'; '<' = '＜'; '>' = '＞'; '|' = '｜'
    }
    foreach ($k in $map.Keys) { $name = $name.Replace($k, $map[$k]) }
    return $name
}

$files = Get-ChildItem -LiteralPath $Root -Recurse -Filter *.mp3 -File
Write-Host "Found $($files.Count) mp3 files."

$moved = 0
$alreadyThere = 0
$errors = 0
$i = 0

foreach ($f in $files) {
    $i++
    if ($i % 50 -eq 0) { Write-Host "... $i / $($files.Count)" }

    try {
        $album = (& $ffprobe -v error -show_entries format_tags=album -of default=noprint_wrappers=1:nokey=1 -- $f.FullName).Trim()
        if ([string]::IsNullOrWhiteSpace($album)) {
            Write-Host "SKIP (no album tag): $($f.FullName)"
            continue
        }
        if ($albumAliases.ContainsKey($album)) { $album = $albumAliases[$album] }

        $safeAlbum = Get-SafeName $album
        $targetDir = Join-Path $Root $safeAlbum
        $targetPath = Join-Path $targetDir $f.Name

        # Already correctly placed (file directly under Root\<album>\).
        if ($f.DirectoryName -eq $targetDir) { $alreadyThere++; continue }

        if ($WhatIf) {
            Write-Host "WOULD MOVE: $($f.FullName) -> $targetPath"
            continue
        }

        if (-not (Test-Path -LiteralPath $targetDir)) {
            New-Item -ItemType Directory -Path $targetDir -Force | Out-Null
        }

        # Resolve filename collisions inside the target album folder.
        if (Test-Path -LiteralPath $targetPath) {
            $base = [System.IO.Path]::GetFileNameWithoutExtension($f.Name)
            $ext = $f.Extension
            $n = 2
            do {
                $targetPath = Join-Path $targetDir "$base ($n)$ext"
                $n++
            } while (Test-Path -LiteralPath $targetPath)
        }

        Move-Item -LiteralPath $f.FullName -Destination $targetPath
        $moved++
    }
    catch {
        Write-Host "ERROR on $($f.FullName): $_"
        $errors++
    }
}

Write-Host ""
Write-Host "Moved: $moved | Already in place: $alreadyThere | Errors: $errors"

if (-not $WhatIf) {
    # Clean up now-empty leftover folders (old numbered playlist folders,
    # chapter-split subfolders, etc.)
    $removedDirs = 0
    $sortedDirs = Get-ChildItem -LiteralPath $Root -Recurse -Directory |
        Sort-Object { $_.FullName.Length } -Descending
    foreach ($d in $sortedDirs) {
        if ((Get-ChildItem -LiteralPath $d.FullName -Force -ErrorAction SilentlyContinue | Measure-Object).Count -eq 0) {
            Remove-Item -LiteralPath $d.FullName -Force
            $removedDirs++
        }
    }
    Write-Host "Removed empty folders: $removedDirs"
}
