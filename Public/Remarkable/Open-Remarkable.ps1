<#
.SYNOPSIS
    Открывает окно RCU: спаривание с планшетом, папки, скриншоты.

.DESCRIPTION
    Все остальные команды темы ходят через RCU-CLI, а тот подключается по
    последнему пресету, сохранённому здесь, в GUI. Поэтому новое
    подключение или смена адреса делаются в этом окне.

    Спаривание, один раз на планшет и сеть:

    1. На планшете открыть Menu - Settings - Help - About - Copyrights
       and licenses, раздел GPLv3 Compliance. Там адрес, пользователь
       (root) и пароль SSH.
    2. По кабелю адрес всегда 10.11.99.1. По Wi-Fi на прошивке 3.22 и
       новее SSH надо включить: в RCU правый клик по значку планшета, или
       `rm-ssh-over-wlan on` на самом планшете.
    3. В окне RCU, панель Connection: вписать Host, Username, Password,
       нажать Save, включить Auto. Connect и нажать Connect.
    4. Для нескольких сетей - несколько пресетов через стрелку у Save;
       CLI возьмёт тот, который был активен последним.

    Paper Pro, Move и Pure работают со сторонним софтом только в режиме
    разработчика, а вход в него сбрасывает планшет к заводским.

    Настройки и пресеты RCU хранит в %APPDATA%\davisr\rcu.ini открытым
    текстом, вместе с паролем. Файл не копировать в волт и не выводить.

.EXAMPLE
    Open-Remarkable
#>
function Open-Remarkable {
    [CmdletBinding()]
    param()

    $gui = Join-Path (Split-Path (Get-RemarkableCliPath)) 'RCU.exe'
    if (-not (Test-Path -LiteralPath $gui)) {
        throw "Не найден RCU: $gui"
    }
    Start-Process -FilePath $gui -WorkingDirectory (Split-Path $gui)
}
