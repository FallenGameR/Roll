<#
    Roll module - RPG music library management (yt-dlp download,
    reorganize/tag, thumbnail resize, chapter splitting, fzf export) plus
    the original dice-roll utility.
#>

$script:RollRoot = $PSScriptRoot

# Модуль работает с кириллицей: Description/Situation/Evidence в тегах и
# русские имена файлов кампании. По умолчанию консоль Windows читает и
# печатает в OEM-кодировке (437/866/850), из-за чего вывод ffprobe в
# UTF-8 превращается в кракозябры ещё на этапе чтения, а вывести
# кириллицу она всё равно не может. Переключаем консоль на UTF-8 один
# раз при импорте — иначе Get-Track показывает мусор вместо текста.
if ([Console]::OutputEncoding.CodePage -ne 65001) {
    try { [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false) } catch { }
}

# Private helpers first (not exported), then public functions.
Get-ChildItem -Path "$PSScriptRoot\Private\*.ps1" -ErrorAction SilentlyContinue |
    ForEach-Object { . $_.FullName }

Get-ChildItem -Path "$PSScriptRoot\Public\*.ps1" -ErrorAction SilentlyContinue |
    ForEach-Object { . $_.FullName }

Export-ModuleMember -Function * -Alias *
