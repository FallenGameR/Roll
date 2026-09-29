<#
.SYNOPSIS
    Internal helper: runs a scriptblock with the console set to read
    external-process output as UTF-8, then restores the previous setting.

.DESCRIPTION
    ffprobe and yt-dlp print UTF-8. PowerShell decodes the stdout of an
    external process using [Console]::OutputEncoding, which on a default
    Windows console is the OEM code page (437/866/850 depending on the
    system). Russian text in the Comment tag then comes back as mojibake
    - the tags themselves are fine, only the reading side is wrong.

    Wrapping the ffprobe calls in this helper makes the decoding explicit
    instead of depending on whatever the user's terminal happens to be
    set to. The previous encoding is restored afterwards so the caller's
    console is left exactly as it was.
#>
function Invoke-WithUtf8Console {
    param(
        [Parameter(Mandatory)]
        [scriptblock]$ScriptBlock
    )

    $previous = [Console]::OutputEncoding
    $needsChange = $previous.CodePage -ne 65001

    if ($needsChange) {
        try { [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false) }
        catch { $needsChange = $false }  # редкие хосты без консоли
    }

    try { & $ScriptBlock }
    finally {
        if ($needsChange) {
            try { [Console]::OutputEncoding = $previous } catch { }
        }
    }
}
