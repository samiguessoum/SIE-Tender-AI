# SIE-Tender-AI

**Plateforme locale de préparation des réponses aux appels d'offres** — développée pour SIE (électricité CFO / CFA / SSI).

SIE-Tender-AI centralise une consultation de bout en bout : import du DCE, analyse structurée des pièces (RC, questions-réponses, CCAP, cadre de réponse, CCTP), fiche de renseignement pré-remplie avec sources, alertes à traiter, métrés, demandes de prix, DPGF, mémoire technique et contrôle final. Tout tourne sur le poste ou le serveur de l'entreprise, sans service d'IA externe ni cloud ; l'IA locale (RAG sur les mémoires historiques) est prévue dans une phase ultérieure.

> Nom de code historique : *SIE Tender Intelligence*.

## Démarrer sur macOS

Double-cliquer sur `LANCER_MAC.command` : il crée l'environnement Python hors d'iCloud (`~/venvs/sie-tender-intelligence`), installe les dépendances au premier lancement, exécute les tests puis démarre le serveur sur http://127.0.0.1:8000.

---

## Prototype fonctionnel local (documentation d'origine)

**Version 1 de développement**, construite à partir de la maquette HTML V2 et des spécifications du 10 novembre 2026. L'interface originale est conservée. La persistance, les fichiers et certains traitements reposent sur un serveur Python **local**, sans API IA externe.

## Démarrer l'application (Windows)

1. Installer Python 3.11 ou supérieur : <https://www.python.org/downloads/>. Cocher « Add Python to PATH » si demandé.
2. Extraire **tout** le ZIP dans un dossier de travail, et ouvrir un terminal (PowerShell ou Invite de commandes) dans ce dossier.
3. Installer les dépendances :

   ```powershell
   py -3 -m pip install -r requirements.txt
   ```

4. Double-cliquer sur `DEMARRER_WINDOWS.bat` ou saisir `py -3 server.py`.
5. Ouvrir **http://127.0.0.1:8000** dans Chrome, Firefox ou Edge.

**Ne pas ouvrir** `static/index.html` en double-cliquant dessus. La version fonctionnelle nécessite le serveur local ; en mode `file://`, les requêtes API et le stockage ne fonctionneront pas.

