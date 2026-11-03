<#
.SYNOPSIS
    Reads a CSV file written by Export-Track back into Roll.MusicTrack
    objects, splitting the ';'-joined array columns
    (Intensity/Emotion/Scene/Game/Type) back into string[].

.DESCRIPTION
    Import-Csv alone would leave every column as a plain string,
    including the array-valued categories (which Export-Track wrote as
    ';'-joined text). Import-Track splits them back so the round-tripped
    objects behave exactly like fresh Get-Track output:
    Intensity/Emotion/Scene/Game/Type are all string[] you can filter
    with -contains.

    Returned objects carry the Roll.MusicTrack type name, so they get the
    same default table view as Get-Track (see Roll.Format.ps1xml).

    Use this together with Export-Track to avoid re-running Get-Track's
    slow ffprobe scan every time you need to query the library - export
    once after a tagging pass, then Import-Track as many times as you
    like for near-instant repeated queries.

.PARAMETER Path
    CSV file to read. Defaults to C:\vaults\Music\Tracks.csv
    (the same default Export-Track writes to).

.EXAMPLE
    Import-Track
    Loads the default Tracks.csv.
.EXAMPLE
    Import-Track | Where-Object { $_.Game -contains 'Fantasy' -and $_.Intensity -contains 'Combat' }
    Fast, offline filtering without touching the mp3 files at all.
.EXAMPLE
    Export-Track; Import-Track
    Refresh the index from the current mp3 tags, then load it back.
#>
function Import-Track {
    [CmdletBinding()]
    param(
        [Parameter(Position = 0)]
        [string]$Path = "C:\vaults\Music\Tracks.csv"
    )

    $ErrorActionPreference = "Stop"

    function ConvertTo-ArrayValue {
        param([string]$Value)
        if ([string]::IsNullOrEmpty($Value)) { return @() }
        return @($Value -split ';')
    }

    Import-Csv -LiteralPath $Path | ForEach-Object {
        [PSCustomObject]@{
            PSTypeName  = 'Roll.MusicTrack'
            Name        = $_.Name
            Intensity   = ConvertTo-ArrayValue $_.Intensity
            Emotion     = ConvertTo-ArrayValue $_.Emotion
            Scene       = ConvertTo-ArrayValue $_.Scene
            Game        = ConvertTo-ArrayValue $_.Game
            Type        = ConvertTo-ArrayValue $_.Type
            Situation   = $_.Situation
            Description = $_.Description
            Measurement = $_.Measurement
            Note        = $_.Note
            Source      = $_.Source
            Path        = $_.Path
        }
    }
}
