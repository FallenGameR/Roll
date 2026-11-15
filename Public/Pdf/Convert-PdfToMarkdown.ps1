<#
.SYNOPSIS
    Переводит PDF приключения в markdown для Обсидиана, с картинками.

.DESCRIPTION
    Обёртка над Tools\Pdf\pdf-to-markdown.py (Python 3.9 с pymupdf). Текст
    собирается по строкам страницы: две колонки, абзацы, заголовки по
    размеру шрифта и оглавлению PDF, жирный и курсив, буквицы. Колонтитулы,
    номера страниц, боковые закладки и водяные знаки отбрасываются как
    строки у краёв, повторяющиеся на многих страницах. Картинки, которые
    встречаются в книге один раз, вырезаются в img\ и вставляются ссылками
    ![[...]] на своё место. На каждой странице ставится метка %% p. N %%.

    Подбирать шрифты под вёрстку обычно не нужно. Если заголовком считается
    лишнее или проскакивает мусор, помогут -HeadingFont, -SkipFont и
    -SkipText: имена шрифтов книги видны в выводе команды и в Acrobat.

    Результат - сырой исходник для ручной вычитки, а не готовая страница
    кампании. Повторный запуск перезаписывает .md и картинки.

.PARAMETER Path
    PDF-файл.

.PARAMETER Destination
    Папка, куда лягут <Title>.md и img\. Создаётся при необходимости.

.PARAMETER Title
    Имя файла и заголовок в шапке. По умолчанию заголовок из свойств PDF,
    а если его нет - имя файла.

.PARAMETER Language
    Значение поля language в шапке. По умолчанию en.

.PARAMETER HeadingFont
    Регулярка по имени шрифта: заголовками считаются только крупные строки
    этим шрифтом.

.PARAMETER SkipFont
    Регулярка по имени шрифта: строки этим шрифтом выбрасываются.

.PARAMETER SkipText
    Регулярка по тексту строки: такие строки выбрасываются.

.EXAMPLE
    Convert-PdfToMarkdown ~\Downloads\wrath___glory_rain_of_mercy.pdf `
        '...\Warhammer\Приключения\Rain of Mercy\Исходник' -Title 'Rain of Mercy'
#>
function Convert-PdfToMarkdown {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory, Position = 0)]
        [string] $Path,

        [Parameter(Mandatory, Position = 1)]
        [string] $Destination,

        [string] $Title,

        [string] $Language = 'en',

        [string] $HeadingFont,

        [string] $SkipFont,

        [string] $SkipText
    )

    $ErrorActionPreference = 'Stop'
    $pdf = (Resolve-Path -LiteralPath $Path).Path
    $script = Join-Path $script:RollRoot 'Tools\Pdf\pdf-to-markdown.py'
    $out = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($Destination)

    $arguments = @($script, $pdf, '--out', $out, '--language', $Language)
    if ($Title) { $arguments += '--title', $Title }
    if ($HeadingFont) { $arguments += '--heading-font', $HeadingFont }
    if ($SkipFont) { $arguments += '--skip-font', $SkipFont }
    if ($SkipText) { $arguments += '--skip-text', $SkipText }

    $previous = $env:PYTHONIOENCODING
    try {
        $env:PYTHONIOENCODING = 'utf-8'
        Invoke-WithUtf8Console { & python @arguments }
        if ($LASTEXITCODE) { throw "pdf-to-markdown.py завершился с кодом $LASTEXITCODE" }
    }
    finally {
        $env:PYTHONIOENCODING = $previous
    }
}
