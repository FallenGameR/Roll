<#
.SYNOPSIS
    Sets one or more Genre category values (Intensity/Emotion/Scene/Game/
    Type/IsUnsorted/IsExcluded/IsDelete) on a single mp3 file or every mp3
    under a folder, leaving categories that weren't passed untouched.

.DESCRIPTION
    Reads the current Genre tag (via ConvertTo-GenreCategory, so it works
    on both the legacy free-form format and the canonical
    "Category:value1,value2" format), overrides only the categories that
    were explicitly supplied as parameters, and writes the result back
    via ConvertTo-GenreTagString + Set-GenreTag. Any category not passed
    on the command line keeps its existing value(s) - this is a targeted
    update, not a full replace.

    This is the tool intended to be driven by a (semi-)automated tagging
    pass, most immediately backfilling the Game category (Fantasy/Modern/
    SciFi) on tracks that don't have one yet. The intended weighting for
    that decision:
      - Description (highest weight) - what the track actually sounds
        like/is about is the most reliable signal for which game-era it
        fits, regardless of source game.
      - Situation (lower weight) - it was itself generated from
        Description + file name, so it can nudge the decision but should
        not drive it on its own.
      - File name (fallback hint only) - tells you the source game, but a
        track from a Fantasy game can easily fit Modern/SciFi scenes too;
        the actual musical content (Description) overrides that guess.
    Set-Track doesn't do this classification itself - it's just the
    setter a classifier (human or automated) calls once it has decided.

    By default this is a dry run: it only reports Name/Old/New for files
    that would change. Pass -Apply to actually rewrite them.

.PARAMETER Path
    A single mp3 file, or a folder to recurse for mp3s.

.PARAMETER Intensity
    Replaces the Intensity values (Background/Tension/Combat/Crisis).

.PARAMETER Emotion
    Replaces the Emotion values (Dread/Hostile/Haven/Tragic/Triumph/
    Melancholy/Playful/Secrets/Divine/Forbidden).

.PARAMETER Scene
    Replaces the Scene values (Depths/Urban/Tavern/Lively/Chase/Travel/
    Investigation/Anomaly).

.PARAMETER Game
    Replaces the Game values (Fantasy/Modern/SciFi).

.PARAMETER Type
    Replaces the Type values (Effect/Vocals/Intro/Outro).

.PARAMETER IsUnsorted
    Подвешенное состояние трека: ещё не слушали или слушали и не
    решили. К игре допускается. Любая оценка звёздами эту метку
    снимает.

.PARAMETER IsExcluded
    Отложен насовсем: на игре применять не хочется, слушать даже на
    пробу тоже, но пусть лежит на потом.

.PARAMETER IsDelete
    Послушали, не понравилось. Файл остаётся на месте, пока
    Sync-WinampPlaylist не уберёт помеченные в Music\Deleted и не
    вычистит ссылки из подборок.

.PARAMETER Apply
    Actually rewrite the Genre tag in place. Without this switch, the
    function only reports Name/Old/New for tracks that would change.

.EXAMPLE
    Set-Track -Path "C:\vaults\Music\Magicka\Track.mp3" -Game Fantasy -Apply
.EXAMPLE
    Set-Track -Path "C:\vaults\Music\Magicka" -Game Fantasy -Apply
    Tags every mp3 in the Magicka folder as Game:Fantasy, keeping every
    other category untouched.
.EXAMPLE
    Set-Track -Path "C:\vaults\Music\Magicka\Track.mp3" -IsUnsorted:$false -Apply
#>
function Set-Track {
    param(
        [Parameter(Mandatory, Position = 0)]
        [string]$Path,

        [string[]]$Intensity,
        [string[]]$Emotion,
        [string[]]$Scene,
        [string[]]$Game,
        [string[]]$Type,

        [bool]$IsUnsorted,
        [bool]$IsExcluded,
        [bool]$IsDelete,

        [switch]$Apply
    )

    $ErrorActionPreference = "Stop"

    $ffmpegDir = Split-Path (Find-WingetTool "Gyan.FFmpeg_*" "ffmpeg.exe")
    $ffmpeg = Join-Path $ffmpegDir "ffmpeg.exe"
    $ffprobe = Join-Path $ffmpegDir "ffprobe.exe"

    $item = Get-Item -LiteralPath $Path
    $files = if ($item.PSIsContainer) {
        Get-ChildItem -LiteralPath $Path -Recurse -Filter *.mp3 -File
    }
    else {
        @($item)
    }

    foreach ($f in $files) {
        $json = & $ffprobe -v error -show_entries format_tags=genre -of json -- $f.FullName
        $genre = ($json -join "`n" | ConvertFrom-Json).format.tags.genre
        if (-not $genre) { $genre = '' }

        $category = ConvertTo-GenreCategory -Genre $genre

        if ($PSBoundParameters.ContainsKey('Intensity')) { $category.Intensity = $Intensity }
        if ($PSBoundParameters.ContainsKey('Emotion')) { $category.Emotion = $Emotion }
        if ($PSBoundParameters.ContainsKey('Scene')) { $category.Scene = $Scene }
        if ($PSBoundParameters.ContainsKey('Game')) { $category.Game = $Game }
        if ($PSBoundParameters.ContainsKey('Type')) { $category.Type = $Type }
        if ($PSBoundParameters.ContainsKey('IsUnsorted')) { $category.IsUnsorted = $IsUnsorted }
        if ($PSBoundParameters.ContainsKey('IsExcluded')) { $category.IsExcluded = $IsExcluded }
        if ($PSBoundParameters.ContainsKey('IsDelete')) { $category.IsDelete = $IsDelete }

        $newGenre = ConvertTo-GenreTagString -Category $category

        if ($newGenre -eq $genre) {
            continue
        }

        [PSCustomObject]@{
            Name = [System.IO.Path]::GetFileNameWithoutExtension($f.Name)
            Old  = $genre
            New  = $newGenre
        }

        if (-not $Apply) {
            continue
        }

        try {
            Set-GenreTag -Ffmpeg $ffmpeg -File $f -Genre $newGenre
        }
        catch {
            Write-Error $_
        }
    }
}
