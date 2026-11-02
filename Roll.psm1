<#
    Roll module - инструменты волта настольных игр: фонотека и плейлисты
    Winamp, диктовка, кубики, картинки, пульт Copilot. Устройство модуля
    и правила, куда класть новый код, - в .github\copilot-instructions.md.
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

# Private helpers first (not exported), then public functions. Оба дерева
# разложены по темам (Music, Playlists, Dictation, Images, Dice, Panel), поэтому обход
# рекурсивный: новый подраздел подхватывается сам. Экспорт решает манифест:
# новую публичную функцию надо дописать в FunctionsToExport в Roll.psd1.
Get-ChildItem -Path "$PSScriptRoot\Private" -Filter '*.ps1' -Recurse -ErrorAction SilentlyContinue |
    ForEach-Object { . $_.FullName }

Get-ChildItem -Path "$PSScriptRoot\Public" -Filter '*.ps1' -Recurse -ErrorAction SilentlyContinue |
    ForEach-Object { . $_.FullName }

Export-ModuleMember -Function * -Alias *
