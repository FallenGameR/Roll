<#
    Маска логических процессоров с производительными ядрами.

    У гибридных процессоров (Intel Lunar Lake и подобных) часть ядер
    низкопроизводительные: в GetSystemCpuSetInformation у них
    EfficiencyClass = 0. Планировщик охотно ссылает туда фоновые
    потоки, и аудиорендер Kenku в их числе.
#>
function Get-PerformanceCoreMask {
    if (-not ('Roll.CpuSets' -as [type])) {
        Add-Type -Language CSharp -TypeDefinition @'
using System;
using System.Runtime.InteropServices;

namespace Roll {
    public static class CpuSets {
        [DllImport("kernel32.dll", SetLastError = true)]
        public static extern bool GetSystemCpuSetInformation(IntPtr info,
            uint size, out uint returned, IntPtr process, uint flags);
    }
}
'@
    }

    $length = 0
    [Roll.CpuSets]::GetSystemCpuSetInformation([IntPtr]::Zero, 0, [ref]$length,
        [IntPtr]::Zero, 0) | Out-Null
    if ($length -le 0) { return 0 }

    $buffer = [Runtime.InteropServices.Marshal]::AllocHGlobal($length)
    try {
        if (-not [Roll.CpuSets]::GetSystemCpuSetInformation($buffer, $length,
                [ref]$length, [IntPtr]::Zero, 0)) {
            return 0
        }

        $best = 0
        $classes = @{}
        $offset = 0
        while ($offset -lt $length) {
            $size = [Runtime.InteropServices.Marshal]::ReadInt32($buffer, $offset)
            if ($size -le 0) { break }
            # Смещения внутри SYSTEM_CPU_SET_INFORMATION.CpuSet:
            # 14 - LogicalProcessorIndex, 18 - EfficiencyClass.
            $logical = [Runtime.InteropServices.Marshal]::ReadByte($buffer, $offset + 14)
            $class = [Runtime.InteropServices.Marshal]::ReadByte($buffer, $offset + 18)
            $classes[[int]$logical] = [int]$class
            if ($class -gt $best) { $best = [int]$class }
            $offset += $size
        }

        if ($best -eq 0) { return 0 }   # ядра однородные, ограничивать нечего

        $mask = [int64] 0
        foreach ($logical in $classes.Keys) {
            if ($classes[$logical] -gt 0) { $mask = $mask -bor ([int64]1 -shl $logical) }
        }
        return $mask
    }
    finally { [Runtime.InteropServices.Marshal]::FreeHGlobal($buffer) }
}
