<#
    Roll module - RPG music library management (yt-dlp download,
    reorganize/tag, thumbnail resize, chapter splitting, fzf export) plus
    the original dice-roll utility.
#>

$script:RollRoot = $PSScriptRoot

# Private helpers first (not exported), then public functions.
Get-ChildItem -Path "$PSScriptRoot\Private\*.ps1" -ErrorAction SilentlyContinue |
    ForEach-Object { . $_.FullName }

Get-ChildItem -Path "$PSScriptRoot\Public\*.ps1" -ErrorAction SilentlyContinue |
    ForEach-Object { . $_.FullName }

Export-ModuleMember -Function * -Alias *
