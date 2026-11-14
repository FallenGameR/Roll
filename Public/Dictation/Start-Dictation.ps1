<#
.SYNOPSIS
    Запускает голосовую диктовку: держишь кнопку Copilot, Menu или правую Win,
    говоришь, отпускаешь, и текст печатается в позицию курсора.

.DESCRIPTION
    Поднимает Tools\Dictation\ptt.py фоновым процессом pythonw из venv, который
    ставит Install-Dictation, и ждёт в логе строку готовности. Распознаёт
    локальная faster-whisper, русский вперемешку с английским: на карте
    NVIDIA целиком на CUDA, иначе на процессоре с кодировщиком в OpenVINO.

    Кнопка Copilot шлёт Win+Shift+F23. Скрипт глушит F23 низкоуровневым
    хуком клавиатуры, поэтому Пуск и Поиск не открываются. На клавиатуре
    без кнопки Copilot на её месте обычно стоит Menu (контекстное меню):
    она работает так же, и меню, пока диктовка запущена, не открывается.
    Где нет и Menu, кнопкой служит правая Win: пока диктовка запущена, она
    не открывает Пуск и не работает в сочетаниях, Win остаётся левая.
    Любая другая
    клавиша, нажатая при зажатой кнопке, запись отменяет. Записи короче
    0.4 с отбрасываются.

    Звуки: высокий писк - модель готова, Speech On из C:\Windows\Media -
    пошла запись, Speech Off - запись кончилась, идёт распознавание.
    Speech On и Off по умолчанию играются в десять раз тише системных
    (--chime-volume 0.1 у ptt.py): тихие копии лежат в chimes рядом с
    логом. На машине, где этого мало, громкость задаёт -ChimeVolume.

    Экземпляр всегда один: скрипт занимает порт 127.0.0.1:47811, второй
    сразу выходит.

.PARAMETER Model
    Модель faster-whisper. По умолчанию turbo.

.PARAMETER Encoder
    Где считать Whisper: auto - выбрать по железу, cuda - всю модель на карте
    NVIDIA, gpu - кодировщик в OpenVINO на видеокарте Intel, npu - на NPU,
    off - CTranslate2 на процессоре. auto берёт cuda, если CTranslate2 видит
    карту NVIDIA и Install-Dictation поставил к ней cuBLAS и cuDNN, иначе gpu
    при видеокарте Intel Arc (Core Ultra), иначе npu, если он есть, иначе off:
    старая графика UHD считает кодировщик медленнее процессора. По умолчанию
    auto. Ручной выбор запоминается в encoder.txt рядом с логом, и следующие
    запуски без параметра, в том числе с пульта, берут его оттуда; -Encoder
    auto возвращает автоматический выбор. Что выбрано, видно в пульте и в
    логе строкой "Encoder auto".
    Если CUDA или OpenVINO не поднялись или упали посреди работы, ptt.py сам
    переходит на процессор и пишет причину в лог. На npu первая сборка идёт
    около 2.5 минут, и для неё стоит поднять -TimeoutSeconds.

.PARAMETER ChimeVolume
    Громкость звуков начала и конца записи, доля от системных: 1 - как в
    Windows, 0 - без звука. Запоминается в chime-volume.txt рядом с логом,
    то есть в %LOCALAPPDATA% этой машины, и следующие запуски, в том числе
    с пульта, берут её оттуда. Без файла - 0.1. Тот же файл пишет ползунок
    громкости в пульте, а ptt.py перечитывает его перед каждым звуком, поэтому
    новая громкость слышна сразу, без перезапуска.

.PARAMETER Microphone
    Часть имени микрофона, например Blue: запись идёт с первого микрофона, в
    имени которого она есть, без учёта регистра. Если такого сейчас нет, то
    с микрофона Windows по умолчанию, а когда нужный подключат, диктовка
    перейдёт на него сама в течение 3 с. Запоминается в microphone.txt
    рядом с логом, и следующие запуски, в том числе с пульта, берут его
    оттуда. -Microphone '' возвращает микрофон Windows по умолчанию. Имена
    микрофонов - в "Параметры - Система - Звук - Ввод".

.PARAMETER Test
    Отладка: хук принимает синтетические нажатия и пишет события в лог.

