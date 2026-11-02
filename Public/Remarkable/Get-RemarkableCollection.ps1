<#
.SYNOPSIS
    Список папок (collections) на Remarkable.

.DESCRIPTION
    Обёртка над `RCU-CLI --list-collections`. Id нужен для загрузки в
    конкретную папку; Send-Remarkable умеет искать папку и по имени.

.PARAMETER Name
    Фильтр по имени папки, поддерживает подстановочные знаки.

.EXAMPLE
    Get-RemarkableCollection

.EXAMPLE
    Get-RemarkableCollection 'Фанд*'
#>
function Get-RemarkableCollection {
    [CmdletBinding()]
    param(
        [Parameter(Position = 0)]
        [string]$Name = '*'
    )

    Invoke-RemarkableCli '--list-collections' |
        Where-Object { $_ -match "`t" } |
        ForEach-Object {
            $field = $_ -split "`t"
            [pscustomobject]@{
                Id       = $field[0]
                Name     = $field[1]
                Modified = $field[2]
            }
        } |
        Where-Object { $_.Name -like $Name }
}
