<#
.SYNOPSIS
    Значения ключей из шапки markdown-файла, без сборки YAML целиком.

.DESCRIPTION
    Возвращает словарь "ключ -> массив строк". Ключ бывает строкой
    (`music: "..."`) или списком (`music:` и ниже `  - "..."`), на
    выходе оба вида одинаково дают массив. Внешние кавычки снимаются.
    Ключа нет - значение пустой массив.

.PARAMETER Path
    Файл с шапкой.

.PARAMETER Key
    Какие ключи нужны.
#>
function Get-FrontMatterValue {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory, Position = 0)]
        [string] $Path,

        [Parameter(Mandatory)]
        [string[]] $Key
    )

    $result = @{}
    foreach ($k in $Key) { $result[$k] = @() }

    $lines = [System.IO.File]::ReadAllLines($Path)
    if (-not $lines.Count -or $lines[0].Trim() -ne '---') { return $result }

    $current = $null
    for ($i = 1; $i -lt $lines.Count; $i++) {
        $line = $lines[$i]
        if ($line.Trim() -eq '---') { break }

        if ($line -match '^([^\s:#][^:]*):\s*(.*)$') {
            $current = if ($Matches[1] -in $Key) { $Matches[1] } else { $null }
            $value = $Matches[2].Trim()
            if ($current -and $value) {
                $result[$current] += , (Remove-FrontMatterQuote $value)
            }
            continue
        }
        if ($current -and $line -match '^\s+-\s+(.+)$') {
            $result[$current] += , (Remove-FrontMatterQuote $Matches[1].Trim())
        }
    }
    return $result
}

function Remove-FrontMatterQuote([string] $Value) {
    if ($Value -match '^"(.*)"$' -or $Value -match "^'(.*)'$") {
        return $Matches[1]
    }
    return $Value
}
