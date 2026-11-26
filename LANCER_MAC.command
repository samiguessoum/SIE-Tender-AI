#!/bin/bash
# Lancement de SIE Tender Intelligence sur macOS (double-cliquer ce fichier).
cd "$(dirname "$0")" || exit 1
echo "== SIE Tender Intelligence =="
if [ ! -x .venv/bin/python ]; then
  echo "Création de l'environnement Python (.venv)..."
  python3 -m venv .venv || { echo "Python 3 introuvable."; read -r; exit 1; }
fi
echo "Installation / vérification des dépendances..."
.venv/bin/python -m pip install -q --upgrade pip
.venv/bin/python -m pip install -q -r requirements.txt pytest httpx || { echo "Échec de l'installation."; read -r; exit 1; }
echo "Tests automatiques..."
.venv/bin/python -m pytest tests -q 2>&1 | tee data/.derniers_tests.txt
echo
echo "Démarrage du serveur : http://127.0.0.1:8000  (fermer cette fenêtre pour arrêter)"
.venv/bin/python server.py
