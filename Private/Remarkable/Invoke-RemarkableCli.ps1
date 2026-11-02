<#
.SYNOPSIS
    Internal helper: запускает RCU-CLI с последним сохранённым пресетом
    подключения и возвращает его вывод строками.

.DESCRIPTION
    RCU-CLI сам ничего не знает про адрес и пароль планшета: ключ
    --autoconnect берёт последний пресет, сохранённый в GUI-версии
    (RCU.exe, см. Open-Remarkable). Ключ --cli прячет окно и лог.

    Без связи CLI ждёт секунд восемь, пишет "connection unsuccessful" и
    выходит с кодом 1. Поэтому сначала проверяется порт по адресу
    активного пресета: спящий планшет отсекается за две секунды.

    Печатает RCU в трубу в cp1252 и падает на кириллице, а переменные
    PYTHONIOENCODING и PYTHONUTF8 собранный exe игнорирует. Поэтому
    списки идут не через него, а по SSH (Invoke-RemarkableSsh).

    Путь к RCU-CLI.exe можно переопределить переменной окружения
    RCU_CLI, по умолчанию C:\tools\RCU\RCU-CLI.exe.
#>
function Invoke-RemarkableCli {
    param(
        [Parameter(Mandatory)]
        [string[]]$Arguments
    )

    $exe = Get-RemarkableCliPath
    if (-not (Test-Path -LiteralPath $exe)) {
        throw "Не найден RCU-CLI: $exe. Укажи путь в `$env:RCU_CLI."
    }
    $preset = Get-ActiveRemarkablePreset
    if ($preset -and -not (Test-RemarkablePort $preset.host)) {
        throw "Remarkable не отвечает по $($preset.host). Разбуди планшет и проверь, " +
              'что он в той же сети Wi-Fi.'
    }

    $output = @(& $exe --autoconnect --cli @Arguments 2>&1 | ForEach-Object { "$_" })
    $exitCode = $LASTEXITCODE

    if ($output -match 'connection unsuccessful') {
        throw 'Remarkable не отвечает. Разбуди планшет и проверь, что он в той ' +
              'же сети Wi-Fi или подключён кабелем; адрес и пароль - в пресете ' +
              'RCU (Open-Remarkable).'
    }
    if ($exitCode -ne 0) {
        throw "RCU-CLI завершился с кодом ${exitCode}:`n$($output -join "`n")"
    }
    $output
}

function Get-RemarkableCliPath {
    if ($env:RCU_CLI) { $env:RCU_CLI } else { 'C:\tools\RCU\RCU-CLI.exe' }
}
