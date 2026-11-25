<#
.SYNOPSIS
    Каталог наших надстроек Обсидиана: самописные плагины и сниппеты из
    папки Obsidian модуля Roll.

.DESCRIPTION
    Надстройки разложены по наборам: base годится любому волту, dnd -
    волту с Initiative Tracker и Fantasy Statblocks, phandelver завязан на
    страницы кампании Рудники Фанделвера. Источник правды - папка
    Obsidian модуля и её catalog.json, в волты их ставит
    Install-ObsidianKit.

    С -Vault показывает ещё, что из каталога уже стоит в волте и включено
    ли: State - нет, совпадает с Roll или отличается; Enabled - включено ли
    в community-plugins.json или enabledCssSnippets.

.PARAMETER Kit
    Только эти наборы. По умолчанию все.

.PARAMETER Vault
    Папка волта (та, в которой лежит .obsidian).

.EXAMPLE
    Get-ObsidianKit | Format-Table Kit, Kind, Id, Name

.EXAMPLE
    Get-ObsidianKit -Vault 'C:\vaults\Рудники Фанделвера' | Format-Table Kit, Id, State, Enabled
#>
function Get-ObsidianKit {
    [CmdletBinding()]
    param(
        [ValidateSet('base', 'dnd', 'phandelver', 'map', 'travel')]
        [string[]] $Kit,
        [string] $Vault
    )

    $items = Get-RollObsidianCatalog
    if ($Kit) { $items = $items | Where-Object { $Kit -contains $_.Kit } }

    if (-not $Vault) { return $items | Select-Object Kit, Kind, Id, Name, Needs, Description }

    $obsidianDir = Join-Path $Vault '.obsidian'
    if (-not (Test-Path -LiteralPath $obsidianDir)) { throw "Не волт Обсидиана: нет $obsidianDir" }
    $plugins = @(Read-RollObsidianJson (Join-Path $obsidianDir 'community-plugins.json'))
    $snippets = @((Read-RollObsidianJson (Join-Path $obsidianDir 'appearance.json')).enabledCssSnippets)

    foreach ($item in $items) {
        $enabled = if ($item.Kind -eq 'plugin') { $plugins -contains $item.Id } else { $snippets -contains $item.Id }
        [pscustomobject] @{
            Kit     = $item.Kit
            Kind    = $item.Kind
            Id      = $item.Id
            Name    = $item.Name
            State   = Get-RollObsidianState $item $obsidianDir
            Enabled = $enabled
        }
    }
}
