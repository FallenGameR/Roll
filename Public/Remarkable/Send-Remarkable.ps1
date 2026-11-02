<#
.SYNOPSIS
    Загружает файлы на Remarkable, в корень или в указанную папку.

.DESCRIPTION
    Обёртка над `RCU-CLI --upload-doc` и `--upload-doc-to`. Каждый файл
    грузится отдельным вызовом, и каждый вызов заново подключается к
    планшету, так что пачка идёт секунд по десять на файл. Код выхода
    RCU врёт, поэтому в конце команда сверяет по SSH, что все файлы
    действительно появились в нужной папке.

    Планшет принимает PDF, EPUB, RMN, RMDOC, RM, TXT и MD. Markdown RCU
    переводит в родной текстовый документ Remarkable с разметкой.
    Загрузка RMN всегда создаёт копию с новым id, а не заменяет старый
    документ; то же с повторной загрузкой PDF - на планшете будет два.

    Подключение берётся из активного пресета RCU (Get-RemarkableConnection).

.PARAMETER Path
    Файлы для загрузки. Принимает конвейер, в том числе из Get-ChildItem.

.PARAMETER Collection
    Папка на планшете: полный путь через "/" (как Path в
    Get-RemarkableCollection), короткое имя или id. Если коротких имён
    несколько, команда остановится и перечислит пути. Без параметра
    файлы ложатся в корень.

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
            $match = @($all | Where-Object { $_.Id -eq $Collection -or $_.Path -eq $Collection })
            if (-not $match) { $match = @($all | Where-Object { $_.Name -eq $Collection }) }
            if ($match.Count -eq 0) {
                throw "На планшете нет папки '$Collection'. Список: Get-RemarkableCollection."
            }
            if ($match.Count -gt 1) {
                $paths = ($match | ForEach-Object Path) -join ', '
                throw "Папок '$Collection' несколько, укажи полный путь: $paths"
            }
            $collectionId = $match[0].Id
            $Collection = $match[0].Path
        }
        $target = if ($collectionId) { "папку '$Collection'" } else { 'корень' }
        $sent = [Collections.Generic.List[string]]::new()
        $started = (Get-Date).AddMinutes(-1)
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
            $sent.Add($file.BaseName)
            Write-Host "Отправлено: $($file.Name) -> $target"
        }
    }

    end {
        if (-not $sent.Count) { return }
        $parent = if ($collectionId) { $Collection } else { '' }
        $arrived = @(Get-RemarkableDocument | Where-Object {
            $_.Parent -eq $parent -and $_.Modified -ge $started
        } | ForEach-Object Name)
        $missing = @($sent | Where-Object { $_ -notin $arrived })
        if ($missing) {
            Write-Error "На планшете не появились: $($missing -join ', ')"
        } else {
            Write-Host "Проверено на планшете: $($sent.Count) шт."
        }
    }
}
