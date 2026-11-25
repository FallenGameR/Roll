<#
.SYNOPSIS
    Ставит наши надстройки Обсидиана в волт: самописные плагины и сниппеты
    из папки Obsidian модуля Roll.

.DESCRIPTION
    Копирует выбранные наборы в <волт>\.obsidian и включает их: плагины
    строкой в community-plugins.json, сниппеты в enabledCssSnippets файла
    appearance.json. Уже включённое и чужое не трогает.

    Источник правды - Roll\Obsidian. Если файл в волте отличается от Roll и
    при этом новее, значит, его правили прямо в волте: такая надстройка
    пропускается с предупреждением, чтобы установка не затёрла работу.
    Сначала перенеси правку в Roll, потом ставь заново; -Force ставит
    поверх.

    data.json плагинов не переносится: это настройки и состояние в
    конкретном волте.

    Открытый Обсидиан держит настройки в памяти и при выходе перезаписывает
    community-plugins.json и appearance.json. Поэтому при запущенном
    Обсидиане файлы копируются, а включение не делается: команда печатает,
    что включить руками в Settings, или ставь заново при закрытом
    Обсидиане. Новый main.js уже включённого плагина Обсидиан подхватывает
    только после перезагрузки (Ctrl+R) или выключения и включения плагина.

    Чужие плагины, от которых зависят наши (Initiative Tracker, Fantasy
    Statblocks и другие), команда не ставит, а только предупреждает, что их
    в волте нет.

.PARAMETER Vault
    Папка волта (та, в которой лежит .obsidian).

.PARAMETER Kit
    Наборы: base - любой волт, dnd - волт с Initiative Tracker и Fantasy
    Statblocks, phandelver - кампания Рудники Фанделвера. По умолчанию base.

.PARAMETER Name
    Отдельные плагины или сниппеты по id, в дополнение к наборам.

.PARAMETER Force
    Ставить поверх файлов, которые в волте новее, чем в Roll.

.EXAMPLE
    Install-ObsidianKit -Vault 'C:\vaults\Новый волт'

.EXAMPLE
    Install-ObsidianKit -Vault 'C:\vaults\Рудники Фанделвера' -Kit base, dnd, phandelver -WhatIf
#>
function Install-ObsidianKit {
    [CmdletBinding(SupportsShouldProcess)]
    param(
        [Parameter(Mandatory)]
        [string] $Vault,
        [ValidateSet('base', 'dnd', 'phandelver')]
        [string[]] $Kit = @('base'),
        [string[]] $Name,
        [switch] $Force
    )

    $ErrorActionPreference = 'Stop'
    $obsidianDir = Join-Path $Vault '.obsidian'
    if (-not (Test-Path -LiteralPath $obsidianDir)) { throw "Не волт Обсидиана: нет $obsidianDir" }

    $catalog = Get-RollObsidianCatalog
    $items = @($catalog | Where-Object { ($Kit -contains $_.Kit) -or ($Name -contains $_.Id) })
    foreach ($n in $Name) {
        if (-not ($catalog | Where-Object Id -eq $n)) { Write-Warning "Нет в каталоге: $n" }
    }

    $installed = @()
    foreach ($item in $items) {
        $target = Get-RollObsidianTarget $item $obsidianDir
        $files = @(Get-RollObsidianFiles $item)

        $newer = @($files | Where-Object {
            $dst = Join-Path $target $_.Relative
            (Test-Path -LiteralPath $dst) -and
            (Get-FileHash -LiteralPath $dst).Hash -ne (Get-FileHash -LiteralPath $_.Path).Hash -and
            (Get-Item -LiteralPath $dst).LastWriteTime -gt (Get-Item -LiteralPath $_.Path).LastWriteTime
        })
        if ($newer -and -not $Force) {
            Write-Warning ("$($item.Id): в волте правка новее, чем в Roll ($($newer.Relative -join ', ')). " +
                'Пропускаю: перенеси её в Roll или поставь с -Force.')
            continue
        }

        $changed = 0
        foreach ($f in $files) {
            $dst = Join-Path $target $f.Relative
            $same = (Test-Path -LiteralPath $dst) -and
                (Get-FileHash -LiteralPath $dst).Hash -eq (Get-FileHash -LiteralPath $f.Path).Hash
            if ($same) { continue }
            if ($PSCmdlet.ShouldProcess($dst, "копировать $($item.Id)")) {
                New-Item -ItemType Directory -Force (Split-Path $dst) | Out-Null
                Copy-Item -LiteralPath $f.Path -Destination $dst -Force
            }
            $changed++
        }
        Write-Host ("{0,-28} {1}" -f $item.Id, $(if ($changed) { "обновлено файлов: $changed" } else { 'без изменений' }))
        $installed += $item

        foreach ($need in $item.Needs) {
            if (-not (Test-Path -LiteralPath (Join-Path $obsidianDir "plugins\$need"))) {
                Write-Warning "$($item.Id) работает в паре с плагином $need, а его в волте нет."
            }
        }
    }

    # Включение. Открытый Обсидиан перезапишет настройки при выходе.
    $pluginsPath = Join-Path $obsidianDir 'community-plugins.json'
    $appearancePath = Join-Path $obsidianDir 'appearance.json'
    $plugins = [System.Collections.Generic.List[string]]::new()
    foreach ($p in @(Read-RollObsidianJson $pluginsPath)) { if ($p) { $plugins.Add($p) } }
    $appearance = Read-RollObsidianJson $appearancePath
    if (-not $appearance) { $appearance = [pscustomobject] @{} }
    $snippets = [System.Collections.Generic.List[string]]::new()
    foreach ($s in @($appearance.enabledCssSnippets)) { if ($s) { $snippets.Add($s) } }

    $toPlugins = @($installed | Where-Object { $_.Kind -eq 'plugin' -and -not $plugins.Contains($_.Id) } | ForEach-Object { $_.Id })
    $toSnippets = @($installed | Where-Object { $_.Kind -eq 'snippet' -and -not $snippets.Contains($_.Id) } | ForEach-Object { $_.Id })
    if (-not $toPlugins -and -not $toSnippets) { Write-Host 'Всё поставленное уже включено.'; return }

    if (Get-Process -Name Obsidian -ErrorAction SilentlyContinue) {
        Write-Warning 'Обсидиан запущен: включение не трогаю, он перезапишет настройки при выходе.'
        if ($toPlugins) { Write-Host "Включить в Settings -> Community plugins: $($toPlugins -join ', ')" }
        if ($toSnippets) { Write-Host "Включить в Settings -> Appearance -> CSS snippets: $($toSnippets -join ', ')" }
        Write-Host 'Или закрой Обсидиан и запусти команду ещё раз.'
        return
    }

    if ($toPlugins -and $PSCmdlet.ShouldProcess($pluginsPath, "включить $($toPlugins -join ', ')")) {
        $toPlugins | ForEach-Object { $plugins.Add($_) }
        Write-RollObsidianJson $pluginsPath ([string[]] $plugins)
        Write-Host "Включены плагины: $($toPlugins -join ', ')"
    }
    if ($toSnippets -and $PSCmdlet.ShouldProcess($appearancePath, "включить $($toSnippets -join ', ')")) {
        $toSnippets | ForEach-Object { $snippets.Add($_) }
        $appearance | Add-Member -NotePropertyName enabledCssSnippets -NotePropertyValue ([string[]] $snippets) -Force
        Write-RollObsidianJson $appearancePath $appearance
        Write-Host "Включены сниппеты: $($toSnippets -join ', ')"
    }
}
