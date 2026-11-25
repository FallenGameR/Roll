<#
    Каталог надстроек Обсидиана из Obsidian\catalog.json модуля: плагины и
    сниппеты, написанные для наших волтов. Имя и описание плагина берутся
    из его manifest.json, у сниппета - из каталога.
#>
function Get-RollObsidianCatalog {
    $root = Join-Path $script:RollRoot 'Obsidian'
    $catalog = Get-Content -LiteralPath (Join-Path $root 'catalog.json') -Raw -Encoding UTF8 | ConvertFrom-Json

    $items = @()
    foreach ($p in $catalog.plugins) {
        $dir = Join-Path $root "plugins\$($p.id)"
        $manifest = Get-Content -LiteralPath (Join-Path $dir 'manifest.json') -Raw -Encoding UTF8 | ConvertFrom-Json
        $items += [pscustomobject] @{
            Kind        = 'plugin'
            Id          = $p.id
            Kit         = $p.kit
            Name        = $manifest.name
            Description = $manifest.description
            Needs       = @($p.needs)
            Source      = $dir
        }
    }
    foreach ($s in $catalog.snippets) {
        $items += [pscustomobject] @{
            Kind        = 'snippet'
            Id          = $s.name
            Kit         = $s.kit
            Name        = $s.name
            Description = $s.description
            Needs       = @($s.needs)
            Source      = Join-Path $root "snippets\$($s.name).css"
        }
    }

    # Файл, о котором не знает каталог, установщик не поставит: напомнить.
    $known = $items | ForEach-Object { $_.Source }
    $onDisk = @(Get-ChildItem -LiteralPath (Join-Path $root 'plugins') -Directory | ForEach-Object { $_.FullName }) +
              @(Get-ChildItem -LiteralPath (Join-Path $root 'snippets') -Filter *.css | ForEach-Object { $_.FullName })
    foreach ($path in $onDisk) {
        if ($known -notcontains $path) { Write-Warning "Нет в catalog.json: $path" }
    }

    $items
}

# Файлы плагина или сниппета относительно его корня. data.json - настройки и
# состояние плагина в конкретном волте, его не переносим.
function Get-RollObsidianFiles($item) {
    if ($item.Kind -eq 'snippet') {
        return , ([pscustomobject] @{ Path = $item.Source; Relative = Split-Path $item.Source -Leaf })
    }
    Get-ChildItem -LiteralPath $item.Source -Recurse -File |
        Where-Object { $_.Name -ne 'data.json' } |
        ForEach-Object { [pscustomobject] @{ Path = $_.FullName; Relative = $_.FullName.Substring($item.Source.Length + 1) } }
}

function Get-RollObsidianTarget($item, $obsidianDir) {
    if ($item.Kind -eq 'snippet') { return Join-Path $obsidianDir 'snippets' }
    Join-Path $obsidianDir "plugins\$($item.Id)"
}

# Состояние надстройки в волте: нет, совпадает с Roll, отличается.
function Get-RollObsidianState($item, $obsidianDir) {
    $target = Get-RollObsidianTarget $item $obsidianDir
    $state = 'совпадает'
    foreach ($f in Get-RollObsidianFiles $item) {
        $dst = Join-Path $target $f.Relative
        if (-not (Test-Path -LiteralPath $dst)) { return 'нет' }
        if ((Get-FileHash -LiteralPath $dst).Hash -ne (Get-FileHash -LiteralPath $f.Path).Hash) { $state = 'отличается' }
    }
    $state
}

function Read-RollObsidianJson($path) {
    if (-not (Test-Path -LiteralPath $path)) { return $null }
    Get-Content -LiteralPath $path -Raw -Encoding UTF8 | ConvertFrom-Json
}

function Write-RollObsidianJson($path, $value) {
    $text = (ConvertTo-Json -InputObject $value -Depth 20) -replace "`r`n", "`n"
    [System.IO.File]::WriteAllText($path, $text + "`n", [System.Text.UTF8Encoding]::new($false))
}
