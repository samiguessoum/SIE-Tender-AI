"""Analyse structurée d'un DCE (dossier de consultation des entreprises).

Principe : on ne compte pas des mots-clés dans l'ordre alphabétique des fichiers.
1. On classe chaque pièce par type (RC, Q/R, CCAP, cadre de réponse, CCTP par lot, plans...).
2. On lit les pièces dans l'ordre de priorité : les questions-réponses modifient le RC,
   le RC prime pour la procédure, le CCAP complète (lieu, intervenants, clauses).
3. On extrait des CHAMPS (date limite, visite, lots, critères...) avec leur source
   (fichier + page + extrait). Ce qui n'est pas trouvé vaut « À vérifier ».

Dépendances : bibliothèque standard, python-docx, openpyxl ; PDF lus avec PyMuPDF (fitz)
ou, à défaut, pdftotext. Aucune IA, aucun appel réseau.
"""
from __future__ import annotations

import io
import json
import re
import shutil
import subprocess
import unicodedata
from datetime import date, datetime, timedelta
from pathlib import Path

A_VERIFIER = 'À vérifier'

# --------------------------------------------------------------------------- outils texte


def sans_accents(s: str) -> str:
    return ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn')


def norm(s: str) -> str:
    """Texte sur une ligne : espaces normalisés, apostrophes droites, ligatures dépliées."""
    for a, b in (('’', "'"), ('‘', "'"), ('\xa0', ' '), (' ', ' '), ('ﬀ', 'ff'), ('ﬁ', 'fi'), ('ﬂ', 'fl')):
        s = s.replace(a, b)
    return re.sub(r'\s+', ' ', s).strip()


def extrait_autour(texte: str, debut: int, fin: int, marge: int = 90) -> str:
    a, b = max(0, debut - marge), min(len(texte), fin + marge)
    return ('…' if a else '') + texte[a:b].strip() + ('…' if b < len(texte) else '')


MOIS = {m: i for i, m in enumerate(['janvier', 'fevrier', 'mars', 'avril', 'mai', 'juin', 'juillet',
                                     'aout', 'septembre', 'octobre', 'novembre', 'decembre'], 1)}


def champ(valeur, source=None, page=None, extrait=None, **extra):
    if valeur in (None, '', []):
        return {'valeur': A_VERIFIER, 'statut': 'a_verifier', 'source': None, 'page': None, 'extrait': None, **extra}
    return {'valeur': valeur, 'statut': 'extrait', 'source': source, 'page': page, 'extrait': extrait, **extra}


def _date_fr(jour, mois, annee):
    mois = sans_accents(str(mois)).lower().strip()
    m = int(mois) if mois.isdigit() else MOIS.get(mois)
    if not m:
        return None
    try:
        return date(int(annee), m, int(re.sub(r'\D', '', str(jour))))
    except ValueError:
        return None

# --------------------------------------------------------------------------- classification des pièces


TYPES = {
    # type : (priorité de lecture, libellé)
    'QR': (1, 'Questions-réponses'),
    'RC': (2, 'Règlement de consultation'),
    'CCAP': (3, 'CCAP'),
    'CRT': (4, 'Cadre de réponse technique'),
    'AE': (5, "Acte d'engagement"),
    'CCTC': (6, 'CCTC (clauses techniques communes)'),
    'CCTP': (7, 'CCTP'),
    'PLANNING': (8, 'Planning'),
    'DPGF': (9, 'DPGF / bordereau de prix'),
    'PGC': (10, 'PGC (sécurité)'),
    'ATTESTATION_VISITE': (11, 'Attestation de visite'),
    'RC_ANNEXE': (12, 'Annexe au RC'),
    'FORMULAIRE': (13, 'Formulaire de candidature'),
    'DIAGNOSTIC': (14, 'Diagnostic / rapport'),
    'AUTRE': (15, 'Autre pièce'),
    'PLAN': (20, 'Plan / visuel'),
    'ARCHIVE': (21, 'Archive ZIP'),
}

TEXTE_LISIBLE = {'.pdf', '.docx', '.xlsx', '.xlsm', '.txt', '.md', '.csv'}
NON_LUS = {'PLAN', 'ARCHIVE', 'DIAGNOSTIC', 'FORMULAIRE', 'RC_ANNEXE'}


def detecter_lot(chemin: str) -> str | None:
    s = sans_accents(chemin).lower().replace('_', ' ')
    nom = s.rsplit('/', 1)[-1]
    for cible in (nom, s):
        m = re.search(r'macro[ -]*lot[ -]*(\d+(?:\.\d+)?)', cible)
        if m:
            return 'ML' + m.group(1)
        m = re.search(r'(?<![a-z])lot[ -]*(\d+(?:\.\d+)?)', cible)
        if m:
            return m.group(1)
        m = re.search(r'(?<![a-z0-9])ml[ -]?(\d+)(?![0-9])', cible)
        if m:
            return 'ML' + m.group(1)
    return None


