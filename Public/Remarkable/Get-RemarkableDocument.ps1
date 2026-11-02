<#
.SYNOPSIS
    Список документов на Remarkable.

.DESCRIPTION
    Обёртка над `RCU-CLI --list-documents`: id, имя, дата изменения и тип
    файла. Папку, в которой лежит документ, CLI не сообщает.

.PARAMETER Name
    Фильтр по имени документа, поддерживает подстановочные знаки.

.EXAMPLE
    Get-RemarkableDocument '*Фанделвер*'
#>
function Get-RemarkableDocument {
    [CmdletBinding()]
    param(
        [Parameter(Position = 0)]
        [string]$Name = '*'
    )

    Invoke-RemarkableCli '--list-documents' |
        Where-Object { $_ -match "`t" } |
        ForEach-Object {
            $field = $_ -split "`t"
            [pscustomobject]@{
                Id       = $field[0]
                Name     = $field[1]
                Modified = $field[2]
                Type     = $field[3]
            }
        } |
        Where-Object { $_.Name -like $Name }
}
