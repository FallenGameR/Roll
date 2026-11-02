<#
.SYNOPSIS
    Internal helpers: чтение и запись пресетов подключения RCU.

.DESCRIPTION
    RCU хранит пресеты в %APPDATA%\davisr\rcu.ini, раздел [connection],
    строкой presets="{...}": JSON в кавычках с экранированными \" и \\
    (формат QSettings). Пароль там лежит открытым текстом. Файл
    локальный и в git не попадает, поэтому пароль держим именно в нём,
    а не дублируем в модуле: RCU-CLI всё равно читает его оттуда.

    Пресет возвращается объектом с полем password. Наружу из модуля
    объект с паролем не отдаётся: Get-RemarkableConnection его маскирует.

    Пока открыто окно RCU, оно держит настройки в памяти и при закрытии
    затрёт правку, поэтому запись при запущенном RCU.exe отказывается.
#>
function Get-RemarkableIniPath {
    Join-Path $env:APPDATA 'davisr\rcu.ini'
}

function Read-RemarkablePresets {
    $path = Get-RemarkableIniPath
    if (-not (Test-Path -LiteralPath $path)) {
        return [pscustomobject]@{ active = 0; presets = @() }
    }
    $line = [IO.File]::ReadAllLines($path, [Text.UTF8Encoding]::new($false)) |
        Where-Object { $_ -like 'presets=*' } | Select-Object -First 1
    if (-not $line) {
        return [pscustomobject]@{ active = 0; presets = @() }
    }
    $value = $line.Substring('presets='.Length)
    if ($value.StartsWith('"') -and $value.EndsWith('"')) {
        $value = $value.Substring(1, $value.Length - 2)
    }
    $json = $value.Replace('\"', '"').Replace('\\', '\')
    $data = $json | ConvertFrom-Json
    $data.presets = @($data.presets)
    $data
}

function Write-RemarkablePresets {
    param(
        [Parameter(Mandatory)]
        $Data
    )

    if (Get-Process -Name RCU -ErrorAction SilentlyContinue) {
        throw 'Окно RCU открыто и при закрытии затрёт пресеты. Закрой его и повтори.'
    }

    $path = Get-RemarkableIniPath
    $json = ConvertTo-Json -InputObject $Data -Depth 5 -Compress
    $line = 'presets="' + $json.Replace('\', '\\').Replace('"', '\"') + '"'

    $lines = [Collections.Generic.List[string]]::new()
    if (Test-Path -LiteralPath $path) {
        $lines.AddRange([IO.File]::ReadAllLines($path, [Text.UTF8Encoding]::new($false)))
    }
    $index = $lines.FindIndex({ param($l) $l -like 'presets=*' })
    if ($index -ge 0) {
        $lines[$index] = $line
    } else {
        $section = $lines.IndexOf('[connection]')
        if ($section -lt 0) {
            if ($lines.Count) { $lines.Add('') }
            $lines.Add('[connection]')
            $section = $lines.Count - 1
        }
        $lines.Insert($section + 1, $line)
    }

    New-Item -ItemType Directory -Force -Path (Split-Path $path) | Out-Null
    [IO.File]::WriteAllText($path, ($lines -join "`r`n") + "`r`n", [Text.UTF8Encoding]::new($false))
}

function Get-ActiveRemarkablePreset {
    $data = Read-RemarkablePresets
    if (-not $data.presets.Count) { return $null }
    $data.presets[[int]$data.active]
}

function Test-RemarkablePort {
    param(
        [Parameter(Mandatory)]
        [string]$HostName,

        [int]$TimeoutMs = 2000
    )

    $client = [Net.Sockets.TcpClient]::new()
    try { $client.ConnectAsync($HostName, 22).Wait($TimeoutMs) }
    catch { $false }
    finally { $client.Dispose() }
}
