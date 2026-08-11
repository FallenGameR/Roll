<#
.SYNOPSIS
    Internal helper: locates an executable installed via winget, whose
    install path is versioned and therefore not predictable in advance
    (e.g. ffmpeg/deno land under a version-numbered package folder).
#>
function Find-WingetTool {
    param(
        [Parameter(Mandatory = $true)][string]$PackageGlob,
        [Parameter(Mandatory = $true)][string]$ExeName
    )
    $found = Get-ChildItem "$env:LOCALAPPDATA\Microsoft\WinGet\Packages\$PackageGlob" `
        -Recurse -Filter $ExeName -ErrorAction SilentlyContinue |
        Select-Object -First 1 -ExpandProperty FullName
    if (-not $found) {
        throw "Could not find $ExeName under WinGet packages matching '$PackageGlob'. " +
              "Install it with winget and retry."
    }
    return $found
}
