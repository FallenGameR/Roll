<#
.SYNOPSIS
    Открывает интерфейс простановки жанровых тегов треку, который играет
    в Winamp прямо сейчас.

.DESCRIPTION
    Поднимает локальный веб-интерфейс и открывает его в браузере. Страница
    спрашивает Winamp, что он играет, показывает его теги галочками и
    записывает изменения сразу по щелчку. Сменил трек в плеере - страница
    сама перерисовалась под новый.

    Писать можно и в тот файл, который звучит прямо сейчас: тег правится
    на месте, без подмены mp3, которая на занятом файле срывается.

    Значения берутся из таксономии модуля, строку genre собирает он же,
    так что формат остаётся единым с Set-Track.

.PARAMETER Port
    Порт локального сервера. По умолчанию 8731.

.PARAMETER NoBrowser
    Не открывать браузер, только напечатать адрес.

.EXAMPLE
    Start-MusicTagger
.EXAMPLE
    Start-MusicTagger -Port 9000 -NoBrowser
#>
function Start-MusicTagger {
    [CmdletBinding()]
    param(
        [int] $Port = 8731,
        [switch] $NoBrowser
    )

    $ErrorActionPreference = 'Stop'

    $script = Join-Path $script:RollRoot 'Tools\tagger.py'
    if (-not (Test-Path -LiteralPath $script)) {
        throw "Не найден $script"
    }

    if (-not (Get-Process -Name 'winamp' -ErrorAction SilentlyContinue)) {
        Write-Warning 'Winamp не запущен - страница будет ждать его.'
    }

    # ffprobe нужен скрипту для чтения тегов; путь ставится тот же, что
    # и у остальных команд модуля.
    $ffmpegDir = Split-Path (Find-WingetTool "Gyan.FFmpeg_*" "ffmpeg.exe")
    $env:FFPROBE = Join-Path $ffmpegDir 'ffprobe.exe'
    $env:PYTHONIOENCODING = 'utf-8'

    $arguments = @($script, '--port', $Port)
    if ($NoBrowser) { $arguments += '--no-browser' }

    & python @arguments
}
