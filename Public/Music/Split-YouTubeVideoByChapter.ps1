<#
.SYNOPSIS
    Splits a single already-downloaded YouTube mix (mp3, with embedded
    thumbnail) into individual tracks using the video's own YouTube
    Chapters (start/end timestamps + names), when the mix author encoded
    one video as multiple songs.

.DESCRIPTION
    Many "mix" videos in our RPG music library are actually several tracks
    concatenated into one YouTube video, with the track boundaries marked
    as YouTube Chapters (visible in the "Chapters" tab under the video).
    yt-dlp can split by those chapters directly from the source URL
    (re-using the local ffmpeg/deno tools already installed for this
    project), but it does NOT propagate per-chapter title/artist metadata
    to the split files (known yt-dlp limitation) - only the filename ends
    up correct. This function fixes that with a second ffmpeg pass that
    parses "Artist - Title" from each split filename and writes it back as
    proper id3 tags (title/artist/album/track), preserving the embedded
    cover art (stream-copy, no re-encode).

    Result layout: the original combined mp3 is deleted and replaced by a
    subfolder (named exactly like the original file, without extension)
    containing the individual numbered tracks.

.PARAMETER VideoUrl
    URL (or bare video ID) of the source video. Must have YouTube Chapters.

.PARAMETER ExistingFile
    Path to the already-downloaded combined mp3 for this video (as found
    in the RPG Music library). It will be deleted after a successful split.

.EXAMPLE
    Split-YouTubeVideoByChapter `
        -VideoUrl "https://www.youtube.com/watch?v=9II8wyujeAw" `
        -ExistingFile "C:\vaults\Music\VtM London\01 - John Wick.mp3"
#>
function Split-YouTubeVideoByChapter {
    param(
        [Parameter(Mandatory = $true)]
        [string]$VideoUrl,

        [Parameter(Mandatory = $true)]
        [string]$ExistingFile
    )

    $ErrorActionPreference = "Stop"

    $ytDlp = Get-YtDlpPath

    $ffmpegDir = Split-Path (Find-WingetTool "Gyan.FFmpeg_*" "ffmpeg.exe")
    $ffmpeg = Join-Path $ffmpegDir "ffmpeg.exe"
    $deno = Find-WingetTool "DenoLand.Deno_*" "deno.exe"

    # Use -LiteralPath everywhere below: track/filenames routinely contain
    # "[...]" (e.g. "[Copyright Free]") which Test-Path/Get-Item would
    # otherwise interpret as wildcard patterns instead of literal characters.
    if (-not (Test-Path -LiteralPath $ExistingFile)) {
        throw "ExistingFile not found: $ExistingFile"
    }

    $existingItem = Get-Item -LiteralPath $ExistingFile
    $parentDir = $existingItem.DirectoryName
    $albumTitle = $existingItem.BaseName
    $subfolder = Join-Path $parentDir $albumTitle

    if (Test-Path -LiteralPath $subfolder) {
        throw "Target subfolder already exists: $subfolder (aborting to avoid clobbering)"
    }
    New-Item -ItemType Directory -Path $subfolder -Force | Out-Null

    # 1) Ask yt-dlp to split by chapters. This re-downloads/re-uses the
    #    source video and writes one mp3 per chapter, named
    #    "NN - <chapter title>.mp3".
    & $ytDlp --ffmpeg-location $ffmpegDir --js-runtimes "deno:$deno" --remote-components "ejs:github" `
        -x --audio-format mp3 --audio-quality 0 --embed-thumbnail --add-metadata `
        --split-chapters --no-keep-video `
        -o "chapter:$subfolder\%(section_number)02d - %(section_title)s.%(ext)s" `
        $VideoUrl

    $splitFiles = Get-ChildItem -LiteralPath $subfolder -Filter *.mp3
    if ($splitFiles.Count -eq 0) {
        Remove-Item -LiteralPath $subfolder -Recurse -Force
        throw "No chapters were found/split for $VideoUrl - does the video actually have YouTube Chapters?"
    }

    # 2) Fix up per-track metadata: yt-dlp does not propagate chapter
    #    titles to the split files' own id3 tags, only to the filename.
    #    Parse "Artist - Title" out of each filename and rewrite tags via
    #    ffmpeg (stream-copy, so cover art and audio are preserved
    #    bit-for-bit).
    foreach ($f in $splitFiles) {
        if ($f.BaseName -match '^(\d+) - (.+?) - (.+)$') {
            $track = [int]$matches[1]
            $artist = $matches[2]
            $title = $matches[3]
        }
        else {
            $track = $null
            $artist = $null
            $title = ($f.BaseName -replace '^\d+ - ')
        }
        $tmp = "$($f.FullName).tmp.mp3"
        & $ffmpeg -y -v error -i $f.FullName -map 0 -c copy `
            -metadata title="$title" -metadata artist="$artist" `
            -metadata album="$albumTitle" -metadata track="$track" `
            $tmp
        Move-Item $tmp $f.FullName -Force
        Write-Host "  [$track] $artist - $title"
    }

    # 3) Remove the original combined file now that the split exists.
    Remove-Item -LiteralPath $ExistingFile -Force

    Write-Host "Done: $($splitFiles.Count) tracks written to $subfolder"
}
