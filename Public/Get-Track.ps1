<#
.SYNOPSIS
    Lists every mp3 under Path with its Genre and Comment id3 tags
    decomposed into structured Roll.MusicTrack objects.

.DESCRIPTION
    Each track's Genre id3 tag is a string built from a 6-category
    tagging scheme (e.g. "Background Dread/Secrets Anomaly Modern/SciFi"):
    space-separated groups, optionally with "/"-separated alternatives
    inside a group. Tokens are flattened and bucketed via the known-tag
    dictionary (Private/Get-GenreTaxonomy.ps1) into:
      - Intensity = energy/pacing (Background/Tension/Combat/Crisis)
      - Emotion   = emotional/narrative tone (Dread/Haven/Hostile/...)
      - Scene     = place + type of content (Depths/Urban/Tavern/Lively/
                    Chase/Investigation/Anomaly)
      - Game      = source-material era (Fantasy/Modern/SciFi)
      - Type      = catch-all bucket for everything that isn't
                    Intensity/Emotion/Scene/Game: production hints
                    (Effect = soundboard/sfx, Vocals = has singing/
                    lyrics), the Intro/Outro campaign theme markers,
                    Unsorted (pipeline hasn't finished categorizing this
                    track yet), and any tag not yet known to the
                    dictionary (should normally not appear; if it does,
                    the taxonomy needs to be extended). These are all
                    just elements of the same Type array - not separate
                    boolean/array properties - so filtering for any of
                    them is always `$_.Type -contains 'X'`.

    The Comment id3 tag is similarly split into:
      - Situation   = the scene/prompt the track suits
      - Description = the musical description ("Description: ...")
      - Source      = the source URL ("Source: ..."), $null if missing

    Objects are tagged with the Roll.MusicTrack type name, which has a
    default table view (see Roll.Format.ps1xml) equivalent to
    `Format-Table -AutoSize`.

.PARAMETER Path
    Folder to scan for mp3s. Defaults to the RPG Music library root.
    Pass "." to scan the current working directory instead (handy for a
    quick, fast test run from a small subfolder).

.EXAMPLE
    Get-Track
.EXAMPLE
    Get-Track .
.EXAMPLE
    Get-Track -Path "C:\vaults\Music\03 - D&D Combat"
.EXAMPLE
    Get-Track | Where-Object { $_.Intensity -contains 'Combat' }
#>
function Get-Track {
    param(
        [string]$Path = "C:\vaults\Music"
    )

    $ErrorActionPreference = "Stop"

    if ($Path -eq '.') {
        $Path = (Get-Location).Path
    }

    $ffprobe = Join-Path (Split-Path (Find-WingetTool "Gyan.FFmpeg_*" "ffmpeg.exe")) "ffprobe.exe"

    $files = Get-ChildItem -LiteralPath $Path -Recurse -Filter *.mp3 -File

    foreach ($f in $files) {
        # A single ffprobe call reading both tags at once (via -of json)
        # instead of one call per tag roughly halves the per-file cost.
        $json = & $ffprobe -v error -show_entries format_tags=genre,comment -of json -- $f.FullName
        $probeTags = ($json -join "`n" | ConvertFrom-Json).format.tags

        $genre = $probeTags.genre
        $comment = $(if ($probeTags.comment) { $probeTags.comment } else { '' }).Trim()

        # Flatten to one line: turn blank-line paragraph breaks into " | "
        # so the whole comment (situation / description / source) stays
        # visible on a single row instead of being cut off after the
        # first line.
        $flatComment = ($comment -replace "(`r`n|`r|`n)+", " | ").Trim()

        $genreCategories = ConvertTo-GenreCategory -Genre $genre
        $commentParts = ConvertTo-CommentParts -Comment $flatComment

        # Type is the single catch-all array for everything that isn't
        # Intensity/Emotion/Scene/Game: the production-hint category
        # values (Effect/Vocals), the Intro/Outro/Unsorted pipeline
        # meta-flags, and any Unmatched (not-yet-categorized) tokens.
        # These aren't rendered as an array from separate booleans/lists
        # - they ARE array elements, exactly like Intensity/Emotion/Scene/
        # Game, so every viewer (console table, Out-GridView, CSV export
        # via Export-Track, ...) treats them identically instead of
        # needing special-cased boolean/array properties.
        $type = [System.Collections.Generic.List[string]]::new()
        $type.AddRange([string[]]$genreCategories.Type)
        if ($genreCategories.IsIntro) { $type.Add('Intro') }
        if ($genreCategories.IsOutro) { $type.Add('Outro') }
        if ($genreCategories.IsUnsorted) { $type.Add('Unsorted') }
        $type.AddRange([string[]]$genreCategories.Unmatched)

        [PSCustomObject]@{
            PSTypeName  = 'Roll.MusicTrack'
            Name        = [System.IO.Path]::GetFileNameWithoutExtension($f.Name)
            Intensity   = $genreCategories.Intensity
            Emotion     = $genreCategories.Emotion
            Scene       = $genreCategories.Scene
            Game        = $genreCategories.Game
            Type        = $type.ToArray()
            Situation   = $commentParts.Situation
            Description = $commentParts.Description
            Source      = $commentParts.Source
        }
    }
}
