<#
.SYNOPSIS
    Список папок на Remarkable с полными путями.

.DESCRIPTION
    Читает метаданные планшета по SSH (см. Get-RemarkableConnection).
    Path - полный путь через "/", по нему Send-Remarkable находит папку,
    даже если коротких имён одинаковых несколько. Папки в корзине
    скрыты, их показывает -IncludeTrash.

.PARAMETER Name
    Фильтр по имени или по полному пути, поддерживает подстановочные знаки.

.PARAMETER IncludeTrash
    Показать и папки из корзины.

.EXAMPLE
    Get-RemarkableCollection

.EXAMPLE
    Get-RemarkableCollection 'Projects/*'
#>
function Get-RemarkableCollection {
    [CmdletBinding()]
    param(
        [Parameter(Position = 0)]
        [string]$Name = '*',

        [switch]$IncludeTrash
    )

    Get-RemarkableItem |
        Where-Object { $_.Folder -and ($IncludeTrash -or -not $_.Trashed) } |
        Where-Object { $_.Name -like $Name -or $_.Path -like $Name } |
        Sort-Object Path |
        Select-Object Path, Name, Modified, Id
}
