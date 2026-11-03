<#
.SYNOPSIS
    Internal helper: locates an executable installed via winget, whose
    install path is versioned and therefore not predictable in advance
    (e.g. ffmpeg/deno land under a version-numbered package folder).
    Falls back to the same executable on PATH, so a machine where the tool
    came from somewhere else (scoop, choco, a manual unzip) works too.
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
        $found = Get-Command $ExeName -CommandType Application -ErrorAction SilentlyContinue |
            Select-Object -First 1 -ExpandProperty Source
    }
    if (-not $found) {
        throw "Could not find $ExeName under WinGet packages matching '$PackageGlob' or on PATH. " +
              "Install it with winget and retry."
    }
    return $found
}
