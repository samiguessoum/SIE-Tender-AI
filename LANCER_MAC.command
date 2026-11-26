#!/bin/bash
# Lancement de SIE Tender Intelligence sur macOS (double-cliquer ce fichier).
# L'environnement Python est créé HORS du bureau : le bureau est synchronisé par iCloud,
# ce qui bloque Python sur les milliers de petits fichiers d'un environnement virtuel.
cd "$(dirname "$0")" || exit 1
VENV="$HOME/venvs/sie-tender-intelligence"
PY="$VENV/bin/python"
echo "== SIE Tender Intelligence =="
if [ ! -x "$PY" ]; then
  echo "Création de l'environnement Python dans $VENV ..."
  mkdir -p "$HOME/venvs" && python3 -m venv "$VENV" || { echo "Python 3 introuvable."; read -r; exit 1; }
fi
echo "Vérification des dépendances..."
if "$PY" -c "import fastapi, uvicorn, fitz, docx, openpyxl, pytest, httpx" 2>/dev/null; then
  echo "Dépendances déjà installées."
else
  echo "Installation des dépendances (connexion Internet nécessaire, 1 à 2 minutes)..."
  "$PY" -m pip install --disable-pip-version-check -r requirements.txt pytest httpx || { echo "Échec de l'installation."; read -r; exit 1; }
fi
echo "Tests automatiques..."
PYTHONDONTWRITEBYTECODE=1 "$PY" -m pytest tests -q -p no:cacheprovider 2>&1 | tee data/.derniers_tests.txt
echo
echo "Démarrage du serveur : http://127.0.0.1:8000  (fermer cette fenêtre pour arrêter)"
PYTHONDONTWRITEBYTECODE=1 "$PY" server.py
