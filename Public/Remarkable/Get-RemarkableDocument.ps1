<#
.SYNOPSIS
    Список документов на Remarkable: имя, папка, тип файла.

.DESCRIPTION
    Читает метаданные планшета по SSH (см. Get-RemarkableConnection).
    Документы в корзине скрыты, их показывает -IncludeTrash.

.PARAMETER Name
    Фильтр по имени документа, поддерживает подстановочные знаки.

.PARAMETER Collection
    Только документы из этой папки (полный путь, с подпапками).

.PARAMETER IncludeTrash
    Показать и документы из корзины.

.EXAMPLE
    Get-RemarkableDocument '*Фанделвер*'

.EXAMPLE
    Get-RemarkableDocument -Collection 'Coriolis'
#>
function Get-RemarkableDocument {
    [CmdletBinding()]
    param(
        [Parameter(Position = 0)]
        [string]$Name = '*',

        [string]$Collection,

        [switch]$IncludeTrash
    )

    Get-RemarkableItem |
        Where-Object { -not $_.Folder -and ($IncludeTrash -or -not $_.Trashed) } |
        Where-Object { $_.Name -like $Name } |
        Where-Object { -not $Collection -or $_.Parent -eq $Collection -or $_.Parent -like "$Collection/*" } |
        Sort-Object Parent, Name |
        Select-Object Name, Parent, FileType, Modified, Id
}