## Démarrer (macOS / Linux)

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python3 server.py
```

Puis ouvrir http://127.0.0.1:8000. Le serveur écoute sur `127.0.0.1`, donc uniquement sur cet ordinateur.

## Fonctions opérationnelles

- **Consultations** : création avec une référence unique, modification, sélection, séparation des données d'une consultation à l'autre, sauvegarde automatique sur disque.
- **DCE** : import réel de dossiers et de fichiers, conservation des arborescences, copie locale par blocs pour les gros fichiers, inventaire, téléchargement et suppression.
- **Fiche de renseignement** : saisie des informations du marché, tous les lots, décision GO / NO GO **manuelle**, responsable de visite, impression / PDF via le navigateur, export JSON.
- **Analyse** : repérage lexical dans PDF disposant de texte, DOCX, TXT, CSV et certains ZIP ; extraits retrouvés avec source et page quand disponible, puis ajout manuel aux points de vigilance.
- **Métrés** : lecture locale de `.xlsx`, `.xlsm`, `.csv`, prévisualisation, association des colonnes, conservation des imports, application **sur confirmation** des quantités à la DPGF.
- **Fournisseurs** : choix manuel des fournisseurs, préparation de demandes, ouverture de brouillons d'e-mail sans envoi automatique, sélection d'extraits du CCTP PDF, comparaison de prix et sélection de devis.
- **DPGF** : édition des lignes, contrôle des prix manquants, génération d'une DPGF de travail `.xlsx` à partir du modèle SIE embarqué. Les prix de vente et calculs engageants doivent être vérifiés.
- **Mémoire technique** : rédaction par consultation et par lot, réutilisation manuelle de passages historiques retrouvés par recherche textuelle locale, impression / PDF depuis le navigateur.
- **Documents et contrôle final** : ajout de fichiers réels, classement, suivi humain des pièces reçues et validées, téléchargement d'une **archive ZIP structurée** de travail avec les fichiers réellement déposés, états JSON et DPGF Excel provisoire.
- **Paramètres** : référentiels fournisseurs / utilisateurs / personnes chargées des visites.

Les trois dossiers préchargés « DEMO » et leurs chiffres sont **fictifs** : ils servent à explorer l'interface. Pour une consultation réelle, cliquer sur « Consultations » et créer son dossier.

## Stockage et sauvegardes

- `data/sie.db` : base SQLite de l'application, données, fiches, alertes et paramètres.
- `data/files/` : **copies réelles des documents importés**.
- `data/.pending/` : fichiers temporaires pendant les transferts ou exports.

**Sauvegarder ensemble** `data/sie.db` et `data/files/` avec le serveur arrêté. Une copie de ce dossier constitue votre sauvegarde locale. Pour changer l'emplacement du stockage, définir la variable d'environnement `SIE_DATA_DIR` avant de démarrer. Le dossier `data` fourni dans le ZIP est vide, prêt à recevoir vos données.

## Limites importantes

Cette version est un **prototype local opérationnel**, pas une plateforme commerciale prête à exposer sur Internet.

- **Pas d'authentification multi-utilisateur ni de contrôle d'accès par rôle** : ne pas la publier sur un réseau ou sur Internet sans développement de sécurité complémentaire.
- **Pas d'IA générative ni de véritable RAG / synchronisation SMB automatique** : recherche textuelle et saisie assistée seulement. Les écrans décrivant une architecture RAG sont des spécifications pour une étape ultérieure.
- **Pas de lecture OCR des scans ou de lecture des plans DWG**. Les PDF scannés sans couche texte ne peuvent pas être analysés automatiquement. Le repérage est indicatif et non exhaustif.
- Les anciens fichiers Excel `.xls` doivent être convertis en `.xlsx` ou CSV pour l'import de métrés. L'export utilise le modèle `.xlsx` intégré.
- Les devis fournisseurs et les alertes ne sont **jamais** réputés validés du seul fait de leur dépôt. Pas de signature, de dépôt automatique, de sélection automatique de prix, ni d'envoi d'e-mail automatique.
- **Ne pas considérer le ZIP de travail comme un dossier légalement conforme ou prêt au dépôt** : une revue technique, administrative, contractuelle et financière par SIE reste obligatoire.

## Organisation du code

```text
server.py                     API locale FastAPI, SQLite, traitement PDF/Excel, ZIP
static/index.html             HTML et CSS issus de la maquette
static/app.js                 Fonctions d'origine de la maquette
static/integration.js         Persistance et fonctionnalités réelles ajoutées
static/modele_DPGF_SIE.xlsx   Modèle DPGF intégré à la maquette d'origine
docs/                         Maquette et spécifications originales
tests/                        Tests de base de l'API
data/                         Base et documents créés à l'usage
```

## Tests automatisés

Après installation de `pytest` et `httpx` (`py -3 -m pip install pytest httpx`) :

```bash
python -m pytest tests -q
```

Les tests utilisent un répertoire temporaire, sans modifier les données métier. L'interface a également été vérifiée dans un navigateur de test avec navigation entre les 12 rubriques, création de consultation, gestion GO / NO GO, choix d'un lot, import d'un fichier et transfert d'une vigilance.

---

Projet Commande Entreprise 77 | IMT Atlantique • SIE | Développement pédagogique, novembre 2026.

## Rédaction assistée par IA (mémoire technique)

SIE a autorisé l'usage d'une API externe **pour les écrits uniquement**. Le module `redaction_ia.py` :

- indexe **localement** (BM25, sans service externe) les pièces écrites du DCE et les anciens mémoires SIE importés en catégorie « Mémoire technique » ;
- n'envoie à l'API que le libellé du sous-critère, les consignes saisies et une dizaine d'extraits courts — **jamais** de prix, DPGF, devis, bilans ni pièces de candidature ;
- impose la citation des sources `[S1]…` et l'écriture `[À COMPLÉTER : …]` quand une information manque ;
- signale automatiquement les sources inventées, les paragraphes non sourcés et les chiffres absents des sources ;
- n'insère rien dans le mémoire sans action de l'utilisateur ; le journal ne conserve que des métadonnées.

Configuration (la clé n'est jamais versionnée ni stockée en base) : créer `~/SIE_data/ia.env`

```
OPENAI_API_KEY=sk-...
# facultatif
OPENAI_MODEL=gpt-6.1-terra
OPENAI_BASE_URL=https://eu.api.openai.com/v1
```

puis relancer `LANCER_MAC.command`. Sans clé, l'outil fonctionne normalement, sans la rédaction IA.
