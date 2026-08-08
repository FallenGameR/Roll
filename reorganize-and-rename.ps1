<#
.SYNOPSIS
    Reorganizes the RPG Music library into flat album folders and renames
    every mp3 to "<Album> <Album Artist> - <Title> (<Artist>).mp3" (Album
    Artist and Artist each omitted if empty), then merges any resulting
    tiny album folders (<= 3 tracks) into a single "Misc" folder.

.DESCRIPTION
    Works entirely through the C:\vaults junctions - never touches
    OneDrive paths directly.

    Steps:
      1. Read album/album_artist/artist/title tags of every mp3
         (recursively).
      2. Move each file into "<Root>\<sanitized album>\", flattening any
         existing subfolder structure.
      3. Rename each file to the template above, sanitizing forbidden
         Windows filename characters (fullwidth lookalikes, consistent
         with existing yt-dlp-produced names in this library).
      4. Resolve filename collisions by appending " (n)".
      5. Remove now-empty folders.
      6. Any album folder left with <= $MiscThreshold files has its
         files moved into "<Root>\Misc\" (renamed files, so no further
         action needed there), then the emptied folder is removed.

.PARAMETER Root
    Root of the music library (use the C:\vaults junction, not OneDrive).

.PARAMETER MiscThreshold
    Folders with this many files or fewer get merged into Misc. Default 3.

.PARAMETER WhatIf
    If set, only prints planned actions without touching any files.
#>

param(
    [string]$Root = "C:\vaults\Music",
    [int]$MiscThreshold = 3,
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

# Windows-forbidden filename characters -> fullwidth lookalikes, matching
# the convention yt-dlp already used elsewhere in this library.
function Get-SafeName([string]$name) {
    $name = $name.Trim()
    $map = @{
        '\' = '⧹'; '/' = '⧸'; ':' = '：'; '*' = '＊'
        '?' = '？'; '"' = '＂'; '<' = '＜'; '>' = '＞'; '|' = '｜'
    }
    foreach ($k in $map.Keys) { $name = $name.Replace($k, $map[$k]) }
    return $name
}

function Get-Tag($file, $tagName) {
    $out = & $ffprobe -v error -show_entries "format_tags=$tagName" -of default=noprint_wrappers=1:nokey=1 -- $file
    if ($null -eq $out) { return "" }
    return ($out -join "`n").Trim()
}

$files = Get-ChildItem -LiteralPath $Root -Recurse -Filter *.mp3 -File
Write-Host "Found $($files.Count) mp3 files."

$moved = 0
$errors = 0
$i = 0

foreach ($f in $files) {
    $i++
    if ($i % 50 -eq 0) { Write-Host "... $i / $($files.Count)" }

    try {
        $album = Get-Tag $f.FullName "album"
        $albumArtist = Get-Tag $f.FullName "album_artist"
        $title = Get-Tag $f.FullName "title"
        $artist = Get-Tag $f.FullName "artist"

        if ([string]::IsNullOrWhiteSpace($album)) {
            Write-Host "SKIP (no album tag): $($f.FullName)"
            continue
        }
        if ([string]::IsNullOrWhiteSpace($title)) {
            Write-Host "SKIP (no title tag): $($f.FullName)"
            continue
        }

        $safeAlbum = Get-SafeName $album
        $targetDir = Join-Path $Root $safeAlbum

        if ($albumArtist) {
            $newBaseName = "$album $albumArtist - $title"
        }
        else {
            $newBaseName = "$album - $title"
        }
        if ($artist) {
            $newBaseName = "$newBaseName ($artist)"
        }
        $safeBaseName = Get-SafeName $newBaseName
        $targetPath = Join-Path $targetDir "$safeBaseName.mp3"

        if ($WhatIf) {
            Write-Host "WOULD MOVE/RENAME: $($f.FullName) -> $targetPath"
            continue
        }

        if (-not (Test-Path -LiteralPath $targetDir)) {
            New-Item -ItemType Directory -Path $targetDir -Force | Out-Null
        }

        if ((Test-Path -LiteralPath $targetPath) -and ($targetPath -ne $f.FullName)) {
            $n = 2
            do {
                $targetPath = Join-Path $targetDir "$safeBaseName ($n).mp3"
                $n++
            } while (Test-Path -LiteralPath $targetPath)
        }

        if ($targetPath -ne $f.FullName) {
            Move-Item -LiteralPath $f.FullName -Destination $targetPath
            $moved++
        }
    }
    catch {
        Write-Host "ERROR on $($f.FullName): $_"
        $errors++
    }
}

Write-Host ""
Write-Host "Moved/renamed: $moved | Errors: $errors"

if ($WhatIf) { return }

# Remove now-empty folders left behind by the move above.
$sortedDirs = Get-ChildItem -LiteralPath $Root -Recurse -Directory |
    Sort-Object { $_.FullName.Length } -Descending
foreach ($d in $sortedDirs) {
    if ((Get-ChildItem -LiteralPath $d.FullName -Force -ErrorAction SilentlyContinue | Measure-Object).Count -eq 0) {
        Remove-Item -LiteralPath $d.FullName -Force
    }
}

# Merge tiny album folders into Misc.
$miscDir = Join-Path $Root "Misc"
if (-not (Test-Path -LiteralPath $miscDir)) {
    New-Item -ItemType Directory -Path $miscDir -Force | Out-Null
}

$albumDirs = Get-ChildItem -LiteralPath $Root -Directory | Where-Object { $_.Name -ne "Misc" }
$mergedCount = 0
foreach ($d in $albumDirs) {
    $tracks = Get-ChildItem -LiteralPath $d.FullName -Filter *.mp3 -File
    if ($tracks.Count -le $MiscThreshold) {
        foreach ($t in $tracks) {
            $dest = Join-Path $miscDir $t.Name
            if (Test-Path -LiteralPath $dest) {
                $base = [System.IO.Path]::GetFileNameWithoutExtension($t.Name)
                $ext = $t.Extension
                $n = 2
                do {
                    $dest = Join-Path $miscDir "$base ($n)$ext"
                    $n++
                } while (Test-Path -LiteralPath $dest)
            }
            Move-Item -LiteralPath $t.FullName -Destination $dest
            $mergedCount++
        }
        # Remove the now-emptied (or already-empty) small album folder.
        if ((Get-ChildItem -LiteralPath $d.FullName -Force -ErrorAction SilentlyContinue | Measure-Object).Count -eq 0) {
            Remove-Item -LiteralPath $d.FullName -Force
        }
    }
}

Write-Host "Merged into Misc: $mergedCount files from small album folders (<= $MiscThreshold tracks)."
Write-Host "Final album folder count: $((Get-ChildItem -LiteralPath $Root -Directory).Count)"
Write-Host "Final mp3 count: $((Get-ChildItem -LiteralPath $Root -Recurse -Filter *.mp3).Count)"
