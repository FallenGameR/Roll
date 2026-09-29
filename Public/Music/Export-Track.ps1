<#
.SYNOPSIS
    Exports Get-Track output (or any Roll.MusicTrack objects piped in) to
    a CSV file, correctly flattening the array-valued categories
    (Intensity/Emotion/Scene/Game/Type) so the CSV round-trips cleanly
    through Import-Track.

.DESCRIPTION
    Export-Csv has no idea what to do with a PSCustomObject property that
    holds a string[] - it just calls .ToString() on it, which produces
    the useless literal text "System.Object[]" instead of the actual
    values. Export-Track works around this by joining each array
    property with ';' (semicolon, not comma) before handing the object to
    Export-Csv, so:
      - the joined cell survives Export-Csv's own comma-based column
        quoting untouched (no ambiguity with the CSV delimiter), and
      - Import-Track can split back on ';' to recover the array.

    This is meant to be the one indexing step you run after a tagging
    pass so you have a fast, offline snapshot of the whole library (or a
    subfolder) to repeatedly query from PowerShell/SQL without re-running
    Get-Track's ffprobe scan (which is the slow part) every time.

.PARAMETER Track
    Roll.MusicTrack objects to export, typically piped in from Get-Track.
    If omitted, Export-Track calls Get-Track itself using -Root.

.PARAMETER Root
    Folder to scan for mp3s when Track isn't piped in. Forwarded to
    Get-Track's own -Path as-is (so "." works the same way it does
    there). Ignored if Track is piped in.

.PARAMETER Path
    CSV file to write. Defaults to C:\vaults\Music\Tracks.csv.
    Named Path (not Destination) per the usual PowerShell convention that
    the sole output-file parameter of a cmdlet is called Path (compare
    Export-Csv -Path); Root is the other, differently-purposed path in
    this function so it gets a more specific name instead.

.EXAMPLE
    Export-Track
    Scans the whole library and writes the default Tracks.csv.
.EXAMPLE
    Get-Track -Path "C:\vaults\Music\WH40k" | Export-Track -Path .\wh40k.csv
    Exports just one folder's tracks to a custom file.
.EXAMPLE
    Export-Track -Root "C:\vaults\Music\WH40k"
    Same result as above without an intermediate Get-Track pipe.
#>
function Export-Track {
    [CmdletBinding()]
    param(
        [Parameter(ValueFromPipeline)]
        [PSObject[]]$Track,

        [string]$Root = "C:\vaults\Music",

        [Parameter(Position = 0)]
        [string]$Path = "C:\vaults\Music\Tracks.csv"
    )

    begin {
        $ErrorActionPreference = "Stop"
        $items = [System.Collections.Generic.List[object]]::new()
    }

    process {
        foreach ($t in $Track) { $items.Add($t) }
    }

    end {
        if ($items.Count -eq 0) {
            $items.AddRange([object[]](Get-Track -Path $Root))
        }

        $items |
            Select-Object Name,
                @{Name = 'Intensity'; Expression = { $_.Intensity -join ';' } },
                @{Name = 'Emotion'; Expression = { $_.Emotion -join ';' } },
                @{Name = 'Scene'; Expression = { $_.Scene -join ';' } },
                @{Name = 'Game'; Expression = { $_.Game -join ';' } },
                @{Name = 'Type'; Expression = { $_.Type -join ';' } },
                Situation, Description, Evidence, Note, Source, Path |
            Export-Csv -LiteralPath $Path -NoTypeInformation -Encoding utf8BOM
        # utf8BOM, а не UTF8: Description и Evidence содержат кириллицу,
        # и без BOM Excel открывает файл в ANSI, показывая кракозябры.
        # Import-Csv и Import-Track читают BOM без проблем.

        Get-Item -LiteralPath $Path
    }
}
