<#
.SYNOPSIS
    Internal helper: пути голосовой диктовки.

.DESCRIPTION
    Скрипт лежит в репозитории, а venv и лог - в %LOCALAPPDATA%\Roll\dictation.
    Roll живёт в OneDrive, и тысячи файлов venv там синхронизировать
    незачем: OneDrive подменяет их облачными заглушками, а Python на
    таких файлах ломается.
#>
function Get-DictationPath {
    $dir = Join-Path $env:LOCALAPPDATA 'Roll\dictation'
    [pscustomobject] @{
        Home         = $dir
        Venv         = Join-Path $dir 'venv'
        Python       = Join-Path $dir 'venv\Scripts\python.exe'
        PythonW      = Join-Path $dir 'venv\Scripts\pythonw.exe'
        Log          = Join-Path $dir 'dictation.log'
        Encoder      = Join-Path $dir 'encoder.txt'
        ChimeVolume  = Join-Path $dir 'chime-volume.txt'
        Script       = Join-Path $script:RollRoot 'Tools\Dictation\ptt.py'
        Requirements = Join-Path $script:RollRoot 'Tools\Dictation\requirements.txt'
        Port         = 47811
    }
}

<#
.SYNOPSIS
    Internal helper: процессы диктовки, то есть python и pythonw, у которых
    в командной строке есть ptt.py.
#>
function Get-DictationProcess {
    Get-CimInstance Win32_Process -Filter "Name like 'python%'" |
        Where-Object { $_.CommandLine -match 'ptt\.py' }
}
