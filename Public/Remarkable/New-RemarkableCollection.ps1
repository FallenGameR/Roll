<#
.SYNOPSIS
    Создаёт папку на Remarkable.

.DESCRIPTION
    RCU-CLI папки создавать не умеет, поэтому команда делает это так же,
    как сам планшет: кладёт по scp файл <id>.metadata с типом
    CollectionType в ~/.local/share/remarkable/xochitl и перезапускает
    интерфейс планшета (xochitl), иначе тот новую папку не увидит.
    Перезапуск закрывает открытый на планшете документ, поэтому
    команда спрашивает подтверждение.

    Метаданные уходят готовым файлом, а не командой: base64 на планшете
    нет, а кириллица в аргументах ssh зависит от кодировки.

    Если папка с таким путём уже есть, команда её и возвращает.

.PARAMETER Name
    Имя папки.

.PARAMETER Parent
    Путь родительской папки через "/", как Path в
    Get-RemarkableCollection. Без параметра папка ложится в корень.

.EXAMPLE
    New-RemarkableCollection 'Сенека. Письма к Луцилию'

.EXAMPLE
    New-RemarkableCollection 'BG3' -Parent 'RPG/Archive'
#>
function New-RemarkableCollection {
    [CmdletBinding(SupportsShouldProcess, ConfirmImpact = 'High')]
    param(
        [Parameter(Mandatory, Position = 0)]
        [string]$Name,

        [string]$Parent
    )

    $all = @(Get-RemarkableCollection)
    $path = if ($Parent) { "$Parent/$Name" } else { $Name }
    $existing = $all | Where-Object Path -eq $path
    if ($existing) {
        Write-Host "Папка уже есть: $path"
        return $existing
    }

    $parentId = ''
    if ($Parent) {
        $parentItem = $all | Where-Object Path -eq $Parent
        if (-not $parentItem) { throw "На планшете нет папки '$Parent'." }
        $parentId = $parentItem.Id
    }

    if (-not $PSCmdlet.ShouldProcess($path, 'Создать папку и перезапустить интерфейс Remarkable')) {
        return
    }

    $id = [guid]::NewGuid().ToString()
    $now = [string][DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
    $metadata = [ordered]@{
        createdTime  = $now
        lastModified = $now
        new          = $false
        parent       = $parentId
        pinned       = $false
        source       = ''
        type         = 'CollectionType'
        visibleName  = $Name
    } | ConvertTo-Json
    $local = Join-Path ([IO.Path]::GetTempPath()) "$id.metadata"
    [IO.File]::WriteAllText($local, $metadata, [Text.UTF8Encoding]::new($false))
    try {
        Send-RemarkableRawFile $local "/home/root/.local/share/remarkable/xochitl/$id.metadata"
    }
    finally {
        Remove-Item -LiteralPath $local -ErrorAction SilentlyContinue
    }
    Invoke-RemarkableSsh 'systemctl restart xochitl' | Out-Null

    Start-Sleep -Seconds 3
    Get-RemarkableCollection | Where-Object Id -eq $id
}
