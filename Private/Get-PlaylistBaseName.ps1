<#
.SYNOPSIS
    Имя, под которым плейлисты файла кампании видны в плеере.

.DESCRIPTION
    По умолчанию берётся имя файла, а всему, что не страница локации,
    приписывается точка в начале: в дереве плеера это уводит сквозные
    подборки наверх, отдельно от мест на карте.

    Свойство `playlist` в шапке перебивает оба правила разом и задаёт
    имя целиком, вместе с точкой. Нужно оно там, где имя файла длиннее,
    чем помещается в дерево плеера: "Погоня Правила" превращается в
    ".Погоня".

.PARAMETER Path
    Файл кампании.
#>
function Get-PlaylistBaseName {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory, Position = 0)]
        [string] $Path
    )

    $full = (Resolve-Path -LiteralPath $Path).Path
    $lines = [System.IO.File]::ReadAllLines($full)

    # Шапка читается на месте и только ради одного ключа: пересобирать
    # её нельзя, незнакомые поля от этого пропадают молча.
    if ($lines.Count -and $lines[0].Trim() -eq '---') {
        for ($i = 1; $i -lt $lines.Count; $i++) {
            if ($lines[$i].Trim() -eq '---') { break }
            if ($lines[$i] -match '^playlist:\s*(.+?)\s*$') {
                $value = $Matches[1].Trim()
                if ($value -match '^"(.*)"$' -or $value -match "^'(.*)'$") {
                    $value = $Matches[1]
                }
                if ($value) { return $value }
                break
            }
        }
    }

    $name = [System.IO.Path]::GetFileNameWithoutExtension($full)
    if ($full -notmatch '\\Adventure\\Locations\\') { $name = ".$name" }
    return $name
}