def classer(chemin: str) -> str:
    """Type d'une pièce d'après son chemin relatif (dossier + nom de fichier)."""
    p = sans_accents(chemin).lower().replace('_', ' ')
    nom = p.rsplit('/', 1)[-1]
    ext = '.' + nom.rsplit('.', 1)[-1] if '.' in nom else ''
    if ext == '.zip':
        return 'ARCHIVE'
    if ext in ('.png', '.jpg', '.jpeg', '.dwg', '.dxf', '.ifc', '.tif', '.tiff', '.gif'):
        return 'PLAN'
    if 'question' in nom and 'reponse' in nom:
        return 'QR'
    if re.search(r'\bannexe\b.*\brc\b', nom):
        return 'RC_ANNEXE'
    if re.search(r'(^|[ -])rc([ .-]|$)', nom) or re.search(r'reglement de (la )?consultation', nom):
        return 'RC'
    if 'ccap' in nom:
        return 'CCAP'
    if 'cadre de reponse' in nom or re.search(r'\bcrt\b', nom):
        return 'CRT'
    if 'attestation de visite' in nom:
        return 'ATTESTATION_VISITE'
    if re.search(r'(^|[ -])ae([ .-]|$)', nom) or "acte d'engagement" in nom or 'acte d engagement' in nom:
        return 'AE'
    if re.search(r'\b(dc1|dc2|dc4|dume)\b', nom):
        return 'FORMULAIRE'
    if re.search(r'\b(dpgf|cdpgf|bpu|dqe|dpu)\b', nom):
        return 'DPGF'
    if re.search(r'\bpgc\b', nom):
        return 'PGC'
    if 'planning' in nom:
        return 'PLANNING'
    if re.search(r'amiante|\bplomb\b|diagnostic|\brict\b|portance|pemd|reperage|geotechni|fiche technique', nom):
        return 'DIAGNOSTIC'
    if 'cctc' in nom:
        return 'CCTC'
    if 'cctp' in nom:
        return 'CCTP'
    if re.search(r'(^|/)(pg |plans?( |/)|visuels?)', p) or re.search(
            r'\bplans?\b|coupe|facade|carnet|nomenclature|synoptique|mqte|perspective|details?\b|mood board', nom):
        return 'PLAN'
    if 'cctp' in p and ext in ('.pdf', '.docx'):
        # pièce rangée dans un dossier « CCTP » sans en être un (notices, tableaux...)
        return 'CCTP' if re.search(r'\blot\b|cctp', nom) else 'AUTRE'
    return 'AUTRE'

# --------------------------------------------------------------------------- lecture du texte


def _pdf_pages(chemin: Path) -> list[str]:
    try:
        import fitz  # PyMuPDF
    except ImportError:
        fitz = None
    if fitz is not None:
        with fitz.open(str(chemin), filetype='pdf') as pdf:  # fichier stocké sans extension
            return [pdf[i].get_text('text') for i in range(min(len(pdf), 400))]
    if shutil.which('pdftotext'):
        out = subprocess.run(['pdftotext', '-l', '400', str(chemin), '-'], capture_output=True, timeout=120)
        pages = out.stdout.decode('utf-8', 'replace').split('\f')
        return pages[:-1] if pages and not pages[-1].strip() else pages
    return []


def pages_texte(chemin: Path, nom: str) -> list[str]:
    """Liste des pages de texte d'un document (une « page » par feuille Excel, une seule pour Word)."""
    ext = Path(nom).suffix.lower()
    try:
        if chemin.stat().st_size == 0:
            return []
        if ext == '.pdf':
            return _pdf_pages(chemin)
        if ext == '.docx':
            from docx import Document
            d = Document(io.BytesIO(chemin.read_bytes()))
            morceaux = [p.text for p in d.paragraphs if p.text.strip()]
            for t in d.tables:
                for row in t.rows:
                    vus, cells = set(), []
                    for c in row.cells:
                        if id(c._tc) in vus:
                            continue
                        vus.add(id(c._tc))
                        cells.append(c.text.strip())
                    if any(cells):
                        morceaux.append(' | '.join(cells))
            return ['\n'.join(morceaux)]
        if ext in ('.xlsx', '.xlsm'):
            from openpyxl import load_workbook
            wb = load_workbook(io.BytesIO(chemin.read_bytes()), read_only=True, data_only=True)
            pages = []
            for ws in wb.worksheets:
                lignes = []
                for i, row in enumerate(ws.iter_rows(values_only=True)):
                    if i > 5000:
                        break
                    vals = [str(v).strip() for v in row[:40] if v is not None and str(v).strip()]
                    if vals:
                        lignes.append(' | '.join(vals))
                pages.append('\n'.join(lignes))
            wb.close()
            return pages
        if ext in ('.txt', '.md', '.csv'):
            return [chemin.read_bytes()[:5_000_000].decode('utf-8', 'replace')]
    except Exception:
        return []
    return []


class Lecteur:
    """Lecture des pièces avec cache disque : le texte d'un fichier ne change pas (clé = SHA-256)."""

    def __init__(self, cache_dir: Path | None = None):
        self.cache_dir = cache_dir
        if cache_dir:
            cache_dir.mkdir(parents=True, exist_ok=True)

    def pages(self, doc: dict) -> list[str]:
        cle = doc.get('sha256')
        f = self.cache_dir / f'{cle}.json' if (self.cache_dir and cle) else None
        if f and f.exists():
            try:
                return json.loads(f.read_text('utf-8'))
            except ValueError:
                pass
        pages = pages_texte(Path(doc['storepath']), doc['filename'])
        if f:
            f.write_text(json.dumps(pages, ensure_ascii=False), 'utf-8')
        return pages

# --------------------------------------------------------------------------- recherche sourcée


