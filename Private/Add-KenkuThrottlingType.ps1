<#
    P/Invoke для EcoQoS: SetProcessInformation с
    PROCESS_POWER_THROTTLING_STATE. Отдельным файлом, потому что тип
    компилируется один раз за сессию, а Repair-KenkuAudio может
    вызываться многократно.
#>
function Add-KenkuThrottlingType {
    if ('Roll.ProcessPower' -as [type]) { return }

    Add-Type -Language CSharp -TypeDefinition @'
using System;
using System.Runtime.InteropServices;

namespace Roll {
    public static class ProcessPower {
        const int ProcessPowerThrottling = 4;
        const uint EXECUTION_SPEED = 0x1;
        const uint PROCESS_SET_INFORMATION = 0x0200;
        const uint PROCESS_QUERY_LIMITED_INFORMATION = 0x1000;

        [StructLayout(LayoutKind.Sequential)]
        struct State {
            public uint Version;
            public uint ControlMask;
            public uint StateMask;
        }

        [DllImport("kernel32.dll", SetLastError = true)]
        static extern IntPtr OpenProcess(uint access, bool inherit, int pid);

        [DllImport("kernel32.dll", SetLastError = true)]
        static extern bool CloseHandle(IntPtr handle);

        [DllImport("kernel32.dll", SetLastError = true)]
        static extern bool SetProcessInformation(IntPtr handle, int cls,
            ref State info, uint size);

        [DllImport("kernel32.dll", SetLastError = true)]
        static extern bool GetProcessInformation(IntPtr handle, int cls,
            ref State info, uint size);

        const uint THREAD_SET_INFORMATION = 0x0020;
        const uint THREAD_QUERY_INFORMATION = 0x0040;
        const int THREAD_PRIORITY_HIGHEST = 2;
        const int THREAD_PRIORITY_TIME_CRITICAL = 15;
        const int THREAD_MODE_BACKGROUND_END = 0x00020000;

        [DllImport("kernel32.dll", SetLastError = true)]
        static extern IntPtr OpenThread(uint access, bool inherit, int tid);

        [DllImport("kernel32.dll", SetLastError = true)]
        static extern bool SetThreadPriority(IntPtr handle, int priority);

        [DllImport("kernel32.dll", SetLastError = true)]
        static extern int GetThreadPriority(IntPtr handle);

        /// <summary>
        /// Поднимает приоритет потока и выводит его из фонового режима.
        /// Класс приоритета процесса потоки не покрывает: Chromium
        /// отдельно опускает свои рабочие потоки, и аудио среди них.
        /// </summary>
        public static bool RaiseThread(int tid, bool timeCritical) {
            IntPtr handle = OpenThread(
                THREAD_SET_INFORMATION | THREAD_QUERY_INFORMATION, false, tid);
            if (handle == IntPtr.Zero) { return false; }
            try {
                // Снятие фонового режима заодно возвращает потоку
                // нормальный приоритет ввода-вывода.
                SetThreadPriority(handle, THREAD_MODE_BACKGROUND_END);
                return SetThreadPriority(handle, timeCritical
                    ? THREAD_PRIORITY_TIME_CRITICAL : THREAD_PRIORITY_HIGHEST);
            }
            finally { CloseHandle(handle); }
        }

        public static int ThreadPriority(int tid) {
            IntPtr handle = OpenThread(THREAD_QUERY_INFORMATION, false, tid);
            if (handle == IntPtr.Zero) { return int.MinValue; }
            try { return GetThreadPriority(handle); }
            finally { CloseHandle(handle); }
        }

        public static bool DisableThrottling(int pid, out bool wasThrottled) {
            wasThrottled = false;
            IntPtr handle = OpenProcess(
                PROCESS_SET_INFORMATION | PROCESS_QUERY_LIMITED_INFORMATION,
                false, pid);
            if (handle == IntPtr.Zero) { return false; }
            try {
                State current = new State();
                current.Version = 1;
                uint size = (uint)Marshal.SizeOf(typeof(State));
                if (GetProcessInformation(handle, ProcessPowerThrottling,
                        ref current, size)) {
                    wasThrottled = (current.StateMask & EXECUTION_SPEED) != 0;
                }

                // ControlMask с нулевым StateMask означает "этим рычагом
                // управляем мы, и он выключен" - процесс перестаёт быть
                // кандидатом на EcoQoS. Разрешение менять системный
                // таймер сюда не входит: оно глобальное и заметно ест
                // батарею на ноутбуке.
                State off = new State();
                off.Version = 1;
                off.ControlMask = EXECUTION_SPEED;
                off.StateMask = 0;
                return SetProcessInformation(handle, ProcessPowerThrottling,
                    ref off, size);
            }
            finally { CloseHandle(handle); }
        }
    }
}
'@
}
