<#
.SYNOPSIS
    Trims mp3 files to a maximum duration, keeping the embedded cover art.

.DESCRIPTION
    ffmpeg truncates the single-frame cover video stream together with the
    audio when -t is used, which produces a file with a broken picture.
    So the work is done in two passes: first the audio is cut, then the
    cover from the original file is attached back.

    Files shorter than -MaxSeconds are left untouched.

.EXAMPLE
    .\Trim-Audio.ps1 -Path C:\vaults\Music\Effects-new -MaxSeconds 360
#>
param(
    [Parameter(Mandatory = $true)]
    [string]$Path,

    [int]$MaxSeconds = 360
)

$ErrorActionPreference = 'Stop'

$pkg = "$env:LOCALAPPDATA\Microsoft\WinGet\Packages\Gyan.FFmpeg_*"
$ffmpeg = (Get-ChildItem $pkg -Recurse -Filter ffmpeg.exe | Select-Object -First 1).FullName
$ffprobe = (Get-ChildItem $pkg -Recurse -Filter ffprobe.exe | Select-Object -First 1).FullName

foreach ($file in Get-ChildItem $Path -Filter *.mp3) {
    $duration = [double](& $ffprobe -v error -show_entries format=duration `
        -of default=noprint_wrappers=1:nokey=1 $file.FullName)

    if ($duration -le $MaxSeconds) {
        Write-Host ("keep {0,7:N0}s  {1}" -f $duration, $file.Name)
        continue
    }

    $audio = Join-Path $file.DirectoryName "$($file.BaseName).trim-audio.mp3"
    $out = Join-Path $file.DirectoryName "$($file.BaseName).trim-out.mp3"

    # Pass 1: audio only, no cover stream at all.
    & $ffmpeg -v error -y -i $file.FullName -map 0:a:0 -t $MaxSeconds `
        -c:a copy -map_metadata 0 $audio

    # Pass 2: attach the cover from the original untrimmed file.
    & $ffmpeg -v error -y -i $audio -i $file.FullName `
        -map 0:a:0 -map "1:v:0?" -c copy -id3v2_version 3 `
        -metadata:s:v title="Album cover" `
        -metadata:s:v comment="Cover (front)" $out

    Remove-Item $audio
    Remove-Item $file.FullName
    Move-Item $out $file.FullName

    Write-Host ("trim {0,7:N0}s -> {1}s  {2}" -f $duration, $MaxSeconds, $file.Name)
}
