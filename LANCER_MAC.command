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
# Données (base + documents importés) HORS d'iCloud : une base SQLite synchronisée peut s'abîmer.
DATA_DIR="${SIE_DATA_DIR:-$HOME/SIE_data}"
if lsof -nP -iTCP:8000 -sTCP:LISTEN >/dev/null 2>&1; then
  echo "Un serveur SIE tourne déjà (port 8000). Fermez l'autre fenêtre du Terminal, puis relancez."
  read -r; exit 1
fi
if [ ! -f "$DATA_DIR/sie.db" ] && [ -f data/sie.db ]; then
  echo "Déplacement des données hors d'iCloud vers $DATA_DIR ..."
  mkdir -p "$DATA_DIR"
  for x in sie.db sie.db-wal sie.db-shm files texte .pending; do
    if [ -e "data/$x" ]; then mv "data/$x" "$DATA_DIR/" || { echo "Échec du déplacement de $x"; read -r; exit 1; }; fi
  done
  echo "Données déplacées."
fi
export SIE_DATA_DIR="$DATA_DIR"
# Rédaction IA : la clé OpenAI est lue dans $DATA_DIR/ia.env (hors du projet, jamais versionnée).
if [ -f "$DATA_DIR/ia.env" ]; then
  chmod 600 "$DATA_DIR/ia.env" 2>/dev/null
  set -a; . "$DATA_DIR/ia.env"; set +a
  echo "Rédaction IA : configurée (modèle ${OPENAI_MODEL:-par défaut})"
else
  echo "Rédaction IA : non configurée (créer $DATA_DIR/ia.env avec OPENAI_API_KEY=...)"
fi
echo "Données : $SIE_DATA_DIR"
echo "Tests automatiques..."
OPENAI_API_KEY= SIE_IA_FOURNISSEUR= PYTHONDONTWRITEBYTECODE=1 "$PY" -m pytest tests -q -p no:cacheprovider 2>&1 | tee data/.derniers_tests.txt
echo
echo "Démarrage du serveur : http://127.0.0.1:8000  (fermer cette fenêtre pour arrêter)"
PYTHONDONTWRITEBYTECODE=1 "$PY" server.py
