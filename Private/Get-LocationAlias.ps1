<#
.SYNOPSIS
    Reads the English alias of a location page from its frontmatter.

.DESCRIPTION
    Location pages list both the Russian title and the original English
    name in `aliases`. The English one names the illustration in
    `_img\locations`, so it is what New-Playlist needs to find the card
    background.

    Returns $null when the file has no frontmatter aliases or none of
    them looks like an English name.
#>
function Get-LocationAlias {
    param(
        [Parameter(Mandatory)]
        [string]$Path
    )

    $lines = [System.IO.File]::ReadAllLines($Path)
    if ($lines.Count -eq 0 -or $lines[0] -ne '---') { return $null }

    $inAliases = $false
    foreach ($line in $lines[1..($lines.Count - 1)]) {
        if ($line -eq '---') { break }

        if ($line -match '^aliases:\s*$') { $inAliases = $true; continue }
        # Список кончился, как только пошло следующее свойство: строка
        # начинается не с дефиса и не с отступа.
        if ($line -notmatch '^[\s-]') { $inAliases = $false }
        if (-not $inAliases) { continue }

        if ($line -match '^\s*-\s*"?([^"]+)"?\s*$') {
            $value = $matches[1].Trim()
            if ($value -match '^[\x20-\x7E]+$') { return $value }
        }
    }
    return $null
}
