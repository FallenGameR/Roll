<#
.SYNOPSIS
    Applies a loudness plan produced by Tools/gain-plan.py: lossless
    global_gain edits via mp3rgain, and a list of tracks that need
    re-encoding instead.

.DESCRIPTION
    Reads the plan CSV and processes every row marked "lossless" by
    calling mp3rgain with the precomputed number of 1.5 dB steps.
    Tracks sharing the same step count are passed in batches, which is
    an order of magnitude faster than invoking mp3rgain per file.

    Rows marked "reencode" are not handled here: they need the ffmpeg
    loudnorm path. Their paths are written to a JSON file next to the
    plan so they can be piped straight into Tools/loudnorm.py.

    Nothing is decoded or re-compressed: mp3rgain rewrites the
    global_gain field inside the existing frames, so cover art and ID3
    tags are untouched and the change is reversible with "mp3rgain -u".

.PARAMETER Path
    Plan CSV written by gain-plan.py.

.PARAMETER BatchSize
    How many files to hand to mp3rgain in one call. 150 keeps the
    command line well under the Windows limit.

.PARAMETER WhatIf
    Report what would happen without touching any file.

.EXAMPLE
    Import-Module C:\vaults\Roll\Roll.psd1 -Force
    python C:\vaults\Roll\Tools\loudness.py paths.json measured.json
    python C:\vaults\Roll\Tools\gain-plan.py measured.json plan.csv
    C:\vaults\Roll\Tools\Invoke-GainPlan.ps1 -Path plan.csv
#>
[CmdletBinding(SupportsShouldProcess)]
param(
    [Parameter(Mandatory, Position = 0)]
    [string]$Path,

    [int]$BatchSize = 150
)

$ErrorActionPreference = 'Stop'

$mp3rgain = Get-ChildItem -Path "$env:LOCALAPPDATA\Microsoft\WinGet\Packages" `
    -Recurse -Filter 'mp3rgain.exe' -ErrorAction SilentlyContinue |
    Select-Object -First 1

if (-not $mp3rgain) {
    throw "mp3rgain.exe not found. Install it with: winget install --id M-Igashi.mp3rgain"
}

$plan = Import-Csv -LiteralPath $Path

$missing = @($plan | Where-Object { -not (Test-Path -LiteralPath $_.Path) })
if ($missing) {
    Write-Warning "$($missing.Count) file(s) from the plan no longer exist and will be skipped."
}

$lossless = @($plan | Where-Object {
        $_.Action -eq 'lossless' -and
        [int]$_.Steps -ne 0 -and
        (Test-Path -LiteralPath $_.Path)
    })

$reencode = @($plan | Where-Object {
        $_.Action -eq 'reencode' -and (Test-Path -LiteralPath $_.Path)
    })

Write-Host "lossless: $($lossless.Count) | reencode: $($reencode.Count)"

# Группируем по величине сдвига: mp3rgain принимает один -g на вызов,
# поэтому пачка может содержать только файлы с одинаковым числом шагов.
$done = 0
$failed = @()

foreach ($group in $lossless | Group-Object Steps) {
    $steps = [int]$group.Name
    $files = @($group.Group.Path)

    Write-Host ("  {0,3} шагов ({1,6:+0.0;-0.0} дБ): {2} файлов" -f `
            $steps, ($steps * 1.5), $files.Count)

    for ($i = 0; $i -lt $files.Count; $i += $BatchSize) {
        $chunk = $files[$i..([Math]::Min($i + $BatchSize - 1, $files.Count - 1))]

        if (-not $PSCmdlet.ShouldProcess("$($chunk.Count) file(s)", "gain $steps steps")) {
            continue
        }

        # -p сохраняет исходную дату файла, чтобы правка громкости не
        # выглядела как «трек добавлен сегодня».
        & $mp3rgain.FullName -g $steps -p -q @chunk 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) {
            $failed += "steps=$steps batch=$i"
        }
        $done += $chunk.Count
    }
}

Write-Host "поднято/ослаблено lossless: $done | ошибок: $($failed.Count)"
foreach ($f in $failed) { Write-Warning "mp3rgain failed: $f" }

if ($reencode) {
    $listPath = [IO.Path]::ChangeExtension($Path, '.reencode.json')
    $reencode.Path | ConvertTo-Json -AsArray | Set-Content -LiteralPath $listPath -Encoding UTF8
    Write-Host "требуют перекодирования: $($reencode.Count) -> $listPath"
    Write-Host "  python C:\vaults\Roll\Tools\loudnorm.py `"$listPath`" report.json --apply"
}
