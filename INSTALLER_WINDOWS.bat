@echo off
cd /d "%~dp0"
echo Installation des dependances Python pour SIE Tender Intelligence...
py -3 -m pip install -r requirements.txt
if errorlevel 1 (
  echo Installation incomplete. Verifiez votre version de Python et votre connexion Internet.
) else (
  echo Installation terminee. Double-cliquez sur DEMARRER_WINDOWS.bat.
)
pause
