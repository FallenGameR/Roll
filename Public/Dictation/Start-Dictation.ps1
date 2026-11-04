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

    Звуки: высокий писк - модель готова, Speech On из C:\Windows\Media -
    пошла запись, Speech Off - запись кончилась, идёт распознавание.

    Экземпляр всегда один: скрипт занимает порт 127.0.0.1:47811, второй
    сразу выходит.

.PARAMETER Model
    Модель faster-whisper. По умолчанию turbo.

.PARAMETER Encoder
    Где считать кодировщик: gpu - OpenVINO на видеокарте, npu - на NPU, off -
    CTranslate2 на процессоре, как было до ноября 2026. Это откат, если гибрид
    начнёт ошибаться. Выбор запоминается в encoder.txt рядом с логом, и
    следующие запуски без параметра, в том числе с пульта, берут его оттуда.
    Если OpenVINO не поднялся, ptt.py сам переходит на процессор и пишет
    причину в лог. На npu первая сборка идёт около 2.5 минут, и для неё
    стоит поднять -TimeoutSeconds.

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
        [ValidateSet('gpu', 'npu', 'off')]
        [string] $Encoder,
        [switch] $Test,
        [int] $TimeoutSeconds = 180
    )

    $ErrorActionPreference = 'Stop'
    $paths = Get-DictationPath

    if (-not (Test-Path -LiteralPath $paths.PythonW)) {
        throw 'Окружение не установлено, сначала Install-Dictation.'
    }
    New-Item -ItemType Directory -Force $paths.Home | Out-Null
    $chosen = [bool] $Encoder
    if ($Encoder) {
        Set-Content -LiteralPath $paths.Encoder -Value $Encoder -Encoding ascii
    } elseif (Test-Path -LiteralPath $paths.Encoder) {
        $Encoder = (Get-Content -LiteralPath $paths.Encoder -TotalCount 1).Trim()
    }
    if ($Encoder -notin 'gpu', 'npu', 'off') { $Encoder = 'gpu' }

    if (Get-DictationProcess) {
        if ($chosen) {
            Write-Warning "Диктовка уже запущена. Кодировщик $Encoder записан и включится после Stop-Dictation и нового запуска."
        } else {
            Write-Warning 'Диктовка уже запущена.'
        }
        return Get-Dictation
    }

    $offset = if (Test-Path -LiteralPath $paths.Log) { (Get-Item -LiteralPath $paths.Log).Length } else { 0 }

    $arguments = @("`"$($paths.Script)`"", $Model, '--log', "`"$($paths.Log)`"", '--encoder', $Encoder)
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
