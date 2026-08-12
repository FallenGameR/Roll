<#
.SYNOPSIS
    Splits a raw Genre id3 tag string into its individual tag tokens.

.DESCRIPTION
    Genre strings are space-separated groups, where each group can itself
    contain "/"-separated alternative tags (e.g. "Background Dread/Secrets
    Modern/SciFi"). Both separators are flattened into one ordered,
    de-duplicated list of tokens.
#>
function Split-GenreTag {
    param(
        [Parameter(Mandatory)]
        [AllowEmptyString()]
        [string]$Genre
    )

    ($Genre -split '[ /]' | Where-Object { $_ }) | Select-Object -Unique
}

<#
.SYNOPSIS
    Buckets a flat list of Genre tags into Type / Mood / Setting /
    Modifier arrays using the known-tag dictionary in
    Get-GenreTaxonomy.ps1. Tags not found in the dictionary are returned
    under Unmatched instead of being silently dropped.
#>
function ConvertTo-GenreCategory {
    param(
        [Parameter(Mandatory)]
        [AllowEmptyCollection()]
        [string[]]$Tags
    )

    $buckets = [ordered]@{
        Type      = [System.Collections.Generic.List[string]]::new()
        Mood      = [System.Collections.Generic.List[string]]::new()
        Setting   = [System.Collections.Generic.List[string]]::new()
        Modifier  = [System.Collections.Generic.List[string]]::new()
        Unmatched = [System.Collections.Generic.List[string]]::new()
    }

    foreach ($tag in $Tags) {
        $category = $script:RollGenreTaxonomy[$tag]
        if ($category) {
            $buckets[$category].Add($tag)
        }
        else {
            $buckets['Unmatched'].Add($tag)
        }
    }

    [PSCustomObject]@{
        Type      = $buckets.Type.ToArray()
        Mood      = $buckets.Mood.ToArray()
        Setting   = $buckets.Setting.ToArray()
        Modifier  = $buckets.Modifier.ToArray()
        Unmatched = $buckets.Unmatched.ToArray()
    }
}

<#
.SYNOPSIS
    Splits the flattened Comment id3 tag into Situation / Description /
    Source parts.

.DESCRIPTION
    Comment format written by the annotation pipeline is:
      <situation> | Description: <description> | Source: <url>
    The trailing "| Source: <url>" segment is occasionally missing, in
    which case Source comes back as $null.
#>
function ConvertTo-CommentParts {
    param(
        [Parameter(Mandatory)]
        [AllowEmptyString()]
        [string]$Comment
    )

    $situation = $Comment
    $description = $null
    $source = $null

    $parts = $Comment -split '\s*\|\s*Description:\s*', 2
    if ($parts.Count -eq 2) {
        $situation = $parts[0].Trim()

        $rest = $parts[1] -split '\s*\|\s*Source:\s*', 2
        $description = $rest[0].Trim()
        if ($rest.Count -eq 2) {
            $source = $rest[1].Trim()
        }
    }

    [PSCustomObject]@{
        Situation   = $situation
        Description = $description
        Source      = $source
    }
}
