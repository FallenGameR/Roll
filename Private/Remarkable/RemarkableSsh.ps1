<#
.SYNOPSIS
    Internal helpers: команды на Remarkable по SSH и разбор его
    метаданных.

.DESCRIPTION
    Списки документов идут по SSH, а не через RCU-CLI: тот печатает в
    трубу в cp1252 и падает на первом же кириллическом имени, а
    переменные PYTHONIOENCODING и PYTHONUTF8 собранный exe игнорирует.

    Пароль ssh спрашивает через SSH_ASKPASS, а Tools\Remarkable\askpass.cmd
    отдаёт ему пароль активного пресета RCU. Так пароль живёт в одном
    месте, в rcu.ini, и нигде не печатается. Нужен OpenSSH 8.4+ (в
    Windows 11 он есть) ради SSH_ASKPASS_REQUIRE=force.

    Документы лежат в ~/.local/share/remarkable/xochitl: на каждый
    <id>.metadata (имя, папка-родитель, тип) и <id>.content (тип файла).
    У корня parent пустой, у корзины - "trash".
#>
function Invoke-RemarkableSsh {
    param(
        [Parameter(Mandatory)]
        [string]$Command
    )

    Use-RemarkableAskpass 'ssh' {
        param($target)
        ssh -n -o StrictHostKeyChecking=accept-new -o ConnectTimeout=5 $target $Command
    }
}

function Send-RemarkableRawFile {
    <# Кладёт локальный файл на планшет по scp. Ключ -O нужен: SFTP на
       планшете нет, и новый протокол scp рвёт соединение. #>
    param(
        [Parameter(Mandatory)]
        [string]$LocalPath,

        [Parameter(Mandatory)]
        [string]$RemotePath
    )

    Use-RemarkableAskpass 'scp' {
        param($target)
        scp -O -q -o StrictHostKeyChecking=accept-new -o ConnectTimeout=5 $LocalPath "${target}:$RemotePath"
    } | Out-Null
}

function Use-RemarkableAskpass {
    param(
        [Parameter(Mandatory)]
        [string]$Tool,

        [Parameter(Mandatory)]
        [scriptblock]$ScriptBlock
    )

    $preset = Get-ActiveRemarkablePreset
    if (-not $preset) {
        throw 'Нет пресета подключения к Remarkable. Set-RemarkableConnection.'
    }
    if (-not (Test-RemarkablePort $preset.host)) {
        throw "Remarkable не отвечает по $($preset.host). Разбуди планшет и проверь, " +
              'что он в той же сети Wi-Fi.'
    }

    $target = "$($preset.username)@$($preset.host)"
    $toolBlock = $ScriptBlock
    $saved = $env:SSH_ASKPASS, $env:SSH_ASKPASS_REQUIRE
    $env:SSH_ASKPASS = Join-Path $script:RollRoot 'Tools\Remarkable\askpass.cmd'
    $env:SSH_ASKPASS_REQUIRE = 'force'
    try {
        $output = @(Invoke-WithUtf8Console {
            & $toolBlock $target 2>&1 | ForEach-Object { "$_" }
        })
        $exitCode = $LASTEXITCODE
    }
    finally {
        $env:SSH_ASKPASS, $env:SSH_ASKPASS_REQUIRE = $saved
    }
    if ($exitCode -ne 0) {
        throw "$Tool на Remarkable завершился с кодом ${exitCode}:`n$($output -join "`n")"
    }
    $output
}

function Get-RemarkableItem {
    $command = 'cd ~/.local/share/remarkable/xochitl && for f in *.metadata; do ' +
        'i=${f%.metadata}; ' +
        't=$(grep -o ''"fileType": *"[^"]*"'' "$i.content" 2>/dev/null); ' +
        'printf ''\n@@%s|%s\n'' "$i" "$t"; cat "$f"; done'

    $raw = @{}
    $id = $null
    $buffer = [Text.StringBuilder]::new()
    $flush = {
        if ($id) { $raw[$id.Id] = [pscustomobject]@{ Head = $id; Json = $buffer.ToString() } }
    }
    foreach ($line in Invoke-RemarkableSsh $command) {
        if ($line -match '^@@([^|]+)\|(.*)$') {
            & $flush
            $itemId, $typeText = $Matches[1], $Matches[2]
            $fileType = if ($typeText -match '"fileType": *"([^"]*)"') { $Matches[1] } else { '' }
            $id = @{ Id = $itemId; FileType = $fileType }
            $buffer.Clear() | Out-Null
        } else {
            $buffer.AppendLine($line) | Out-Null
        }
    }
    & $flush

    $meta = @{}
    foreach ($entry in $raw.Values) {
        try { $data = $entry.Json | ConvertFrom-Json } catch { continue }
        if ($data.deleted) { continue }
        $meta[$entry.Head.Id] = [pscustomobject]@{
            Id       = $entry.Head.Id
            Name     = $data.visibleName
            Folder   = $data.type -eq 'CollectionType'
            FileType = $entry.Head.FileType
            Parent   = "$($data.parent)"
            Modified = [DateTimeOffset]::FromUnixTimeMilliseconds([long]$data.lastModified).LocalDateTime
        }
    }

    $pathOf = @{}
    $resolve = $null
    $resolve = {
        param($itemId)
        if ($pathOf.ContainsKey($itemId)) { return $pathOf[$itemId] }
        $item = $meta[$itemId]
        $path = if (-not $item) { '?' }
            elseif ($item.Parent -eq '') { $item.Name }
            elseif ($item.Parent -eq 'trash') { "Корзина/$($item.Name)" }
            else { "$(& $resolve $item.Parent)/$($item.Name)" }
        $pathOf[$itemId] = $path
        $path
    }

    foreach ($item in $meta.Values) {
        $full = & $resolve $item.Id
        $parentPath = if ($item.Parent -eq '') { '' } else { $full.Substring(0, $full.Length - $item.Name.Length - 1) }
        [pscustomobject]@{
            Id       = $item.Id
            Name     = $item.Name
            Folder   = $item.Folder
            FileType = $item.FileType
            Path     = $full
            Parent   = $parentPath
            Trashed  = $full -like 'Корзина/*'
            Modified = $item.Modified
        }
    }
}