class Corpus:
    """Textes normalisés par pièce et par page, avec recherche sourcée."""

    def __init__(self):
        self.docs: list[dict] = []

    def ajouter(self, relpath, type_, lot, pages):
        self.docs.append({'relpath': relpath, 'type': type_, 'lot': lot, 'pages': [norm(p) for p in pages]})

    def de_type(self, *types):
        return [d for t in types for d in self.docs if d['type'] == t]

    def chercher(self, motif, types, flags=re.I, groupe=1):
        """Première occurrence d'un motif dans les pièces des types donnés, dans l'ordre donné.
        Renvoie (valeur, fichier, page, extrait, match) ou None."""
        for d in self.de_type(*types):
            for i, page in enumerate(d['pages'], 1):
                m = re.search(motif, page, flags)
                if m:
                    val = m.group(groupe) if groupe is not None else m.group(0)
                    val = val.strip() if isinstance(val, str) else val
                    return val, d['relpath'], i, extrait_autour(page, m.start(), m.end()), m
        return None

# --------------------------------------------------------------------------- questions-réponses


RE_QR_ENTETE = re.compile(r'(?:^|\n)[ \t]*(\d{2}/\d{2}/\d{2,4})[ \t]*\n\s*(?:(\d{2}/\d{2}/\d{2,4})[ \t]*\n\s*)?(\d{1,3})[ \t]*\n')


def _date_qr(s):
    if not s:
        return None
    j, m, a = s.split('/')
    a = int(a) + 2000 if len(a) == 2 else int(a)
    try:
        return date(a, int(m), int(j)).isoformat()
    except ValueError:
        return None


def parser_qr(pages: list[str], relpath: str) -> list[dict]:
    """Découpe un fichier de questions-réponses en questions numérotées."""
    items = []
    if relpath.lower().endswith(('.xlsx', '.xlsm')):
        for p, page in enumerate(pages, 1):
            for ligne in page.split('\n'):
                cells = [c.strip() for c in ligne.split(' | ')]
                if len(cells) < 3 or not re.match(r'\d{4}-\d{2}-\d{2}', cells[0]):
                    continue
                k, date_r = 1, None
                if re.match(r'\d{4}-\d{2}-\d{2}', cells[1]):
                    date_r, k = cells[1][:10], 2
                if k < len(cells) and cells[k].isdigit():
                    q = cells[k + 1] if k + 1 < len(cells) else ''
                    r = ' '.join(cells[k + 2:])
                    items.append({'num': int(cells[k]), 'date_question': cells[0][:10], 'date_reponse': date_r,
                                  'question': norm(q), 'reponse': norm(r), 'texte': norm(q + ' ' + r),
                                  'source': relpath, 'page': p})
        return items
    for p, page in enumerate(pages, 1):
        heads = list(RE_QR_ENTETE.finditer(page))
        for k, m in enumerate(heads):
            fin = heads[k + 1].start() if k + 1 < len(heads) else len(page)
            num = int(m.group(3))
            if num > 500:
                continue
            items.append({'num': num, 'date_question': _date_qr(m.group(1)), 'date_reponse': _date_qr(m.group(2)),
                          'question': None, 'reponse': None, 'texte': norm(page[m.end():fin]),
                          'source': relpath, 'page': p})
    return items


def fusionner_qr(listes: list[list[dict]]) -> list[dict]:
    """Les Q/R sont souvent publiées en cumulatif (le dernier PDF reprend les précédents).
    Par numéro : version tableur d'abord (questions et réponses en colonnes distinctes) ;
    sinon la version PDF la plus courte parmi celles qui ont du contenu, car une version
    plus longue a souvent « avalé » la question voisine lors du découpage du tableau."""
    versions = {}
    for liste in listes:
        for it in liste:
            versions.setdefault(it['num'], []).append(it)
    out = []
    for num in sorted(versions):
        vs = versions[num]
        tab = [v for v in vs if v.get('question') is not None]
        if tab:
            choix = dict(tab[0], decoupage='tableur')
        else:
            pleins = [v for v in vs if len(v['texte']) >= 15]
            choix = dict(min(pleins, key=lambda v: len(v['texte'])) if pleins else max(vs, key=lambda v: len(v['texte'])),
                         decoupage='approximatif (PDF) : vérifier dans la source')
        out.append(choix)
    return out


def lots_cites(texte: str) -> list[str]:
    s = sans_accents(texte).lower()
    lots = set()
    for m in re.finditer(r'macro[ -]?lot\s*(\d+(?:\.\d+)?)', s):
        lots.add('ML' + m.group(1))
    for m in re.finditer(r'(?<!macro )(?<!macro-)\blot\s*(\d+(?:\.\d+)?)', s):
        lots.add(m.group(1))
    return sorted(lots)

# --------------------------------------------------------------------------- analyse


