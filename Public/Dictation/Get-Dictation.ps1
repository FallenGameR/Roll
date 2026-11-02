<#
.SYNOPSIS
    Состояние голосовой диктовки: запущена ли, чем, и что в конце лога.

.PARAMETER Tail
    Сколько последних строк лога показать. По умолчанию 5.

.EXAMPLE
    Get-Dictation
.EXAMPLE
    Get-Dictation -Tail 30
#>
function Get-Dictation {
    [CmdletBinding()]
    param([int] $Tail = 5)

    $paths = Get-DictationPath
    $processes = @(Get-DictationProcess)
    $listener = Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort $paths.Port `
        -State Listen, Bound -ErrorAction SilentlyContinue | Select-Object -First 1
    $log = if (Test-Path -LiteralPath $paths.Log) {
        Get-Content -LiteralPath $paths.Log -Tail $Tail -Encoding UTF8
    }

    [pscustomobject] @{
        Running   = [bool] $processes
        Installed = Test-Path -LiteralPath $paths.PythonW
        PortOwner = if ($listener) { $listener.OwningProcess }
        Processes = $processes.ProcessId
        Script    = ($processes | Select-Object -First 1).CommandLine
        Log       = $paths.Log
        Recent    = $log
    }
}
