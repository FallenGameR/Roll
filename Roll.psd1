@{
    RootModule        = 'Roll.psm1'
    ModuleVersion      = '1.0.0'
    FormatsToProcess   = @('Roll.Format.ps1xml')
    GUID               = '666b37cf-008f-44e2-b29d-33c8a29ac377'
    Author             = 'FallenGameR'
    Description        = 'RPG music library tools (YouTube download, ' +
                          'reorganize/tag, thumbnail resize, chapter ' +
                          'splitting, fzf export) plus a dice-roll utility.'
    PowerShellVersion  = '5.1'
    FunctionsToExport  = @(
        'Save-YouTubePlaylist',
        'Update-MusicLibrary',
        'Resize-MusicThumbnail',
        'Split-YouTubeVideoByChapter',
        'Get-Track',
        'Set-Track',
        'Set-TrackText',
        'Export-Track',
        'Import-Track',
        'Export-Playlist',
        'Import-WinampPlaylist',
        'Sync-WinampPlaylist',
        'Update-MusicGenreTag',
        'Start-WinampPlaylist',
        'Get-PngPrompt',
        'Get-ExeIcon',
        'Invoke-DiceRoll',
        'Install-Dictation',
        'Start-Dictation',
        'Stop-Dictation',
        'Get-Dictation'
    )
    AliasesToExport    = @('roll')
    CmdletsToExport    = @()
    VariablesToExport  = @()
}
