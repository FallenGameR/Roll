<#
.SYNOPSIS
    Подключает пульт Roll к Copilot: canvas с кнопками диктовки, плейлиста
    Winamp и бросков кубиков.

.DESCRIPTION
    Код пульта живёт в модуле, в Tools\Panel. Copilot ищет расширения в
    ~/.copilot/extensions, поэтому команда кладёт туда заглушку
    roll-panel\extension.mjs, которая импортирует настоящий файл из модуля.
    Путь к модулю в заглушке свой на каждом компьютере, поэтому после
    переноса модуля команду надо запустить заново.

    Пульт появится в сессиях, начатых после установки. Как править его на
    лету - Tools\Panel\README.md.

.EXAMPLE
    Install-RollPanel
#>
function Install-RollPanel {
    [CmdletBinding()]
    param()

    $ErrorActionPreference = 'Stop'
    $source = Join-Path $script:RollRoot 'Tools\Panel\extension.mjs'
    if (-not (Test-Path -LiteralPath $source)) { throw "Не найден $source" }

    $copilotHome = if ($env:COPILOT_HOME) { $env:COPILOT_HOME } else { Join-Path $HOME '.copilot' }
    $target = Join-Path $copilotHome 'extensions\roll-panel'
    if (Test-Path -LiteralPath $target) {
        Get-ChildItem -LiteralPath $target -Force | Remove-Item -Recurse -Force
    } else {
        New-Item -ItemType Directory -Force $target | Out-Null
    }

    $url = ([uri] (Resolve-Path -LiteralPath $source).Path).AbsoluteUri
    $stub = @"
// Заглушка: настоящий пульт лежит в модуле Roll. Создана Install-RollPanel.
await import("$url");
"@
    [System.IO.File]::WriteAllText((Join-Path $target 'extension.mjs'), $stub,
        [System.Text.UTF8Encoding]::new($false))

    Write-Host "Пульт подключён: $target -> $source"
    Write-Host 'Он появится в сессиях, начатых после этого.'
}
