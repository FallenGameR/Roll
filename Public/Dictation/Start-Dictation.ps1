<#
.SYNOPSIS
    Запускает голосовую диктовку: держишь кнопку Copilot, говоришь,
    отпускаешь, и текст печатается в позицию курсора.

.DESCRIPTION
    Поднимает Tools\Dictation\ptt.py фоновым процессом pythonw из venv, который
    ставит Install-Dictation, и ждёт в логе строку готовности. Распознаёт
    локальная faster-whisper на CPU, русский вперемешку с английским.

    Кнопка Copilot шлёт Win+Shift+F23. Скрипт глушит F23 низкоуровневым
    хуком клавиатуры, поэтому Пуск и Поиск не открываются. Любая другая
    клавиша, нажатая при зажатой кнопке, запись отменяет. Записи короче
    0.4 с отбрасываются.

    Писки: высокий - модель готова, средний - пошла запись, низкий -
    распознаётся.

    Экземпляр всегда один: скрипт занимает порт 127.0.0.1:47811, второй
    сразу выходит.

.PARAMETER Model
    Модель faster-whisper. По умолчанию turbo.

.PARAMETER Test
    Отладка: хук принимает синтетические нажатия и пишет события в лог.

.PARAMETER TimeoutSeconds
    Сколько ждать готовности модели. По умолчанию 180.

.EXAMPLE
    Start-Dictation
#>
function Start-Dictation {
    [CmdletBinding()]
    param(
        [string] $Model = 'turbo',
        [switch] $Test,
        [int] $TimeoutSeconds = 180
    )

    $ErrorActionPreference = 'Stop'
    $paths = Get-DictationPath

    if (-not (Test-Path -LiteralPath $paths.PythonW)) {
        throw 'Окружение не установлено, сначала Install-Dictation.'
    }
    if (Get-DictationProcess) {
        Write-Warning 'Диктовка уже запущена.'
        return Get-Dictation
    }

    New-Item -ItemType Directory -Force $paths.Home | Out-Null
    $offset = if (Test-Path -LiteralPath $paths.Log) { (Get-Item -LiteralPath $paths.Log).Length } else { 0 }

    $arguments = @("`"$($paths.Script)`"", $Model, '--log', "`"$($paths.Log)`"")
    if ($Test) { $arguments += '--test' }
    Start-Process -FilePath $paths.PythonW -ArgumentList $arguments -WindowStyle Hidden

    # Читаем только то, что дописано после запуска: старая строка Ready в
    # логе ничего не говорит о новом процессе.
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Seconds 1
        if (Test-Path -LiteralPath $paths.Log) {
            $stream = [System.IO.File]::Open($paths.Log, 'Open', 'Read', 'ReadWrite')
            try {
                [void] $stream.Seek($offset, 'Begin')
                $fresh = [System.IO.StreamReader]::new($stream, [System.Text.Encoding]::UTF8).ReadToEnd()
            } finally { $stream.Dispose() }
            if ($fresh -match 'Ready\. Hold the Copilot key') { return Get-Dictation }
            if ($fresh -match 'Another instance') { throw 'Порт 47811 занят другим экземпляром.' }
        }
        if (-not (Get-DictationProcess)) {
            throw "Процесс диктовки завершился до готовности, смотрите $($paths.Log)"
        }
    }
    throw "Модель не загрузилась за $TimeoutSeconds с, смотрите $($paths.Log)"
}
