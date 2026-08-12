<#
.SYNOPSIS
    Lists every mp3 in the RPG Music library with its Genre and Comment
    id3 tags decomposed into structured Roll.MusicTrack objects.

.DESCRIPTION
    Each track's Genre id3 tag is a heuristic taxonomy string (e.g.
    "Background Dread/Secrets Anomaly Modern/SciFi"), not a fixed schema:
    space-separated groups, optionally with "/"-separated alternatives
    inside a group. Tokens are flattened and bucketed via a known-tag
    dictionary (Private/Get-GenreTaxonomy.ps1) into:
      - Type      = scene role (Background/Combat/Tension/Crisis/Effect)
      - Mood      = emotional tone (Dread/Haven/Hostile/Tragic/...)
      - Setting   = world backdrop (Fantasy/Modern/SciFi/Urban/Tavern/...)
      - Modifier  = usage hints (Chase/Investigation/Vocals/Intro/...)
      - Unmatched = any tag not yet known to the dictionary (should
                    normally be empty; a non-empty value means the
                    taxonomy needs to be extended)

    The Comment id3 tag is similarly split into:
      - Situation   = the scene/prompt the track suits
      - Description = the musical description ("Description: ...")
      - Source      = the source URL ("Source: ..."), $null if missing

    Objects are tagged with the Roll.MusicTrack type name, which has a
    default table view (see Roll.Format.ps1xml) equivalent to
    `Format-Table -AutoSize`.

.PARAMETER Root
    Root of the music library to scan. Defaults to the RPG Music library.
    Point this at a small subfolder while testing to keep runs fast.

.EXAMPLE
    Get-MusicTrackList
.EXAMPLE
    Get-MusicTrackList -Root "C:\vaults\Music\03 - D&D Combat"
.EXAMPLE
    Get-MusicTrackList | Where-Object { $_.Type -contains 'Combat' }
#>
function Get-MusicTrackList {
    param(
        [string]$Root = "C:\vaults\Music"
    )

    $ErrorActionPreference = "Stop"

    $ffprobe = Join-Path (Split-Path (Find-WingetTool "Gyan.FFmpeg_*" "ffmpeg.exe")) "ffprobe.exe"

    $files = Get-ChildItem -LiteralPath $Root -Recurse -Filter *.mp3 -File

    foreach ($f in $files) {
        $genre = & $ffprobe -v error -show_entries format_tags=genre -of default=noprint_wrappers=1:nokey=1 -- $f.FullName
        $commentRaw = & $ffprobe -v error -show_entries format_tags=comment -of default=noprint_wrappers=1:nokey=1 -- $f.FullName
        $comment = ($commentRaw -join "`n").Trim()

        # Flatten to one line: turn blank-line paragraph breaks into " | "
        # so the whole comment (situation / description / source) stays
        # visible on a single row instead of being cut off after the
        # first line.
        $flatComment = ($comment -replace "(`r`n|`r|`n)+", " | ").Trim()

        $tags = Split-GenreTag -Genre $genre
        $genreCategories = ConvertTo-GenreCategory -Tags $tags
        $commentParts = ConvertTo-CommentParts -Comment $flatComment

        [PSCustomObject]@{
            PSTypeName  = 'Roll.MusicTrack'
            Name        = [System.IO.Path]::GetFileNameWithoutExtension($f.Name)
            Type        = $genreCategories.Type
            Mood        = $genreCategories.Mood
            Setting     = $genreCategories.Setting
            Modifier    = $genreCategories.Modifier
            Unmatched   = $genreCategories.Unmatched
            Situation   = $commentParts.Situation
            Description = $commentParts.Description
            Source      = $commentParts.Source
        }
    }
}
