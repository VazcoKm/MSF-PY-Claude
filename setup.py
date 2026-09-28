"""
setup.py — instala dependencias del vault
uso: python setup.py
"""
import subprocess
import sys

PACKAGES = [
    "requests>=2.31.0",
    "psutil>=5.9.0",
    "pywin32>=306",
    "pycryptodome>=3.20.0",
    "cryptography>=42.0.0",
    "browser-cookie3>=0.19.1",
    "pyinstaller",
]

def install():
    for pkg in PACKAGES:
        print(f"[*] {pkg}")
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", pkg, "--quiet"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
    print("\n[+] Todas las dependencias instaladas.")
    print("[*] Para compilar: build.bat")

if __name__ == "__main__":
    install()
