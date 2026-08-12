<#
.SYNOPSIS
    Known-word dictionary mapping individual Genre tag tokens (as found in
    the mp3 Genre id3 tag written by the annotation pipeline) to their
    category, so Get-Track can split the flat tag list into
    Intensity / Emotion / Scene / Game / Type buckets, plus a few
    pipeline meta-flags handled separately (see $script:RollGenreMetaTags).

.DESCRIPTION
    Derived from the original 6-category tagging scheme, then reshaped
    per user feedback: Place (location) and the old Scene (type of
    content) were merged into one broader Scene category, and Type was
    promoted from a single Effect-only flag to a multi-value bucket that
    also covers Vocals:
      - Intensity (energy):   Background, Tension, Combat, Crisis
      - Emotion:              Dread, Hostile, Haven, Tragic, Triumph,
                               Melancholy, Playful, Secrets, Divine,
                               Forbidden
      - Scene (place + type of content): Depths, Urban, Tavern, Lively,
                               Chase, Investigation, Anomaly
      - Game (source setting): Fantasy, Modern, SciFi
      - Type (production hint): Effect (soundboard/sfx), Vocals (has
                               singing/lyrics)

    Tags not covered by this dictionary (i.e. Intro, Outro, Unsorted) are
    pipeline meta-flags outside the category scheme and are handled
    separately, not through this token->category map. New tags not in
    either place end up in the Unmatched bucket instead of being dropped
    or throwing. Extend this table as new tags show up in the library
    (re-run Get-Track and check for non-empty Unmatched).
#>
$script:RollGenreTaxonomy = @{
    # Intensity: energy/pacing role of the track in a scene.
    'Background' = 'Intensity'
    'Tension'    = 'Intensity'
    'Combat'     = 'Intensity'
    'Crisis'     = 'Intensity'

    # Emotion: the emotional/narrative tone of the track.
    'Dread'      = 'Emotion'
    'Hostile'    = 'Emotion'
    'Haven'      = 'Emotion'
    'Tragic'     = 'Emotion'
    'Triumph'    = 'Emotion'
    'Melancholy' = 'Emotion'
    'Playful'    = 'Emotion'
    'Secrets'    = 'Emotion'
    'Divine'     = 'Emotion'
    'Forbidden'  = 'Emotion'

    # Scene: physical place and/or type of content the track fits.
    'Depths'        = 'Scene'
    'Urban'         = 'Scene'
    'Tavern'        = 'Scene'
    'Lively'        = 'Scene'
    'Chase'         = 'Scene'
    'Investigation' = 'Scene'
    'Anomaly'       = 'Scene'

    # Game: the source-material setting/era the track fits.
    'Fantasy' = 'Game'
    'Modern'  = 'Game'
    'SciFi'   = 'Game'

    # Type: production hint (soundboard effect vs. has vocals).
    'Effect' = 'Type'
    'Vocals' = 'Type'
}

<#
.SYNOPSIS
    Pipeline meta-flags outside the category scheme above: Intro/Outro
    (structural markers) and Unsorted (pipeline hasn't finished
    categorizing the track yet). Each becomes its own boolean property on
    the Roll.MusicTrack object instead of a category bucket.
#>
$script:RollGenreMetaTags = @('Intro', 'Outro', 'Unsorted')

<#
.SYNOPSIS
    Canonical category order used when serializing a Roll.MusicTrack's
    parsed Genre categories back into the self-describing
    "Category:value1,value2" tag string (see ConvertTo-GenreTagString).
    Meta and Unmatched are appended last, in that order, when non-empty.
#>
$script:RollGenreCategoryOrder = @('Intensity', 'Emotion', 'Scene', 'Game', 'Type')