def analyser(documents: list[dict], cache_dir: Path | None = None, lots_retenus: list[str] | None = None) -> dict:
    """documents : lignes de la table `documents` (id, relpath, filename, storepath, size, sha256)."""
    lecteur = Lecteur(cache_dir)
    corpus = Corpus()
    inventaire, alertes = [], []
    vus_sha = {}
    # macOS fournit des noms en Unicode décomposé (NFD) : on uniformise pour que « é » soit toujours le même caractère.
    documents = [dict(d, relpath=unicodedata.normalize('NFC', d['relpath']),
                      filename=unicodedata.normalize('NFC', d.get('filename') or Path(d['relpath']).name)) for d in documents]

    for d in documents:
        t = classer(d['relpath'])
        e = {'id': d.get('id'), 'relpath': d['relpath'], 'type': t, 'type_libelle': TYPES[t][1],
             'lot': detecter_lot(d['relpath']), 'taille': d.get('size'), 'lu': False}
        inventaire.append(e)
        if d.get('size') == 0:
            alertes.append({'categorie': 'Complétude DCE', 'priorite': 'haute', 'titre': 'Fichier vide dans le DCE',
                            'detail': f"{d['relpath']} fait 0 octet : demander la pièce à l'acheteur.",
                            'source': d['relpath'], 'page': None})
        if d.get('sha256') and d.get('size'):
            if d['sha256'] in vus_sha:
                e['doublon_de'] = vus_sha[d['sha256']]
            else:
                vus_sha[d['sha256']] = d['relpath']

    # Lecture dans l'ordre de priorité ; plans, archives et diagnostics ne servent pas à la fiche.
    ordre = sorted(range(len(documents)), key=lambda i: (TYPES[inventaire[i]['type']][0], documents[i]['relpath']))
    pages_par_doc = {}
    for i in ordre:
        e, d = inventaire[i], documents[i]
        if e['type'] in NON_LUS or e.get('doublon_de') or Path(d['filename']).suffix.lower() not in TEXTE_LISIBLE:
            continue
        pages = lecteur.pages(d)
        pages_par_doc[i] = pages
        e['lu'], e['pages'] = True, len(pages)
        if d.get('size') and pages is not None and not any(p.strip() for p in pages):
            alertes.append({'categorie': 'Lecture', 'priorite': 'moyenne', 'titre': 'Pièce sans texte lisible (scan ?)',
                            'detail': f"{d['relpath']} : aucune couche texte, lecture humaine ou OCR nécessaire.",
                            'source': d['relpath'], 'page': None})
        corpus.ajouter(d['relpath'], e['type'], e['lot'], pages)

    fiche = {}
    RC, PROC = ['RC'], ['RC', 'CCAP']

    # --- Identification
    r = corpus.chercher(r'Consultation\s*n[°o]\s*:?\s*([A-Z0-9][A-Z0-9._/-]*\d[A-Z0-9._/-]*)', PROC)
    if not r:
        r = corpus.chercher(r'\b([A-Z]{1,5}\d{2}[-_]\d{2,5})\b', PROC, flags=0)
    fiche['reference'] = champ(*r[:4]) if r else champ(None)

    r = (corpus.chercher(r'prestations suivantes\s*:\s*(.{10,300}?)\s*(?:■|[ÉE]l[ée]ments cl[ée]|$)', PROC)
         or corpus.chercher(r'Objet du (?:contrat|march[ée])\s*:?\s*(.{10,250}?)\s*(?:Type de|■|$)', PROC))
    fiche['objet'] = champ(*r[:4]) if r else champ(None)

    r = corpus.chercher(r'Acheteur\s*:\s*(.{5,220}?)\s*(?:T[ée]l[ée]phone|La personne|■)', RC)
    fiche['acheteur'] = champ(re.sub(r'\s*Adresse\s*:\s*', ', ', r[0]).strip(' ,'), *r[1:4]) if r else champ(None)

    r = corpus.chercher(r'en charge du dossier est\s*:\s*(.{3,120}?)\s*(?:■|Description|$)', RC)
    tel = corpus.chercher(r'T[ée]l[ée]phone\s*:\s*(\+?[\d .()]{9,20}\d)', RC)
    fiche['contact'] = champ(r[0] + (f' — {tel[0]}' if tel else ''), *r[1:4]) if r else champ(None)

    r = corpus.chercher(r"(Appel d'offres (?:ouvert|restreint)|Proc[ée]dure adapt[ée]e|MAPA|Proc[ée]dure avec n[ée]gociation|"
                        r"Dialogue comp[ée]titif|March[ée] n[ée]goci[ée])", PROC)
    fiche['procedure'] = champ(*r[:4]) if r else champ(None)

    # --- Date limite : RC, puis modifications éventuelles par les questions-réponses
    date_rc = None
    r = corpus.chercher(r'limite de (?:remise|r[ée]ception).{0,400}?(\d{1,2})\s*/\s*(\d{1,2})\s*/\s*(\d{4})\s*'
                        r'(?:à|a)\s*(\d{1,2})\s*(?:h|heures)\s*(\d{2})?', RC, groupe=None)
    if r:
        m = r[4]
        d0 = _date_fr(m.group(1), m.group(2), m.group(3))
        if d0:
            date_rc = {'valeur': f"{d0.strftime('%d/%m/%Y')} à {int(m.group(4))}h{m.group(5) or '00'}",
                       'iso': f"{d0.isoformat()}T{int(m.group(4)):02d}:{m.group(5) or '00'}",
                       'source': r[1], 'page': r[2], 'extrait': r[3]}

    listes = [parser_qr(pages_par_doc[i], documents[i]['relpath']) for i in ordre
              if i in pages_par_doc and inventaire[i]['type'] == 'QR']
    qr_items = fusionner_qr(listes)

    date_finale, historique = (dict(date_rc) if date_rc else None), []
    for q in qr_items:
        m = re.search(r"date limite de (?:remise|r[ée]ception) des (?:offres|plis)[^.]{0,40}?"
                      r"(?:prolong[ée]e|report[ée]e|modifi[ée]e|fix[ée]e)[^0-9]{0,30}?(\d{1,2})(?:er)?\s*"
                      r"(?:/\s*(\d{1,2})\s*/\s*(\d{4})|\s+([a-zéû]+)\s+(\d{4}))\s*(?:à|a)\s*(\d{1,2})\s*h\s*(\d{2})?",
                      q['texte'], re.I)
        if not m:
            continue
        d1 = _date_fr(m.group(1), m.group(2) or m.group(4), m.group(3) or m.group(5))
        if not d1:
            continue
        if date_finale:
            historique.append({'valeur': date_finale['valeur'], 'source': date_finale['source'],
                               'page': date_finale['page'], 'statut': 'remplacée'})
        date_finale = {'valeur': f"{d1.strftime('%d/%m/%Y')} à {int(m.group(6))}h{m.group(7) or '00'}",
                       'iso': f"{d1.isoformat()}T{int(m.group(6)):02d}:{m.group(7) or '00'}",
                       'source': q['source'], 'page': q['page'],
                       'extrait': extrait_autour(q['texte'], m.start(), m.end()), 'question': q['num']}
    if date_finale:
        fiche['date_limite'] = champ(date_finale['valeur'], date_finale['source'], date_finale['page'],
                                     date_finale['extrait'], iso=date_finale['iso'], historique=historique)
        if historique:
            alertes.append({'categorie': 'Administratif', 'priorite': 'haute',
                            'titre': 'Date limite modifiée par les questions-réponses',
                            'detail': f"Le RC indique {historique[0]['valeur']} ; nouvelle date : {date_finale['valeur']} "
                                      f"(Q/R n°{date_finale.get('question')}).",
                            'source': date_finale['source'], 'page': date_finale['page']})
    else:
        fiche['date_limite'] = champ(None)

    r = corpus.chercher(r'(?:demandes?|questions?|renseignements)[^.]{0,80}?au plus tard\s*(\d{1,2})\s*jours?\s*avant la date limite de remise', RC, groupe=None)
    if r and date_finale:
        dl = datetime.fromisoformat(date_finale['iso']).date() - timedelta(days=int(r[4].group(1)))
        fiche['date_limite_questions'] = champ(f"{dl.strftime('%d/%m/%Y')} ({r[4].group(1)} jours avant la remise)", *r[1:4])
    elif r:
        fiche['date_limite_questions'] = champ(f"{r[4].group(1)} jours avant la date limite de remise", *r[1:4])
    else:
        fiche['date_limite_questions'] = champ(None)

    # --- Visite
    r = corpus.chercher(r'(doivent obligatoirement effectuer une visite|visite (?:du site |des lieux )?(?:est )?obligatoire)',
                        ['RC', 'CCAP', 'QR'], groupe=None)
    r_fac = corpus.chercher(r'visite (?:du site |des lieux )?(?:est )?(?:facultative|libre|non obligatoire)', PROC, groupe=None)
    visite = champ('oui', *r[1:4]) if r else (champ('non', *r_fac[1:4]) if r_fac else champ(None))
    creneaux, contacts, rdv = [], [], None
    for d in corpus.de_type('RC'):
        for page in d['pages']:
            for k in [m.start() for m in re.finditer('visite', page, re.I)]:
                zone = page[k:k + 1500]
                for m in re.finditer(r'(Lundi|Mardi|Mercredi|Jeudi|Vendredi|Samedi)\s+(\d{1,2})(?:er)?\s+([a-zéû]+)'
                                     r'(?:\s+(\d{4}))?\s+de\s+(\d{1,2}\s*h\s*\d{0,2})\s+à\s+(\d{1,2}\s*h\s*\d{0,2})', zone, re.I):
                    lib = f"{m.group(1)} {m.group(2)} {m.group(3)}{(' ' + m.group(4)) if m.group(4) else ''} de {m.group(5)} à {m.group(6)}"
                    if lib not in creneaux:
                        creneaux.append(lib)
                for m in re.finditer(r'[\w.+-]+@[\w-]+\.[a-z.]+', zone):
                    if m.group(0) not in contacts and creneaux:
                        contacts.append(m.group(0))
                mr = re.search(r'au plus tard\s*(\d+)\s*h(?:eures)?\s*avant', zone)
                if mr and not rdv:
                    rdv = f'Rendez-vous au plus tard {mr.group(1)} h avant'
            if creneaux:
                break
        if creneaux:
            break
    if not contacts:
        for d in corpus.de_type('RC'):
            for page in d['pages']:
                k = page.lower().find('personne à contacter')
                if k != -1:
                    contacts = re.findall(r'[\w.+-]+@[\w-]+\.[a-z.]+', page[k:k + 900])
                    break
    visite.update(creneaux=creneaux, contacts=contacts, rendez_vous=rdv,
                  attestation=any(e['type'] == 'ATTESTATION_VISITE' for e in inventaire)
                  or bool(corpus.chercher(r'attestation de visite', RC)))
    fiche['visite'] = visite
    if visite['valeur'] == 'oui':
        alertes.append({'categorie': 'Administratif', 'priorite': 'haute', 'titre': 'Visite obligatoire',
                        'detail': 'Visite du site obligatoire'
                                  + (f" ({len(creneaux)} créneaux : " + '; '.join(creneaux) + ')' if creneaux else '')
                                  + ('. ' + rdv if rdv else '')
                                  + ". Désigner un responsable et joindre l'attestation signée à l'offre.",
                        'source': visite['source'], 'page': visite['page']})

    # --- Clauses générales
    r = corpus.chercher(r'validit[ée] des offres est de\s*(\d+)\s*jours', PROC)
    fiche['validite_offres'] = champ(f'{r[0]} jours', *r[1:4]) if r else champ(None)
    r = corpus.chercher(r"D[ée]lai\s*(?:d'ex[ée]cution)?\s*:?\s*(\d+\s*(?:mois|semaines|jours))", PROC)
    fiche['delai_execution'] = champ(*r[:4]) if r else champ(None)
    r1 = corpus.chercher(r'(prix (?:globaux et )?forfaitaires?|prix unitaires|prix mixtes)', PROC)
    r2 = corpus.chercher(r'\b(r[ée]visables?|actualisables?|fermes? et d[ée]finitifs?)\b', RC)
    fiche['forme_prix'] = (champ(r1[0][0].upper() + r1[0][1:] + (f', {r2[0].lower()}' if r2 else ''), *r1[1:4])
                           if r1 else champ(None))
    r = corpus.chercher(r'variantes?[^.]{0,80}?(ne sont pas autoris[ée]es|sont autoris[ée]es|sont interdites|non autoris[ée]es|'
                        r'sont admises|ne sont pas admises)', PROC)
    fiche['variantes'] = (champ('Non autorisées' if re.search(r'pas|interdit|non', r[0]) else 'Autorisées', *r[1:4])
                          if r else champ(None))

    r = (corpus.chercher(r"lieu d'ex[ée]cution des prestations est\s*:\s*(?:■\s*)?(.{5,140}?)\s*(?:■|Pi[èe]ces contractuelles|$)",
                         ['CCAP', 'RC'])
         or corpus.chercher(r"Lieu d'ex[ée]cution\s*:\s*(?:■\s*)?(.{5,140}?)\s*(?:■|$)", ['CCAP', 'RC']))
    fiche['lieu'] = champ(*r[:4]) if r else champ(None)

    # --- Intervenants
    stop = r"\s*(?=•|■|-\s|Ma[iî]tre d|Conducteur|Coordinat|Contr[ôo]leur|OPC\s*:|Les coordonn|$)"

    def intervenant(motif):
        res = corpus.chercher(motif + r"\s*:\s*(.{2,120}?)" + stop, PROC)
        return champ(*res[:4]) if res else champ(None)

    fiche['moa'] = intervenant(r"Ma[iî]tre d'ouvrage")
    fiche['moe'] = intervenant(r"Ma[iî]tre d'(?:œ|oe)uvre")
    fiche['conducteur_operation'] = intervenant(r"Conducteur d'op[ée]ration")
    fiche['sps'] = intervenant(r'Coordinat(?:eur|ion) (?:SPS|S\.P\.S\.?)')
    fiche['controleur_technique'] = intervenant(r'Contr[ôo]leur technique')
    fiche['opc'] = intervenant(r'\bOPC')
    fiche['ssi'] = intervenant(r'Coordinat(?:eur|ion) SSI')
    arch = None
    if fiche['moe']['statut'] == 'extrait':
        m = re.search(r"([A-Z][\w&' -]{1,40}?Architectes?)", fiche['moe']['valeur'])
        if m:
            arch = champ(m.group(1).strip(), fiche['moe']['source'], fiche['moe']['page'], fiche['moe']['extrait'])
    if not arch:
        r = corpus.chercher(r'Architecte\s*:\s*(.{2,80}?)\s*(?:■|•|$)', PROC)
        arch = champ(*r[:4]) if r else champ(None)
    fiche['architecte'] = arch

    # --- Lots (tous, même ceux que SIE ne retiendra pas)
    lots, src_lots = [], None
    fin_lot = r"(?=\s+(?:Macro[- ]?lot|Lot\s*\d|\d{8}-\d|■|Justification)|\s*$)"
    for d in corpus.de_type('RC'):
        for i, page in enumerate(d['pages'], 1):
            for m in re.finditer(r"Macro[- ]?lot\s*(\d+)\s+(\d+\.\d+)\s+(R[ée]alisation.+?)" + fin_lot, page, re.I):
                lots.append({'numero': m.group(2), 'parent': 'ML' + m.group(1), 'intitule': m.group(3).strip(' .')})
            for m in re.finditer(r"(?<![Mm]acro )\bLot\s*(\d+)\s+\1\s+(R[ée]alisation.+?)" + fin_lot, page):
                lots.append({'numero': m.group(1), 'parent': None, 'intitule': m.group(2).strip(' .')})
            if lots:
                src_lots = (d['relpath'], i)
                break
        if lots:
            break
    if not lots:  # repli : un acte d'engagement par lot
        for e in inventaire:
            if e['type'] == 'AE' and e['lot'] and not any(l['numero'] == e['lot'] for l in lots):
                lots.append({'numero': e['lot'], 'parent': None, 'intitule': A_VERIFIER})
                src_lots = (e['relpath'], None)
    macro = {}
    for l in lots:
        if l['parent']:
            macro.setdefault(l['parent'], []).append(l)
    lots_fiche = [{'numero': k.replace('ML', 'Macro-lot '), 'code': k,
                   'intitule': ' / '.join(f"{s['numero']} {s['intitule']}" for s in macro[k]),
                   'sous_lots': macro[k], 'retenu': False} for k in sorted(macro)]
    lots_fiche += [{'numero': f"Lot {l['numero']}", 'code': l['numero'], 'intitule': l['intitule'],
                    'sous_lots': [], 'retenu': False} for l in lots if not l['parent']]
    fiche['lots'] = {'valeur': lots_fiche, 'statut': 'extrait' if lots_fiche else 'a_verifier',
                     'source': src_lots[0] if src_lots else None, 'page': src_lots[1] if src_lots else None}
    r = corpus.chercher(r"(aucune offre ne pourra [^.]{0,160}?sous-lots?[^.]*\.)", RC)
    if r:
        alertes.append({'categorie': 'Administratif', 'priorite': 'haute', 'titre': "Règle d'allotissement",
                        'detail': r[0], 'source': r[1], 'page': r[2]})

    # --- Critères : cadre de réponse (en points) en priorité, sinon RC (en %)
    criteres = []
    for d in corpus.de_type('CRT'):
        for i, page in enumerate(d['pages'], 1):
            for m in re.finditer(r'CRIT[ÈE]RE\s*(\d)\s*[–-]\s*(.+?)\s*\((\d+)\s*points?\)', page, re.I):
                criteres.append({'code': m.group(1), 'libelle': m.group(2).strip().capitalize(), 'poids': int(m.group(3)),
                                 'unite': 'points', 'sous_criteres': [], 'source': d['relpath'], 'page': i})
            for m in re.finditer(r'Sous-crit[èe]re\s*(\d)\.(\d)\s*:\s*(.+?)\s*\((\d+)\s*points?\)', page, re.I):
                parent = next((c for c in criteres if c['code'] == m.group(1)), None)
                if parent:
                    parent['sous_criteres'].append({'code': f'{m.group(1)}.{m.group(2)}', 'libelle': m.group(3).strip(),
                                                    'poids': int(m.group(4))})
    if not criteres:
        for d in corpus.de_type('RC'):
            for i, page in enumerate(d['pages'], 1):
                for m in re.finditer(r'Crit[èe]re\s*(\d)\s*:\s*(.+?)\s*(\d{1,3})\s*%', page):
                    criteres.append({'code': m.group(1), 'libelle': m.group(2).strip(), 'poids': int(m.group(3)),
                                     'unite': '%', 'sous_criteres': [], 'source': d['relpath'], 'page': i})
    fiche['criteres'] = {'valeur': criteres, 'statut': 'extrait' if criteres else 'a_verifier',
                         'source': criteres[0]['source'] if criteres else None, 'page': criteres[0]['page'] if criteres else None}

    crt = corpus.de_type('CRT')
    fiche['trame_memoire'] = (champ('Cadre de réponse imposé : ' + crt[0]['relpath'].rsplit('/', 1)[-1], crt[0]['relpath'], 1)
                              if crt else champ(None))
    r = corpus.chercher(r'(cadre de r[ée]ponse[^.]{0,250}?sous peine (?:de rejet|d.irr[ée]gularit[ée])[^.]*\.)', ['RC', 'CRT'])
    if r:
        alertes.append({'categorie': 'Administratif', 'priorite': 'haute', 'titre': 'Cadre de réponse obligatoire',
                        'detail': r[0], 'source': r[1], 'page': r[2]})

    # --- Pièces exigées (candidature / offre) repérées dans le RC
    PIECES = [
        ('candidature', 'DC1 (lettre de candidature) ou DUME', r'\bDC1\b'),
        ('candidature', 'DC2 (déclaration du candidat) ou DUME', r'\bDC2\b'),
        ('candidature', "Chiffre d'affaires des 3 derniers exercices", r"chiffre d'affaires"),
        ('candidature', 'Annexe au RC : capacités techniques et professionnelles', r'Annexe\s*\d+\s*au (?:RC|R[èe]glement)'),
        ('candidature', 'Certificats de qualifications professionnelles', r'qualifications? professionnelles'),
        ('candidature', 'Certificats de qualité', r'certificats? de qualit[ée]'),
        ('offre', 'Attestation de visite signée', r'attestation de visite'),
        ('offre', 'Cadre de réponse technique', r'cadre de r[ée]ponse'),
        ('offre', 'DPGF', r'\bDPGF\b'),
        ('offre', "Acte d'engagement", r"acte d'engagement"),
        ('offre', "Planning d'exécution détaillé", r"planning d'ex[ée]cution|planning d[ée]taill[ée]"),
        ('offre', 'Mémoire technique', r'm[ée]moire technique'),
    ]
    pieces = []
    for groupe, libelle, motif in PIECES:
        r = corpus.chercher(motif, RC, groupe=None)
        if not r:
            continue
        zones = [page[m.start():m.end() + 300].lower() for d in corpus.de_type('RC') for page in d['pages']
                 for m in re.finditer(motif, page, re.I)]
        pieces.append({'groupe': groupe, 'piece': libelle,
                       'obligatoire': not any('facultatif' in z[:len(libelle) + 25] for z in zones),
                       'eliminatoire': any(re.search(r'sous peine de rejet|sous peine d.irr', z) for z in zones),
                       'source': r[1], 'page': r[2], 'extrait': r[3]})
    fiche['pieces_exigees'] = {'valeur': pieces, 'statut': 'extrait' if pieces else 'a_verifier'}

    # --- Heures d'insertion (clause sociale)
    # Le tableau « élément du contrat / nombre d'heures » peut être restitué ligne par ligne (pdftotext)
    # ou colonne par colonne (PyMuPDF). On relève donc les libellés et les valeurs DANS L'ORDRE puis on les
    # apparie un à un ; si les deux listes n'ont pas la même longueur, on ne devine pas : « À vérifier ».
    heures = []
    for d in corpus.de_type('CCAP', 'RC'):
        for i, page in enumerate(d['pages'], 1):
            for k in [m.end() for m in re.finditer(r"nombre d'heures d'insertion", page, re.I)]:
                zone = re.split(r'■|Clause environnementale', page[k:k + 700])[0]
                motif_lib = r'((?:Macro[- ]?lot\s*\d+|Lot\s*\d+)(?:\s*\([^)]{0,40}\))?)'
                libelles = [m.group(1).strip() for m in re.finditer(motif_lib, zone, re.I)]
                reste = re.sub(motif_lib, ' | ', zone, flags=re.I)  # « Lot 3 600 heures » ne doit pas donner 3 600
                valeurs = [int(re.sub(r'\D', '', m.group(1))) for m in re.finditer(r'(\d{1,3}(?:[  ]\d{3})*)\s*heures', reste)]
                if libelles and len(libelles) == len(valeurs):
                    heures = [{'element': l, 'heures': v, 'source': d['relpath'], 'page': i} for l, v in zip(libelles, valeurs)]
                    break
            if heures:
                break
        if heures:
            break
    fiche['heures_insertion'] = {'valeur': heures, 'statut': 'extrait' if heures else 'a_verifier'}

    # --- Vigilances issues des questions-réponses
    vigilances = []
    for q in qr_items:
        t = q['texte']
        motifs = [lib for lib, motif in (
            ('DCE modifié', r'pi[èe]ces? ajout[ée]es? au DCE'),
            ('Exigence', r'exig[ée]e?s?\b|obligatoire'),
            ('Correction du DCE', r'coquille|erreur'),
            ('Prestation à prévoir', r'pr[ée]voir|à la charge|\bdoit\b|devra'),
            ('Délai', r'prolong|report'),
            ('Variante', r'variante'),
        ) if re.search(motif, t, re.I)]
        vigilances.append({'question': q['num'], 'texte': t[:700], 'lots': lots_cites(t), 'motifs': motifs,
                           'source': q['source'], 'page': q['page'], 'date_reponse': q.get('date_reponse')})
    if fiche['variantes']['valeur'] == 'Non autorisées':
        qv = [v for v in vigilances if 'Variante' in v['motifs']
              and re.search(r'variante[^.]{0,160}(peut|possible|admise|propos)', v['texte'], re.I)]
        if qv:
            alertes.append({'categorie': 'Administratif', 'priorite': 'haute', 'titre': 'Contradiction sur les variantes',
                            'detail': 'Le RC interdit les variantes, mais les Q/R n° ' + ', '.join(str(v['question']) for v in qv)
                                      + ' en évoquent sous conditions. Clarifier avant de chiffrer une variante.',
                            'source': qv[0]['source'], 'page': qv[0]['page']})
    for v in vigilances:
        if 'Exigence' in v['motifs'] and re.search(r'qualification', v['texte'], re.I):
            alertes.append({'categorie': 'Administratif', 'priorite': 'haute', 'titre': f"Qualification exigée (Q/R n°{v['question']})",
                            'detail': v['texte'][:400] + (f" — lots cités : {', '.join(v['lots'])}" if v['lots'] else ''),
                            'source': v['source'], 'page': v['page'], 'lots': v['lots']})
        if 'DCE modifié' in v['motifs']:
            alertes.append({'categorie': 'Complétude DCE', 'priorite': 'moyenne',
                            'titre': f"Pièces ajoutées au DCE (Q/R n°{v['question']})",
                            'detail': v['texte'][:300] + ' — vérifier que la version importée contient ces pièces.',
                            'source': v['source'], 'page': v['page']})
    if lots_retenus:
        cibles = set(lots_retenus)
        for v in vigilances:
            v['concerne_lot_retenu'] = bool(cibles & set(v['lots']))

    trouves = [k for k, v in fiche.items() if isinstance(v, dict) and v.get('statut') == 'extrait']
    manquants = [k for k, v in fiche.items() if isinstance(v, dict) and v.get('statut') == 'a_verifier']
    par_type = {}
    for e in inventaire:
        par_type[e['type']] = par_type.get(e['type'], 0) + 1
    return {
        'fiche': fiche,
        'questions_reponses': qr_items,
        'vigilances_qr': vigilances,
        'alertes': alertes,
        'inventaire': inventaire,
        'synthese': {'documents': len(inventaire), 'documents_lus': sum(1 for e in inventaire if e.get('lu')),
                     'par_type': par_type, 'champs_extraits': trouves, 'champs_a_verifier': manquants,
                     'questions_reponses': len(qr_items), 'alertes': len(alertes),
                     'doublons': sum(1 for e in inventaire if e.get('doublon_de'))},
        'avertissement': "Extraction par règles, sans IA. Chaque valeur porte sa source : la vérifier dans la pièce avant "
                         "de l'utiliser. Une valeur « À vérifier » n'a pas été trouvée et doit être saisie à la main.",
    }


