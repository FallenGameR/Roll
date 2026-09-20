<#
    Длительности треков для каталога Winamp.

    В индексе медиатеки время звучания хранится числом, а в Tracks.csv
    его нет, поэтому считаем ffprobe. Для 377 треков это заметно, так
    что результат кэшируется рядом со списками и повторные выгрузки
    идут мгновенно.
#>
function Get-TrackDurationCachePath {
    Join-Path 'C:\vaults\Music\_playlists' '.durations.json'
}

function Get-TrackDurationCache {
    $path = Get-TrackDurationCachePath
    $cache = @{}
    if (Test-Path -LiteralPath $path) {
        $data = Get-Content -LiteralPath $path -Raw | ConvertFrom-Json
        foreach ($property in $data.PSObject.Properties) {
            $cache[$property.Name] = [double] $property.Value
        }
    }
    return $cache
}

function Save-TrackDurationCache {
    param([hashtable] $Cache)

    $path = Get-TrackDurationCachePath
    $folder = Split-Path $path -Parent
    if (-not (Test-Path -LiteralPath $folder)) {
        $null = New-Item -ItemType Directory -Path $folder -Force
    }
    $Cache | ConvertTo-Json -Depth 2 |
        Set-Content -LiteralPath $path -Encoding UTF8
}

function Get-TrackDuration {
    param(
        [string] $Path,
        [hashtable] $Cache
    )

    if ($Cache.ContainsKey($Path)) { return $Cache[$Path] }
    if (-not (Test-Path -LiteralPath $Path)) { return 0 }

    if (-not $script:RollFfprobe) {
        $script:RollFfprobe = Join-Path (Split-Path (Find-WingetTool `
            "Gyan.FFmpeg_*" "ffmpeg.exe")) "ffprobe.exe"
    }
    $output = & $script:RollFfprobe -v error -show_entries format=duration `
        -of default=nw=1:nk=1 -- $Path 2>$null
    $seconds = 0.0
    if ([double]::TryParse($output, [ref] $seconds)) {
        $Cache[$Path] = $seconds
        return $seconds
    }
    return 0
}
