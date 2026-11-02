<#
.SYNOPSIS
    Загружает файлы на Remarkable, в корень или в указанную папку.

.DESCRIPTION
    Обёртка над `RCU-CLI --upload-doc` и `--upload-doc-to`. Каждый файл
    грузится отдельным вызовом, и каждый вызов заново подключается к
    планшету, так что пачка идёт по несколько секунд на файл.

    Планшет принимает PDF, EPUB, RMN, RMDOC, RM, TXT и MD. Markdown RCU
    переводит в родной текстовый документ Remarkable с разметкой.
    Загрузка RMN всегда создаёт копию с новым id, а не заменяет старый
    документ; то же с повторной загрузкой PDF - на планшете будет два.

    Подключение берётся из последнего пресета RCU (см. Open-Remarkable).

.PARAMETER Path
    Файлы для загрузки. Принимает конвейер, в том числе из Get-ChildItem.

.PARAMETER Collection
    Папка на планшете: имя (как в Get-RemarkableCollection) или id. Если
    папок с таким именем несколько, команда остановится и попросит id.
    Без параметра файлы ложатся в корень.

.EXAMPLE
    Send-Remarkable '.\Раздатка приёмов.pdf'

.EXAMPLE
    Get-ChildItem .\Levelup\*.pdf | Send-Remarkable -Collection 'Фанделвер'
#>
function Send-Remarkable {
    [CmdletBinding(SupportsShouldProcess)]
    param(
        [Parameter(Mandatory, Position = 0, ValueFromPipeline, ValueFromPipelineByPropertyName)]
        [Alias('FullName')]
        [string[]]$Path,

        [string]$Collection
    )

    begin {
        $supported = '.pdf', '.epub', '.rmn', '.rmdoc', '.rm', '.txt', '.md'
        $collectionId = $null
        if ($Collection) {
            $all = @(Get-RemarkableCollection)
            $match = @($all | Where-Object { $_.Id -eq $Collection })
            if (-not $match) { $match = @($all | Where-Object { $_.Name -eq $Collection }) }
            if ($match.Count -eq 0) {
                throw "На планшете нет папки '$Collection'. Список: Get-RemarkableCollection."
            }
            if ($match.Count -gt 1) {
                $ids = ($match | ForEach-Object { "$($_.Id) ($($_.Modified))" }) -join ', '
                throw "Папок '$Collection' несколько, укажи id: $ids"
            }
            $collectionId = $match[0].Id
        }
        $target = if ($collectionId) { "папку '$Collection'" } else { 'корень' }
    }

    process {
        foreach ($item in $Path) {
            $file = Get-Item -LiteralPath $item -ErrorAction Stop
            if ($file.PSIsContainer) {
                Write-Warning "Пропускаю папку $($file.FullName): загружаются только файлы."
                continue
            }
            if ($file.Extension.ToLowerInvariant() -notin $supported) {
                Write-Warning "Пропускаю $($file.Name): Remarkable не принимает $($file.Extension)."
                continue
            }
            if (-not $PSCmdlet.ShouldProcess($file.FullName, "Загрузить на Remarkable в $target")) {
                continue
            }

            $arguments = if ($collectionId) {
                '--upload-doc-to', $file.FullName, $collectionId
            } else {
                '--upload-doc', $file.FullName
            }
            Invoke-RemarkableCli $arguments | Out-Null
            Write-Host "Загружено: $($file.Name) -> $target"
        }
    }
}
