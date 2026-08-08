<#
.SYNOPSIS
    Batch-downloads all YouTube playlists listed in playlists-progress.json
    as best-quality mp3 with embedded thumbnails, tracking progress in that
    same JSON file so a crash/interruption can be resumed without redoing
    already-finished playlists.

.DESCRIPTION
    For each playlist entry with status "pending" (or "error", to retry):
      1. marks it "in_progress" and saves the json (so progress survives a
         crash)
      2. runs yt-dlp (same options as download-youtube-playlist.ps1)
      3. parses yt-dlp's own output to count already-known vs failed items
      4. records the resulting playlist title, ok/failed track counts and
         status ("done" if at least one track succeeded, "error" if none)
      5. saves the json again

    Safe to re-run: playlists already "done" are skipped, and yt-dlp's
    --download-archive means tracks already downloaded are not re-fetched.

.PARAMETER ProgressFile
    Path to the JSON file tracking playlists (see playlists-progress.json).
#>

param(
    [string]$ProgressFile = "$PSScriptRoot\playlists-progress.json"
)

$ErrorActionPreference = "Stop"

$ytDlp = "C:\Users\alexk\OneDrive\Apps\Tools\yt-dpl\yt-dlp.exe"

function Find-WingetTool([string]$packageGlob, [string]$exeName) {
    $found = Get-ChildItem "$env:LOCALAPPDATA\Microsoft\WinGet\Packages\$packageGlob" `
        -Recurse -Filter $exeName -ErrorAction SilentlyContinue |
        Select-Object -First 1 -ExpandProperty FullName
    if (-not $found) {
        throw "Could not find $exeName under WinGet packages matching '$packageGlob'."
    }
    return $found
}

$ffmpegDir = Split-Path (Find-WingetTool "Gyan.FFmpeg_*" "ffmpeg.exe")
$deno = Find-WingetTool "DenoLand.Deno_*" "deno.exe"

function Save-Progress($data) {
    # Retry a few times: the json can be transiently locked by an external
    # process (editor, another shell inspecting progress, OneDrive, etc.).
    $json = $data | ConvertTo-Json -Depth 5
    $attempt = 0
    while ($true) {
        try {
            Set-Content -Path $ProgressFile -Value $json -Encoding utf8
            return
        }
        catch {
            $attempt++
            if ($attempt -ge 10) { throw }
            Start-Sleep -Milliseconds 500
        }
    }
}

$data = Get-Content $ProgressFile -Raw | ConvertFrom-Json
$root = $data.outputRoot

foreach ($pl in $data.playlists) {
    if ($pl.status -eq "done") {
        Write-Host "[$($pl.index)] SKIP (already done): $($pl.url)"
        continue
    }

    Write-Host "[$($pl.index)] Downloading: $($pl.url)"
    $pl.status = "in_progress"
    Save-Progress $data

    $logFile = Get-Item ([System.IO.Path]::GetTempFileName())
    $ok = 0
    $failed = 0
    $title = $null

    # Prefix the destination folder with our own list index (not just
    # YouTube's playlist title) to avoid collisions - some playlists report
    # an empty/"NA" title, and without this prefix two such playlists would
    # dump their tracks into the same folder.
    $folderPrefix = "{0:D2}" -f [int]$pl.index

    try {
        # Run in a nested scriptblock with ErrorActionPreference=Continue so
        # that yt-dlp's stderr output (warnings, non-fatal messages), which
        # PowerShell converts to ErrorRecord objects when merged via 2>&1,
        # does not turn into a terminating exception that would kill this
        # loop mid-playlist (the outer script uses "Stop" globally).
        & {
            $ErrorActionPreference = "Continue"
            & $ytDlp `
                --ffmpeg-location $ffmpegDir `
                --js-runtimes "deno:$deno" `
                --remote-components "ejs:github" `
                --extract-audio --audio-format mp3 --audio-quality 0 `
                --embed-thumbnail `
                --add-metadata `
                --ignore-errors `
                --max-downloads 300 `
                --download-archive "$root\.archive.txt" `
                -o "$root\$folderPrefix - %(playlist_title)s\%(playlist_index)02d - %(title)s.%(ext)s" `
                --print-to-file "%(playlist_title)s" "$logFile.title" `
                $pl.url 2>&1
        } | ForEach-Object {
            $line = $_.ToString()
            Write-Host $line
            Add-Content -Path $logFile.FullName -Value $line
            if ($line -match '^\[download\] Destination:' -or
                $line -match 'has already been downloaded' -or
                $line -match 'has already been recorded in the archive') { $ok++ }
            if ($line -match '^ERROR:') { $failed++ }
        }
    }
    catch {
        Write-Host "EXCEPTION while downloading playlist $($pl.index): $_"
        $failed++
    }

    if (Test-Path "$logFile.title") {
        $title = (Get-Content "$logFile.title" -Raw -ErrorAction SilentlyContinue |
            Select-Object -First 1) -split "`n" | Select-Object -First 1
        Remove-Item "$logFile.title" -ErrorAction SilentlyContinue
    }
    Remove-Item $logFile -ErrorAction SilentlyContinue

    $pl.title = $title
    $pl.tracks_ok = $ok
    $pl.tracks_failed = $failed
    $pl.status = if ($ok -gt 0) { "done" } else { "error" }
    if ($failed -gt 0) {
        $pl.notes = ("$($pl.notes) | $failed item(s) failed - see console output above").Trim(" |")
    }
    Save-Progress $data

    Write-Host "[$($pl.index)] Finished: status=$($pl.status) ok=$ok failed=$failed title=$title"
}

Write-Host "All playlists processed. See $ProgressFile for the summary."
