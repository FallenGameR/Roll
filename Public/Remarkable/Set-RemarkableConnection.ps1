<#
.SYNOPSIS
    Создаёт или правит пресет подключения к Remarkable и делает его
    активным.

.DESCRIPTION
    Пишет пресет в %APPDATA%\davisr\rcu.ini, откуда его берёт RCU-CLI.
    Файл локальный, в git не попадает. Пароль спрашивается скрыто и
    нигде не печатается; если его не задать, у существующего пресета
    остаётся прежний.

    Пароль и адрес - на планшете: Settings - Help - About - Copyrights
    and licenses, раздел GPLv3 Compliance. По кабелю адрес 10.11.99.1.

    Чтобы работал Wi-Fi, на прошивке 3.22 и новее на планшете включают
    SSH по Wi-Fi: в окне RCU (Open-Remarkable) правый клик по значку
    планшета, либо команда `rm-ssh-over-wlan on` на самом планшете.
    Адрес по Wi-Fi выдаёт роутер, и он может смениться; надёжнее
    закрепить его за планшетом в настройках DHCP роутера.

    Окно RCU должно быть закрыто, иначе оно затрёт правку.

.PARAMETER Name
    Имя пресета. Если такой есть, он правится, иначе создаётся новый.

.PARAMETER HostName
    Адрес планшета. Для нового пресета обязателен.

.PARAMETER User
    Пользователь SSH, по умолчанию root.

.PARAMETER NewPassword
    Задать пароль: команда спросит его скрыто. Для нового пресета
    спрашивается всегда.

.EXAMPLE
    Set-RemarkableConnection -Name 'Wi-Fi' -HostName 192.168.50.174

.EXAMPLE
    Set-RemarkableConnection -Name 'Wi-Fi' -NewPassword
#>
function Set-RemarkableConnection {
    [CmdletBinding(SupportsShouldProcess)]
    param(
        [Parameter(Mandatory, Position = 0)]
        [string]$Name,

        [string]$HostName,

        [string]$User,

        [switch]$NewPassword
    )

    $data = Read-RemarkablePresets
    $presets = [Collections.Generic.List[object]]::new()
    foreach ($p in $data.presets) { $presets.Add($p) }

    $index = -1
    for ($i = 0; $i -lt $presets.Count; $i++) {
        if ($presets[$i].name -eq $Name) { $index = $i; break }
    }

    if ($index -lt 0) {
        if (-not $HostName) { throw "Пресета '$Name' нет; для нового нужен -HostName." }
        $presets.Add([pscustomobject]@{ name = $Name; host = ''; username = 'root'; password = '' })
        $index = $presets.Count - 1
        $NewPassword = $true
    }
    $preset = $presets[$index]

    if ($HostName) { $preset.host = $HostName }
    if ($User) { $preset.username = $User }
    if ($NewPassword) {
        $secure = Read-Host "Пароль SSH для '$Name'" -AsSecureString
        $plain = [Net.NetworkCredential]::new('', $secure).Password
        if (-not $plain) { throw 'Пустой пароль, пресет не изменён.' }
        $preset.password = $plain
    }

    if (-not $PSCmdlet.ShouldProcess((Get-RemarkableIniPath), "Записать пресет '$Name' ($($preset.host)) и сделать активным")) {
        return
    }
    Write-RemarkablePresets ([pscustomobject]@{ active = $index; presets = $presets.ToArray() })
    Get-RemarkableConnection | Where-Object Name -eq $Name
}
