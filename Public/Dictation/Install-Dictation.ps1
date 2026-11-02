<#
.SYNOPSIS
    Ставит окружение голосовой диктовки: venv с faster-whisper.

.DESCRIPTION
    Создаёт venv в %LOCALAPPDATA%\Roll\dictation\venv и ставит туда пакеты из
    Tools\Dictation\requirements.txt. Повторный запуск только доставляет
    пакеты, -Force пересоздаёт venv с нуля.

    Модель whisper отдельно не качается: faster-whisper сам кладёт её в кеш
    Hugging Face профиля при первом запуске Start-Dictation.

.PARAMETER Python
    Базовый интерпретатор. По умолчанию Python 3.9 через py launcher, на нём
    диктовка проверена.

.PARAMETER Force
    Удалить существующий venv и собрать заново.

.EXAMPLE
    Install-Dictation
#>
function Install-Dictation {
    [CmdletBinding()]
    param(
        [string] $Python,
        [switch] $Force
    )

    $ErrorActionPreference = 'Stop'
    $paths = Get-DictationPath

    if (-not $Python) {
        $Python = (& py -3.9 -c 'import sys; print(sys.executable)' 2>$null)
        if (-not $Python) { throw 'Не найден Python 3.9 (py -3.9). Укажите -Python.' }
    }

    if ($Force -and (Test-Path -LiteralPath $paths.Venv)) {
        if (Get-DictationProcess) { throw 'Диктовка запущена, сначала Stop-Dictation.' }
        Remove-Item -LiteralPath $paths.Venv -Recurse -Force
    }

    if (-not (Test-Path -LiteralPath $paths.Python)) {
        New-Item -ItemType Directory -Force $paths.Home | Out-Null
        & $Python -m venv $paths.Venv
        if ($LASTEXITCODE) { throw "venv не создан: $($paths.Venv)" }
    }

    & $paths.Python -m pip install --quiet --upgrade pip
    & $paths.Python -m pip install --quiet -r $paths.Requirements
    if ($LASTEXITCODE) { throw 'pip install не прошёл.' }

    Write-Host "Диктовка установлена: $($paths.Venv)"
}
