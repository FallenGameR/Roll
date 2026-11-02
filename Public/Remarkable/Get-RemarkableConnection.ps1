<#
.SYNOPSIS
    Показывает пресеты подключения к Remarkable и доступен ли планшет.

.DESCRIPTION
    Читает пресеты RCU из %APPDATA%\davisr\rcu.ini. Пароль не выводится:
    вместо него поле PasswordSet. Online проверяет, открыт ли порт SSH
    по адресу пресета; спящий планшет Wi-Fi выключает и даёт False.

.EXAMPLE
    Get-RemarkableConnection
#>
function Get-RemarkableConnection {
    [CmdletBinding()]
    param()

    $data = Read-RemarkablePresets
    for ($i = 0; $i -lt $data.presets.Count; $i++) {
        $preset = $data.presets[$i]
        [pscustomobject]@{
            Name        = $preset.name
            Active      = $i -eq [int]$data.active
            Host        = $preset.host
            User        = $preset.username
            PasswordSet = [bool]$preset.password
            Online      = Test-RemarkablePort $preset.host
        }
    }
}
