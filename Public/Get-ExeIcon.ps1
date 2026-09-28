<#
.SYNOPSIS
    Достаёт одну иконку из exe-файла и кладёт её в PNG.

.DESCRIPTION
    Нужен для значка вкладки в интерфейсе фонотеки: иконка берётся из
    установленного плеера, а не хранится в вольте копией.

    `ExtractAssociatedIcon` умеет только первую иконку файла, а у
    winamp.exe их восемнадцать, и нужна не первая. Поэтому тут
    ExtractIconEx с явным индексом.

    Порядок индексов не совпадает с тем, что показывает диалог
    "Change Icon" в свойствах ярлыка: тот сортирует по-своему.
    Чтобы посмотреть все разом, гони с -All и открой папку.

.PARAMETER Path
    Файл с иконками (exe или dll).

.PARAMETER Index
    Номер иконки, с нуля.

.PARAMETER Size
    Желаемый размер в пикселях. В exe лежит несколько версий рисунка, и
    они отличаются не только чёткостью: у winamp.exe мелкая - голая
    молния, а крупная - молния в тёмном скруглённом квадрате. Берётся
    ближайшая из имеющихся.

.PARAMETER Destination
    Куда сохранить PNG.

.PARAMETER All
    Вытащить все иконки в папку Destination именами icon-N.png.

.EXAMPLE
    Get-ExeIcon -Path 'C:\Program Files (x86)\Winamp\winamp.exe' -Index 0 -Size 256 -Destination icon.png
#>
function Get-ExeIcon {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory, Position = 0)]
        [string] $Path,

        [int] $Index = 0,

        [int] $Size = 32,

        [Parameter(Mandatory, Position = 1)]
        [string] $Destination,

        [switch] $All
    )

    $ErrorActionPreference = 'Stop'
    Add-Type -AssemblyName System.Drawing

    if (-not ('RollIconEx' -as [type])) {
        Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public class RollIconEx {
  [DllImport("shell32.dll", CharSet=CharSet.Unicode)]
  public static extern int ExtractIconEx(string file, int index, IntPtr[] large, IntPtr[] small, int count);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)]
  public static extern int PrivateExtractIcons(string file, int index, int cx, int cy,
      IntPtr[] icons, int[] ids, int count, int flags);
  [DllImport("user32.dll")] public static extern bool DestroyIcon(IntPtr h);
}
'@
    }

    $save = {
        param($idx, $out)
        $handles = New-Object IntPtr[] 1
        $ids = New-Object int[] 1
        $got = [RollIconEx]::PrivateExtractIcons($Path, $idx, $Size, $Size, $handles, $ids, 1, 0)
        if ($got -lt 1 -or $handles[0] -eq [IntPtr]::Zero) { return $false }
        $icon = [System.Drawing.Icon]::FromHandle($handles[0])
        $bitmap = $icon.ToBitmap()
        $bitmap.Save($out, [System.Drawing.Imaging.ImageFormat]::Png)
        $bitmap.Dispose()
        $null = [RollIconEx]::DestroyIcon($handles[0])
        return $true
    }

    if ($All) {
        $total = [RollIconEx]::ExtractIconEx($Path, -1, $null, $null, 0)
        if (-not (Test-Path -LiteralPath $Destination)) {
            $null = New-Item -ItemType Directory -Path $Destination -Force
        }
        for ($i = 0; $i -lt $total; $i++) {
            $null = & $save $i (Join-Path $Destination "icon-$i.png")
        }
        return $total
    }

    if (& $save $Index $Destination) { return $Destination }
    throw "иконка $Index в файле не нашлась: $Path"
}
