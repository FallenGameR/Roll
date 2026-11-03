<#
.SYNOPSIS
    Internal helper: находит yt-dlp.

.DESCRIPTION
    Порядок поиска:
      1. $env:ROLL_YTDLP - явный путь, если yt-dlp лежит в своём месте;
      2. установка через winget (пакет yt-dlp.yt-dlp);
      3. yt-dlp на PATH.

    YouTube регулярно ломает старые версии, а на PATH часто оказывается
    давний yt-dlp от pip. Поэтому версия старше полугода даёт
    предупреждение: обновить - winget upgrade yt-dlp.yt-dlp.
#>
function Get-YtDlpPath {
    $path = $env:ROLL_YTDLP
    if (-not $path) {
        $path = try { Find-WingetTool 'yt-dlp.yt-dlp_*' 'yt-dlp.exe' } catch { $null }
    }
    if (-not $path -or -not (Test-Path -LiteralPath $path)) {
        throw ('Не найден yt-dlp. Поставьте его: winget install yt-dlp.yt-dlp, ' +
               'или укажите путь в $env:ROLL_YTDLP.')
    }

    $version = (& $path --version 2>$null | Select-Object -First 1)
    if ($version -match '^(\d{4})\.(\d{2})\.(\d{2})') {
        $released = [datetime]::new([int]$Matches[1], [int]$Matches[2], [int]$Matches[3])
        if ($released -lt (Get-Date).AddMonths(-6)) {
            Write-Warning ("yt-dlp $version в $path старше полугода; YouTube мог его сломать. " +
                           'Обновите или укажите свежий в $env:ROLL_YTDLP.')
        }
    }
    $path
}