.PARAMETER TimeoutSeconds
    Сколько ждать готовности модели. По умолчанию 180.

.EXAMPLE
    Start-Dictation

.EXAMPLE
    Stop-Dictation; Start-Dictation -ChimeVolume 1

    Звуки записи на полную системную громкость на этой машине.

.EXAMPLE
    Stop-Dictation; Start-Dictation -Microphone Blue

    Писать с Blue Snowball, даже если Windows считает основным другой микрофон.#>
function Start-Dictation {
    [CmdletBinding()]
    param(
        [string] $Model = 'turbo',
        [ValidateSet('auto', 'cuda', 'gpu', 'npu', 'off')]
        [string] $Encoder,
        [ValidateRange(0, 1)]
        [double] $ChimeVolume = -1,
        [string] $Microphone,
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
    if ($Encoder -notin 'auto', 'cuda', 'gpu', 'npu', 'off') { $Encoder = 'auto' }

    $culture = [Globalization.CultureInfo]::InvariantCulture

    # -Microphone '' стирает выбор и возвращает микрофон Windows по умолчанию.
    $micChosen = $PSBoundParameters.ContainsKey('Microphone')
    if ($micChosen) {
        $Microphone = $Microphone.Trim()
        if ($Microphone) {
            Set-Content -LiteralPath $paths.Microphone -Value $Microphone -Encoding utf8
        } else {
            Remove-Item -LiteralPath $paths.Microphone -ErrorAction SilentlyContinue
        }
    } elseif (Test-Path -LiteralPath $paths.Microphone) {
        $Microphone = (Get-Content -LiteralPath $paths.Microphone -TotalCount 1 -Encoding utf8).Trim()
    }
    $volumeChosen = $PSBoundParameters.ContainsKey('ChimeVolume')
    if ($volumeChosen) {
        Set-Content -LiteralPath $paths.ChimeVolume -Value $ChimeVolume.ToString($culture) -Encoding ascii
    } else {
        $ChimeVolume = 0.1
        if (Test-Path -LiteralPath $paths.ChimeVolume) {
            $saved = 0.0
            $text = (Get-Content -LiteralPath $paths.ChimeVolume -TotalCount 1).Trim()
            if ([double]::TryParse($text, 'Float', $culture, [ref] $saved) -and $saved -ge 0 -and $saved -le 1) {
                $ChimeVolume = $saved
            }
        }
    }

    if (Get-DictationProcess) {
        if ($chosen -or $volumeChosen -or $micChosen) {
            Write-Warning 'Диктовка уже запущена. Новые настройки записаны и включатся после Stop-Dictation и нового запуска.'
        } else {
            Write-Warning 'Диктовка уже запущена.'
        }
        return Get-Dictation
    }

    $offset = if (Test-Path -LiteralPath $paths.Log) { (Get-Item -LiteralPath $paths.Log).Length } else { 0 }

    # Потоков декодера по числу физических ядер: на i9-10900K 20 логических
    # потоков медленнее 10 физических на 20%.
    $cores = (Get-CimInstance Win32_Processor | Measure-Object NumberOfCores -Sum).Sum
    $arguments = @("`"$($paths.Script)`"", $Model, '--log', "`"$($paths.Log)`"", '--encoder', $Encoder,
        '--chime-volume', $ChimeVolume.ToString($culture))
    if ($cores) { $arguments += '--threads', $cores }
    if ($Test) { $arguments += '--test' }
    if ($Microphone) { $arguments += '--mic', "`"$Microphone`"" }
    # Рабочая папка - домашняя папка диктовки: драйвер Intel при сборке
    # кодировщика под GPU кладёт в текущую папку kernel.errors.txt.
    Start-Process -FilePath $paths.PythonW -ArgumentList $arguments -WindowStyle Hidden -WorkingDirectory $paths.Home

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
            if ($fresh -match 'Ready\. Hold the Copilot') { return Get-Dictation }
            if ($fresh -match 'Another instance') { throw 'Порт 47811 занят другим экземпляром.' }
        }
        if (-not (Get-DictationProcess)) {
            throw "Процесс диктовки завершился до готовности, смотрите $($paths.Log)"
        }
    }
    throw "Модель не загрузилась за $TimeoutSeconds с, смотрите $($paths.Log)"
}
