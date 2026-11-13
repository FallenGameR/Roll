<#
.SYNOPSIS
    Подключает к Copilot canvas модуля Roll: пульт (диктовка, плейлист
    Winamp, кубики) и «Правку текста».

.DESCRIPTION
    Код canvas живёт в модуле, в Tools\Panel и Tools\Editor. Copilot ищет
    расширения в ~/.copilot/extensions, поэтому команда кладёт туда
    заглушки roll-panel\extension.mjs и roll-editor\extension.mjs, которые
    импортируют настоящие файлы из модуля.
    Путь к модулю в заглушке свой на каждом компьютере, поэтому после
    переноса модуля команду надо запустить заново.

    Canvas появятся в сессиях, начатых после установки. Как править их на
    лету - README.md в Tools\Panel и Tools\Editor.

.EXAMPLE
    Install-RollPanel
#>
function Install-RollPanel {
    [CmdletBinding()]
    param()

    $ErrorActionPreference = 'Stop'
    $copilotHome = if ($env:COPILOT_HOME) { $env:COPILOT_HOME } else { Join-Path $HOME '.copilot' }

    $canvases = [ordered] @{
        'roll-panel'  = 'Tools\Panel\extension.mjs'
        'roll-editor' = 'Tools\Editor\extension.mjs'
    }
    foreach ($name in $canvases.Keys) {
        $source = Join-Path $script:RollRoot $canvases[$name]
        if (-not (Test-Path -LiteralPath $source)) { throw "Не найден $source" }

        $target = Join-Path $copilotHome "extensions\$name"
        if (Test-Path -LiteralPath $target) {
            Get-ChildItem -LiteralPath $target -Force | Remove-Item -Recurse -Force
        } else {
            New-Item -ItemType Directory -Force $target | Out-Null
        }

        $url = ([uri] (Resolve-Path -LiteralPath $source).Path).AbsoluteUri
        $stub = @"
// Заглушка: настоящий canvas лежит в модуле Roll. Создана Install-RollPanel.
await import("$url");
"@
        [System.IO.File]::WriteAllText((Join-Path $target 'extension.mjs'), $stub,
            [System.Text.UTF8Encoding]::new($false))
        Write-Host "Подключён: $target -> $source"
    }

    Write-Host 'Canvas появятся в сессиях, начатых после этого.'
}
