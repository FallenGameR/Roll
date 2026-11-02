<#
.SYNOPSIS
    Internal helper: запускает RCU-CLI с последним сохранённым пресетом
    подключения и возвращает его вывод строками.

.DESCRIPTION
    RCU-CLI сам ничего не знает про адрес и пароль планшета: ключ
    --autoconnect берёт последний пресет, сохранённый в GUI-версии
    (RCU.exe, см. Open-Remarkable). Ключ --cli прячет окно и лог.

    Без связи CLI ждёт секунд восемь, пишет "connection unsuccessful" и
    выходит с кодом 1. Это превращается в исключение с подсказкой, что
    делать, а не в пустой список.

    RCU собран из Python, поэтому PYTHONIOENCODING=utf-8 заставляет его
    печатать имена документов в UTF-8, а Invoke-WithUtf8Console читает
    их без кракозябр.

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

    $previousIo = $env:PYTHONIOENCODING
    $env:PYTHONIOENCODING = 'utf-8'
    try {
        $output = @(Invoke-WithUtf8Console {
            & $exe --autoconnect --cli @Arguments 2>&1 | ForEach-Object { "$_" }
        })
        $exitCode = $LASTEXITCODE
    }
    finally {
        $env:PYTHONIOENCODING = $previousIo
    }

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
