<#
.SYNOPSIS
    Downloads a YouTube playlist as best-quality mp3 files with embedded
    thumbnails (cover art), for use as RPG background music.

.DESCRIPTION
    Wraps yt-dlp + ffmpeg + deno (JS challenge solver runtime, required by
    YouTube since 2026) to download every track of a playlist as mp3
    (VBR ~200-250kbps, i.e. the best that YouTube's audio-only streams
    offer - YouTube Premium does not unlock higher bitrates via yt-dlp as
    of mid-2025), embeds the video thumbnail as cover art, and writes ID3
    tags.

    Tracks are saved into a subfolder named after the playlist title, with
    a numeric prefix that preserves playlist order.

    Requires (installed via winget):
      - yt-dlp.exe   (already present on this machine)
      - ffmpeg        (winget install --id Gyan.FFmpeg)
      - deno          (winget install --id DenoLand.Deno)

.PARAMETER PlaylistUrl
    Full YouTube playlist (or video+list) URL.

.PARAMETER OutputRoot
    Root folder where a subfolder per playlist will be created. Defaults
    to the RPG music library (via the C:\vaults junction).

.PARAMETER PlaylistName
    Explicit subfolder name for the playlist. When omitted, the playlist
    title reported by YouTube is used, which is often noisy (channel
    names, "Full OST" suffixes and so on).

.EXAMPLE
    Save-YouTubePlaylist -PlaylistUrl "https://www.youtube.com/watch?v=QpEyWegZ4PQ&list=PL2VAyAqd6lNqoAnhiI3iZAu-Bnr-C80DU"
#>
function Save-YouTubePlaylist {
    param(
        [Parameter(Mandatory = $true)]
        [string]$PlaylistUrl,

        [string]$OutputRoot = "C:\vaults\Music",

        [string]$PlaylistName
    )

    $ErrorActionPreference = "Stop"

    # yt-dlp is a fixed personal install; ffmpeg/deno are installed via
    # winget and may land in a versioned package folder, so we resolve
    # them dynamically instead of hardcoding a version number.
    $ytDlp = Get-YtDlpPath

    $ffmpegDir = Split-Path (Find-WingetTool "Gyan.FFmpeg_*" "ffmpeg.exe")
    $deno = Find-WingetTool "DenoLand.Deno_*" "deno.exe"

    if (-not (Test-Path $ytDlp)) {
        throw "yt-dlp.exe not found at $ytDlp"
    }

    New-Item -ItemType Directory -Path $OutputRoot -Force | Out-Null

    $folderTemplate = if ($PlaylistName) { $PlaylistName } else { "%(playlist_title)s" }

    & $ytDlp `
        --ffmpeg-location $ffmpegDir `
        --js-runtimes "deno:$deno" `
        --remote-components "ejs:github" `
        --extract-audio --audio-format mp3 --audio-quality 0 `
        --embed-thumbnail `
        --add-metadata `
        --ignore-errors `
        --download-archive "$OutputRoot\.archive.txt" `
        -o "$OutputRoot\$folderTemplate\%(playlist_index)02d - %(title)s.%(ext)s" `
        $PlaylistUrl
}
