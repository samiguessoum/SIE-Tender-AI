@echo off
cd /d "%~dp0"
echo SIE Tender Intelligence - Application locale
py -3 server.py
if errorlevel 1 (
  echo Erreur de demarrage. Consultez README.md pour installer les dependances.
  pause
)
