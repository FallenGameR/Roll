<#
.SYNOPSIS
    Known-word dictionary mapping individual Genre tag tokens (as found in
    the mp3 Genre id3 tag written by the annotation pipeline) to their
    semantic category, so Get-MusicTrackList can split the flat tag list
    into Type / Mood / Setting / Modifier buckets.

.DESCRIPTION
    Genre tags are inherently a heuristic taxonomy, not a fixed schema, so
    new tags not yet in this dictionary end up in the Unmatched bucket
    instead of being dropped or throwing. Extend this table as new tags
    show up in the library (re-run Get-MusicTrackList and check for
    non-empty Unmatched).
#>
$script:RollGenreTaxonomy = @{
    # Type: what role the track plays in a scene.
    'Background' = 'Type'
    'Combat'     = 'Type'
    'Tension'    = 'Type'
    'Crisis'     = 'Type'
    'Effect'     = 'Type'

    # Mood: the emotional tone/flavor of the track.
    'Dread'      = 'Mood'
    'Hostile'    = 'Mood'
    'Haven'      = 'Mood'
    'Tragic'     = 'Mood'
    'Melancholy' = 'Mood'
    'Triumph'    = 'Mood'
    'Playful'    = 'Mood'
    'Lively'     = 'Mood'
    'Secrets'    = 'Mood'
    'Forbidden'  = 'Mood'
    'Divine'     = 'Mood'
    'Anomaly'    = 'Mood'

    # Setting: the world/genre backdrop the track fits.
    'Fantasy'    = 'Setting'
    'Modern'     = 'Setting'
    'SciFi'      = 'Setting'
    'Urban'      = 'Setting'
    'Tavern'     = 'Setting'
    'Depths'     = 'Setting'

    # Modifier: extra playback/usage hints.
    'Chase'         = 'Modifier'
    'Investigation' = 'Modifier'
    'Vocals'        = 'Modifier'
    'Intro'         = 'Modifier'
    'Outro'         = 'Modifier'
    'Unsorted'      = 'Modifier'
}
