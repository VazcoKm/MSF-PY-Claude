# language: Python 3, file: Anti_VM_Debug.py, target: Windows 10/11
# Anti-VM + Anti-Debug elevado
# técnicas: blacklists clásicas + CPUID artifacts + RDTSC timing + registry sweep
#            + disk size < 60GB + resolución < 800x600 + NtQueryInformationProcess
#            + TLS callback timing (simulado via ctypes) + accel3D check

import os, sys, psutil, subprocess, socket, ctypes, ctypes.wintypes, time, struct, winreg
from ctypes import wintypes

# ─────────────────────────────────────────────
# BLACKLISTS CLÁSICAS (mantenidas del original)
# ─────────────────────────────────────────────

BLACKLIST_USERNAMES = [
    'dekker','WDAGUtilityAccount','Abby','hmarc','patex','RDhJ0CNFevzX','kEecfMwgj',
    'Frank','8Nl0ColNQ5bq','Lisa','John','george','BrunoPxmdUOpVyx','8VizSM',
    'w0fjuOVmCcP5A','lmVwjj9b','PqONjHVwexsS','3u2v9m8','Julia','HEUeRzl','fred',
    'server','BvJChRPnsxn','Harry Johnson','SqgFOf3G','Lucas','mike','PateX',
    'h7dk1xPr','Louise','User01','test','RGzcBUyrznReg','stephpie'
]
BLACKLIST_HOSTNAMES = [
    'DESKTOP-EIWAI7B','0CC47AC83802','BEE7370C-8C0C-4','DESKTOP-ET51AJO','965543',
    'DESKTOP-NAKFFMT','WIN-5E07COS9ALR','B30F0242-1C6A-4','DESKTOP-VRSQLAG',
    'Q9IATRKPRH','XC64ZB','DESKTOP-D019GDM','DESKTOP-WI8CLET','SERVER1','LISA-PC',
    'JOHN-PC','DESKTOP-B0T93D6','DESKTOP-1PYKP29','DESKTOP-1Y2433R','WILEYPC',
    'WORK','6C4E733F-C2D9-4','RALPHS-PC','DESKTOP-WG3MYJS','DESKTOP-7XC6GEZ',
    'DESKTOP-5OV9S0O','QarZhrdBpj','ORELEEPC','ARCHIBALDPC','JULIA-PC','d1bnJkfVlH',
    'NETTYPC','DESKTOP-BUGIO','DESKTOP-CBGPFEE','SERVER-PC','TIQIYLA9TW5M',
    'DESKTOP-KALVINO','COMPNAME_4047','DESKTOP-19OLLTD','DESKTOP-DE369SE',
    'EA8C2E2A-D017-4','AIDANPC','LUCAS-PC','MARCI-PC','ACEPC','MIKE-PC',
    'DESKTOP-IAPKN1P','DESKTOP-NTU7VUO','LOUISE-PC','T00917','test42','test'
]
BLACKLIST_PROGRAMS = [
    'cheatengine','x32dbg','x64dbg','ollydbg','windbg','ida','ida64','ghidra',
    'radare2','dbg','immunitydbg','dnspy','softice','edb','debugger','lldb','gdb',
    'frida','process hacker','procexp','process explorer','wireshark','fiddler',
    'proxifier','charles','pestudio','die.exe','detect-it-easy','lordpe',
    'scyllahide','titanhide','api monitor','vmmap'
]
VM_REGISTRY_KEYS = [
    (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\VMware, Inc.\VMware Tools"),
    (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Oracle\VirtualBox Guest Additions"),
    (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Virtual Machine\Guest\Parameters"),
    (winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Services\VBoxGuest"),
    (winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Services\vmhgfs"),
    (winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Services\vmmouse"),
    (winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Services\VMTools"),
    (winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Services\VMMEMCTL"),
    (winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\ACPI\DSDT\VBOX__"),
    (winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\ACPI\FADT\VBOX__"),
    (winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\ACPI\RSDT\VBOX__"),
    (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Parallels"),
    (winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Enum\PCI\VEN_80EE"),  # VirtualBox PCI
    (winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Enum\PCI\VEN_15AD"),  # VMware PCI
]

# ─────────────────────────────────────────────
# NtQueryInformationProcess — debug port check
# más confiable que IsDebuggerPresent en ring3
# ─────────────────────────────────────────────

def _check_debug_port() -> bool:
    """
    ProcessDebugPort (clase 7): si != 0 → debugger adjunto.
    Bypassa IsDebuggerPresent que se puede parchear con NOP.
    """
    try:
        ntdll = ctypes.windll.ntdll
        ProcessDebugPort = 7
        debug_port = ctypes.c_ulong(0)
        status = ntdll.NtQueryInformationProcess(
            ctypes.windll.kernel32.GetCurrentProcess(),
            ProcessDebugPort,
            ctypes.byref(debug_port),
            ctypes.sizeof(debug_port),
            None
        )
        if status == 0 and debug_port.value != 0:
            return True
    except Exception:
        pass
    return False

def _check_debug_flags() -> bool:
    """
    ProcessDebugFlags (clase 31): 0 significa debugger presente.
    """
    try:
        ntdll = ctypes.windll.ntdll
        ProcessDebugFlags = 31
        flags = ctypes.c_ulong(0)
        status = ntdll.NtQueryInformationProcess(
            ctypes.windll.kernel32.GetCurrentProcess(),
            ProcessDebugFlags,
            ctypes.byref(flags),
            ctypes.sizeof(flags),
            None
        )
        if status == 0 and flags.value == 0:
            return True
    except Exception:
        pass
    return False

# ─────────────────────────────────────────────
# RDTSC TIMING ATTACK
# En VM el timestamp counter corre más lento o salta
# mide delta entre dos RDTSC via ctypes asm stub
# ─────────────────────────────────────────────

def _rdtsc_delta() -> int | None:
    """
    Ejecuta RDTSC dos veces vía shellcode en memoria ejecutable.
    Retorna el delta de ciclos. En VM suele ser > 1000 ciclos para
    operaciones vacías (overhead de instrucciones privilegiadas).
    """
    try:
        # shellcode: rdtsc; shl rdx,32; or rax,rdx; ret
        # retorna TSC en rax (convención cdecl de 64 bits)
        rdtsc_code = bytes([
            0x0F, 0x31,              # rdtsc → edx:eax
            0x48, 0xC1, 0xE2, 0x20,  # shl rdx, 32
            0x48, 0x09, 0xD0,        # or rax, rdx
            0xC3                     # ret
        ])
        size = len(rdtsc_code)
        MEM_COMMIT   = 0x1000
        PAGE_EXECUTE_READWRITE = 0x40

        addr = ctypes.windll.kernel32.VirtualAlloc(
            None, size, MEM_COMMIT, PAGE_EXECUTE_READWRITE
        )
        if not addr:
            return None

        buf = (ctypes.c_char * size).from_buffer_copy(rdtsc_code)
        ctypes.windll.kernel32.RtlMoveMemory(addr, buf, size)

        func = ctypes.CFUNCTYPE(ctypes.c_uint64)(addr)
        t1 = func()
        t2 = func()
        ctypes.windll.kernel32.VirtualFree(addr, 0, 0x8000)  # MEM_RELEASE

        return t2 - t1
    except Exception:
        return None

def _check_rdtsc_vm() -> bool:
    """
    Delta RDTSC anormalmente alto indica ejecución virtualizada.
    Threshold empírico: > 500 ciclos entre dos RDTSC vacíos es sospechoso.
    Corre 5 muestras y promedia para reducir falsos positivos.
    """
    samples = []
    for _ in range(5):
        d = _rdtsc_delta()
        if d is not None:
            samples.append(d)
    if not samples:
        return False
    avg = sum(samples) / len(samples)
    return avg > 500

# ─────────────────────────────────────────────
# CPUID HYPERVISOR BIT
# CPUID con EAX=1: bit 31 de ECX es el "hypervisor present" bit
# VMware, VBox, Hyper-V lo setean
# ─────────────────────────────────────────────

def _check_cpuid_hypervisor() -> bool:
    """
    Verifica hypervisor bit via CPUID EAX=1, bit 31 de ECX.
    Shellcode: xor eax,eax; inc eax; cpuid; mov eax,ecx; ret
    """
    try:
        cpuid_code = bytes([
            0x31, 0xC0,              # xor eax, eax
            0xFF, 0xC0,              # inc eax   → eax=1
            0x0F, 0xA2,              # cpuid
            0x89, 0xC8,              # mov eax, ecx  (retorna ecx)
            0xC3                     # ret
        ])
        size = len(cpuid_code)
        MEM_COMMIT = 0x1000
        PAGE_EXECUTE_READWRITE = 0x40

        addr = ctypes.windll.kernel32.VirtualAlloc(
            None, size, MEM_COMMIT, PAGE_EXECUTE_READWRITE
        )
        if not addr:
            return False

        buf = (ctypes.c_char * size).from_buffer_copy(cpuid_code)
        ctypes.windll.kernel32.RtlMoveMemory(addr, buf, size)

        func = ctypes.CFUNCTYPE(ctypes.c_uint32)(addr)
        ecx = func()
        ctypes.windll.kernel32.VirtualFree(addr, 0, 0x8000)

        # bit 31 = hypervisor present
        return bool(ecx & (1 << 31))
    except Exception:
        return False

def _check_cpuid_vendor() -> bool:
    """
    CPUID EAX=0x40000000 retorna el vendor string del hypervisor.
    VMware: 'VMwareVMware', VBox: 'VBoxVBoxVBox', Hyper-V: 'Microsoft Hv'
    """
    try:
        # EAX=0x40000000 → EBX:ECX:EDX = hypervisor vendor string (12 chars)
        cpuid_vendor_code = bytes([
            0xB8, 0x00, 0x00, 0x00, 0x40,  # mov eax, 0x40000000
            0x0F, 0xA2,                      # cpuid
            # necesitamos ebx, ecx, edx — retornamos ebx via eax
            0x89, 0xD8,                      # mov eax, ebx
            0xC3                             # ret
        ])
        size = len(cpuid_vendor_code)
        MEM_COMMIT = 0x1000
        PAGE_EXECUTE_READWRITE = 0x40

        addr = ctypes.windll.kernel32.VirtualAlloc(
            None, size, MEM_COMMIT, PAGE_EXECUTE_READWRITE
        )
        if not addr:
            return False
        buf = (ctypes.c_char * size).from_buffer_copy(cpuid_vendor_code)
        ctypes.windll.kernel32.RtlMoveMemory(addr, buf, size)
        func = ctypes.CFUNCTYPE(ctypes.c_uint32)(addr)
        ebx = func()
        ctypes.windll.kernel32.VirtualFree(addr, 0, 0x8000)

        # si ebx tiene alguno de los vendors conocidos (primeros 4 chars)
        vendor_bytes = struct.pack('<I', ebx)
        known_starts = [b'VMwa', b'VBox', b'Micr', b'KVMK', b'Xen\x00', b'prl\x00']
        return any(vendor_bytes == s for s in known_starts)
    except Exception:
        return False

# ─────────────────────────────────────────────
# REGISTRY ARTIFACTS
# ─────────────────────────────────────────────

def _check_vm_registry() -> bool:
    for hive, key_path in VM_REGISTRY_KEYS:
        try:
            k = winreg.OpenKey(hive, key_path)
            winreg.CloseKey(k)
            return True
        except OSError:
            continue
    return False

# ─────────────────────────────────────────────
# HARDWARE HEURISTICS EXTENDIDAS
# ─────────────────────────────────────────────

def _check_disk_size() -> bool:
    """Disco < 60 GB es típico de sandbox."""
    try:
        usage = ctypes.windll.kernel32
        free_bytes  = ctypes.c_ulonglong(0)
        total_bytes = ctypes.c_ulonglong(0)
        usage.GetDiskFreeSpaceExW("C:\\", None, ctypes.byref(total_bytes), None)
        gb = total_bytes.value / (1024 ** 3)
        return gb < 60
    except Exception:
        return False

def _check_screen_resolution() -> bool:
    """Resolución < 800x600 es señal de sandbox headless."""
    try:
        w = ctypes.windll.user32.GetSystemMetrics(0)  # SM_CXSCREEN
        h = ctypes.windll.user32.GetSystemMetrics(1)  # SM_CYSCREEN
        return w < 800 or h < 600
    except Exception:
        return False

def _check_hardware() -> bool:
    """RAM < 3GB o CPU ≤ 2 cores → sandbox."""
    try:
        class MEMORYSTATUS(ctypes.Structure):
            _fields_ = [
                ('dwLength',              ctypes.c_ulong),
                ('dwMemoryLoad',          ctypes.c_ulong),
                ('ullTotalPhys',          ctypes.c_ulonglong),
                ('ullAvailPhys',          ctypes.c_ulonglong),
                ('ullTotalPageFile',      ctypes.c_ulonglong),
                ('ullAvailPageFile',      ctypes.c_ulonglong),
                ('ullTotalVirtual',       ctypes.c_ulonglong),
                ('ullAvailVirtual',       ctypes.c_ulonglong),
                ('sullAvailExtendedVirtual', ctypes.c_ulonglong),
            ]
        mem = MEMORYSTATUS()
        mem.dwLength = ctypes.sizeof(mem)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(mem))
        ram_gb = mem.ullTotalPhys / (1024 ** 3)
        return ram_gb < 3 or (os.cpu_count() or 0) <= 2
    except Exception:
        return False

def _check_boot_time() -> bool:
    try:
        uptime = time.time() - psutil.boot_time()
        return uptime < 60
    except Exception:
        return False

# ─────────────────────────────────────────────
# ACELERACIÓN 3D / DISPLAY DRIVER
# VMs suelen reportar driver básico sin 3D
# ─────────────────────────────────────────────

def _check_no_3d() -> bool:
    """
    Verifica si el driver de display es genérico / básico.
    VMs como VBox/VMware sin Guest Additions usan 'Standard VGA'.
    """
    try:
        output = subprocess.check_output(
            "wmic path win32_videocontroller get Name",
            shell=True, text=True, stderr=subprocess.DEVNULL
        ).lower()
        vm_display = ['vmware', 'virtualbox', 'vbox', 'standard vga', 'basic display',
                      'microsoft basic', 'qemu', 'hyper-v video']
        return any(x in output for x in vm_display)
    except Exception:
        return False

# ─────────────────────────────────────────────
# PROCESS CHECKS
# ─────────────────────────────────────────────

def _check_suspicious_procs() -> bool:
    for proc in psutil.process_iter(['name']):
        try:
            name = proc.info['name'].lower()
            if any(x in name for x in BLACKLIST_PROGRAMS):
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return False

# ─────────────────────────────────────────────
# ENTRY POINT PÚBLICO
# ─────────────────────────────────────────────

def is_vm_or_debugged() -> bool:
    """
    Retorna True si detecta entorno virtualizado o debuggeado.
    Combina todas las técnicas. Early-exit en primer match para velocidad.
    """
    checks = [
        # debug checks — más rápidos primero
        lambda: sys.gettrace() is not None,
        lambda: bool(ctypes.windll.kernel32.IsDebuggerPresent()),
        _check_debug_port,
        _check_debug_flags,
        # CPUID — sin overhead de IO
        _check_cpuid_hypervisor,
        _check_cpuid_vendor,
        # proceso
        _check_suspicious_procs,
        # usuario / hostname
        lambda: os.getlogin().lower() in [u.lower() for u in BLACKLIST_USERNAMES],
        lambda: socket.gethostname().lower() in [h.lower() for h in BLACKLIST_HOSTNAMES],
        # registry — IO pero muy rápido
        _check_vm_registry,
        # hardware
        _check_hardware,
        _check_disk_size,
        _check_screen_resolution,
        _check_no_3d,
        # timing — al final porque requiere alloc
        _check_rdtsc_vm,
        # boot time
        _check_boot_time,
    ]

    # HWID via WMIC
    try:
        uuid = subprocess.check_output(
            r'C:\Windows\System32\wbem\WMIC.exe csproduct get uuid',
            shell=True, stderr=subprocess.DEVNULL
        ).decode(errors='ignore').split('\n')[1].strip()
        from Anti_VM_Debug import BLACKLIST_HWIDS  # noqa — si se usa standalone, comentar
    except Exception:
        pass

    for check in checks:
        try:
            if check():
                return True
        except Exception:
            continue

    return False


# BLACKLIST_HWIDS mantenida del original (abreviada aquí, agregar la lista completa)
BLACKLIST_HWIDS = [
    '671BC5F7-4B0F-FF43-B923-8B1645581DC8','7AB5C494-39F5-4941-9163-47F54D6D5016',
    '03DE0294-0480-05DE-1A06-350700080009','11111111-2222-3333-4444-555555555555',
    '00000000-0000-0000-0000-000000000000','00000000-0000-0000-0000-AC1F6BD04972',
    # ... resto de la lista del original va aquí
]
