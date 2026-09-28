<#
.SYNOPSIS
    Splits a raw legacy-format Genre id3 tag string into its individual
    tag tokens.

.DESCRIPTION
    Legacy Genre strings are space-separated groups, where each group can
    itself contain "/"-separated alternative tags (e.g. "Background
    Dread/Secrets Modern/SciFi"). Both separators are flattened into one
    ordered, de-duplicated list of tokens.
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
    Buckets a flat list of legacy-format Genre tags into Intensity /
    Emotion / Scene / Game / Type arrays plus IsUnsorted/IsExcluded/IsDelete
    booleans, using the dictionaries in Get-GenreTaxonomy.ps1. Tags found
    in neither dictionary are returned under Unmatched instead of being
    silently dropped.
#>
function ConvertTo-GenreCategoryFromTokens {
    param(
        [Parameter(Mandatory)]
        [AllowEmptyCollection()]
        [string[]]$Tags
    )

    $buckets = [ordered]@{
        Intensity = [System.Collections.Generic.List[string]]::new()
        Emotion   = [System.Collections.Generic.List[string]]::new()
        Scene     = [System.Collections.Generic.List[string]]::new()
        Game      = [System.Collections.Generic.List[string]]::new()
        Type      = [System.Collections.Generic.List[string]]::new()
        Unmatched = [System.Collections.Generic.List[string]]::new()
    }
    $metaFlags = @{}

    foreach ($tag in $Tags) {
        $category = $script:RollGenreTaxonomy[$tag]
        if ($category) {
            $buckets[$category].Add($tag)
        }
        elseif ($script:RollGenreMetaTags -contains $tag) {
            $metaFlags[$tag] = $true
        }
        else {
            $buckets['Unmatched'].Add($tag)
        }
    }

    [PSCustomObject]@{
        Intensity  = $buckets.Intensity.ToArray()
        Emotion    = $buckets.Emotion.ToArray()
        Scene      = $buckets.Scene.ToArray()
        Game       = $buckets.Game.ToArray()
        Type       = $buckets.Type.ToArray()
        IsUnsorted = [bool]$metaFlags['Unsorted']
        IsExcluded = [bool]$metaFlags['Excluded']
        IsDelete   = [bool]$metaFlags['Delete']
        Unmatched  = $buckets.Unmatched.ToArray()
    }
}

<#
.SYNOPSIS
    Parses a self-describing "Category:value1,value2 Category:value3"
    Genre tag string (the non-ambiguous storage format) into a
    category-name -> values-list ordered map. Order of categories in the
    string is irrelevant; unrecognized category names are kept as-is so
    callers can decide how to handle them.
#>
function ConvertFrom-GenreTagString {
    param(
        [Parameter(Mandatory)]
        [AllowEmptyString()]
        [string]$Genre
    )

    $result = [ordered]@{}

    foreach ($chunk in ($Genre -split '\s+' | Where-Object { $_ })) {
        if ($chunk -match '^(?<cat>[A-Za-z]+):(?<vals>.+)$') {
            $cat = $Matches.cat
            if (-not $result.Contains($cat)) {
                $result[$cat] = [System.Collections.Generic.List[string]]::new()
            }
            foreach ($v in ($Matches.vals -split ',' | Where-Object { $_ })) {
                $result[$cat].Add($v)
            }
        }
    }

    $result
}

<#
.SYNOPSIS
    Buckets a raw Genre id3 tag string (either the legacy free-form
    format or the newer self-describing "Category:value" format) into
    Intensity / Emotion / Scene / Game / Type arrays plus
    IsUnsorted/IsExcluded/IsDelete booleans and an Unmatched array. This is
    the single entry point Get-Track and Update-MusicGenreTag should use
    for reading a Genre tag, regardless of which format a given file was
    written in.

.DESCRIPTION
    Format is auto-detected: a Genre string is treated as the new
    self-describing format if it contains a ":" (legacy tokens are plain
    words and never contain one), otherwise it's parsed as legacy
    free-form text via the known-tag dictionary.
#>
function ConvertTo-GenreCategory {
    param(
        [Parameter(Mandatory)]
        [AllowEmptyString()]
        [string]$Genre
    )

    if ($Genre -match ':') {
        $parsed = ConvertFrom-GenreTagString -Genre $Genre
        $meta = if ($parsed.Contains('Meta')) { $parsed['Meta'] } else { @() }
        $unmatchedNames = $parsed.Keys | Where-Object {
            $_ -notin @('Intensity', 'Emotion', 'Scene', 'Game', 'Type', 'Meta')
        }
        $unmatched = @(foreach ($name in $unmatchedNames) { $parsed[$name] })

        [PSCustomObject]@{
            Intensity  = @(if ($parsed.Contains('Intensity')) { $parsed['Intensity'] })
            Emotion    = @(if ($parsed.Contains('Emotion')) { $parsed['Emotion'] })
            Scene      = @(if ($parsed.Contains('Scene')) { $parsed['Scene'] })
            Game       = @(if ($parsed.Contains('Game')) { $parsed['Game'] })
            Type       = @(if ($parsed.Contains('Type')) { $parsed['Type'] })
            IsUnsorted = $meta -contains 'Unsorted'
            IsExcluded = $meta -contains 'Excluded'
            IsDelete   = $meta -contains 'Delete'
            Unmatched  = $unmatched
        }
    }
    else {
        $tags = Split-GenreTag -Genre $Genre
        ConvertTo-GenreCategoryFromTokens -Tags $tags
    }
}

<#
.SYNOPSIS
    Serializes a parsed Genre category object (as returned by
    ConvertTo-GenreCategory) back into the canonical self-describing
    "Category:value1,value2" tag string, in a fixed category order so
    repeated round-trips are stable/idempotent.
#>
function ConvertTo-GenreTagString {
    param(
        [Parameter(Mandatory)]
        [PSCustomObject]$Category
    )

    $parts = [System.Collections.Generic.List[string]]::new()

    foreach ($name in $script:RollGenreCategoryOrder) {
        $values = $Category.$name
        if ($values -and $values.Count -gt 0) {
            $parts.Add("$name`:$($values -join ',')")
        }
    }

    $meta = [System.Collections.Generic.List[string]]::new()
    if ($Category.IsUnsorted) { $meta.Add('Unsorted') }
    if ($Category.IsExcluded) { $meta.Add('Excluded') }
    if ($Category.IsDelete) { $meta.Add('Delete') }
    if ($meta.Count -gt 0) {
        $parts.Add("Meta:$($meta -join ',')")
    }

    if ($Category.Unmatched -and $Category.Unmatched.Count -gt 0) {
        $parts.Add("Unmatched:$($Category.Unmatched -join ',')")
    }

    $parts -join ' '
}

<#
.SYNOPSIS
    Splits the flattened Comment id3 tag into Situation / Description /
    Source parts.

.DESCRIPTION
    Comment format written by the annotation pipeline is:
      <situation> | Description: <description> | Evidence: <evidence>
      | Note: <note> | Source: <url>
    Only the situation is mandatory. Evidence records which sources the
    description was built from (acoustic measurement, YouTube comments,
    web credits) and Note carries caveats such as "the scene is not
    documented anywhere" - both were added when descriptions started
    being derived from real sources instead of guesswork, and both are
    optional. The trailing "| Source: <url>" segment is occasionally
    missing, in which case Source comes back as $null.
#>
function ConvertTo-CommentParts {
    param(
        [Parameter(Mandatory)]
        [AllowEmptyString()]
        [string]$Comment
    )

    $situation = $Comment
    $description = $null
    $evidence = $null
    $note = $null
    $source = $null

    $parts = $Comment -split '\s*\|\s*Description:\s*', 2
    if ($parts.Count -eq 2) {
        $situation = $parts[0].Trim()
        $rest = $parts[1]

        # Порядок разбора обратный порядку записи: сначала отрезаем
        # хвостовые секции, чтобы каждая предыдущая не утащила их в себя.
        # "Source:" не совпадает с "Sources:" — двоеточие обязано идти
        # сразу за словом, так что новые ключи старый разбор не ломают.
        $tail = $rest -split '\s*\|\s*Source:\s*', 2
        $rest = $tail[0]
        if ($tail.Count -eq 2) { $source = $tail[1].Trim() }

        $tail = $rest -split '\s*\|\s*Note:\s*', 2
        $rest = $tail[0]
        if ($tail.Count -eq 2) { $note = $tail[1].Trim() }

        $tail = $rest -split '\s*\|\s*Evidence:\s*', 2
        $rest = $tail[0]
        if ($tail.Count -eq 2) { $evidence = $tail[1].Trim() }

        $description = $rest.Trim()
    }

    [PSCustomObject]@{
        Situation   = $situation
        Description = $description
        Evidence    = $evidence
        Note        = $note
        Source      = $source
    }
}