def fiche_pour_interface(resultat: dict) -> dict:
    """Champs au format de la fiche de renseignement de l'interface (state.fiches[id])."""
    f = resultat['fiche']

    def v(k):
        c = f.get(k) or {}
        return c.get('valeur') if c.get('statut') == 'extrait' else ''

    visite = f.get('visite') or {}
    oui = lambda x: 'oui' if x else 'verifier'
    tri = 'oui' if visite.get('valeur') == 'oui' else ('non' if visite.get('valeur') == 'non' else 'verifier')
    sources = [f"{k} : {c['source'].rsplit('/', 1)[-1]}" + (f" p.{c['page']}" if c.get('page') else '')
               for k, c in f.items() if isinstance(c, dict) and c.get('statut') == 'extrait' and c.get('source')]
    return {
        'intitule': v('objet'), 'reference': v('reference'), 'objet': v('objet'), 'lieu': v('lieu'),
        'dateLimite': v('date_limite'), 'questions': v('date_limite_questions'),
        'visiteDate': '; '.join(visite.get('creneaux') or []),
        'acheteur': v('acheteur'), 'moe': v('moe'), 'architecte': v('architecte'), 'sps': v('sps'), 'ssi': v('ssi'),
        'visiteCondition': tri, 'visiteObligatoire': tri,
        'visiteRdv': oui(visite.get('rendez_vous')), 'ficheVisite': oui(visite.get('attestation')),
        'visiteContact': ', '.join(visite.get('contacts') or []), 'contact': v('contact'),
        'lots': [{'numero': l['numero'], 'intitule': l['intitule'], 'retenu': False}
                 for l in (f.get('lots') or {}).get('valeur') or []],
        'sources': '\n'.join(sources),
    }
