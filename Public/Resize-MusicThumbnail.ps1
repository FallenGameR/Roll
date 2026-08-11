<#
.SYNOPSIS
    Shrinks oversized embedded cover art in all mp3 files under the RPG
    Music library down to a max of 640px on the longest side, to stop
    large thumbnails (e.g. 1280x720) from bloating audio file sizes.

.DESCRIPTION
    Scans every mp3 recursively, checks the embedded picture (attached_pic
    video stream) dimensions via ffprobe, and re-embeds a resized copy via
    ffmpeg for any file whose thumbnail exceeds 640px on the longest side.
    Audio is stream-copied (no re-encode, no quality loss); only the
    embedded image is re-encoded as mjpeg. Files whose thumbnail is
    already <= 640px, or that have no embedded thumbnail, are left alone.

.PARAMETER Root
    Root folder to scan recursively. Defaults to the RPG Music library.

.PARAMETER MaxSize
    Max pixels on the longest side of the embedded thumbnail. Default 640.

.EXAMPLE
    Resize-MusicThumbnail
#>
function Resize-MusicThumbnail {
    param(
        [string]$Root = "C:\vaults\Music",
        [int]$MaxSize = 640
    )

    $ErrorActionPreference = "Stop"

    $ffmpegDir = Split-Path (Find-WingetTool "Gyan.FFmpeg_*" "ffmpeg.exe")
    $ffmpeg = Join-Path $ffmpegDir "ffmpeg.exe"
    $ffprobe = Join-Path $ffmpegDir "ffprobe.exe"

    $files = Get-ChildItem -LiteralPath $Root -Recurse -Filter *.mp3 -File
    $resized = 0
    $skippedNoArt = 0
    $skippedSmall = 0
    $failed = 0
    $totalSavedBytes = 0
    $i = 0

    foreach ($f in $files) {
        $i++
        if ($i % 25 -eq 0) { Write-Host "... $i / $($files.Count)" }

        $dims = & $ffprobe -v error -select_streams v -show_entries stream=width,height -of csv=p=0 -- $f.FullName 2>$null
        if (-not $dims) { $skippedNoArt++; continue }

        $parts = $dims -split ','
        $w = [int]$parts[0]
        $h = [int]$parts[1]
        if ([Math]::Max($w, $h) -le $MaxSize) { $skippedSmall++; continue }

        $origSize = $f.Length
        $tmp = "$($f.FullName).resize-tmp.mp3"
        $vf = "scale='min($MaxSize,iw)':'min($MaxSize,ih)':force_original_aspect_ratio=decrease,scale=trunc(iw/2)*2:trunc(ih/2)*2"

        try {
            & $ffmpeg -y -v error -i $f.FullName -map 0:a -map 0:v `
                -c:a copy -c:v mjpeg -vf $vf -disposition:v attached_pic -id3v2_version 3 `
                $tmp
            if (-not (Test-Path -LiteralPath $tmp) -or (Get-Item -LiteralPath $tmp).Length -eq 0) {
                throw "ffmpeg produced no output"
            }
            Move-Item -LiteralPath $tmp -Destination $f.FullName -Force
            $newSize = (Get-Item -LiteralPath $f.FullName).Length
            $totalSavedBytes += ($origSize - $newSize)
            $resized++
            Write-Host "Resized ($w x $h -> <=$MaxSize): $($f.FullName.Substring($Root.Length+1))"
        }
        catch {
            Write-Host "FAILED: $($f.FullName) - $_"
            if (Test-Path -LiteralPath $tmp) { Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue }
            $failed++
        }
    }

    Write-Host ""
    Write-Host "Done. Resized: $resized | Already small: $skippedSmall | No artwork: $skippedNoArt | Failed: $failed"
    Write-Host ("Space saved: {0:N1} MB" -f ($totalSavedBytes / 1MB))
}
