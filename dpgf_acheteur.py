"""DPGF de l'acheteur : lecture de la structure, saisie des quantités et prix, génération du fichier à remettre.

Pourquoi ce module existe
-------------------------
La DPGF remise à l'acheteur est SON classeur (souvent .xlsm, avec macros, logos, liens externes
et une feuille de récapitulatif). Dans un marché forfaitaire, les colonnes Quantité, Prix unitaire
et Prix total sont vides : c'est l'entreprise qui les remplit, ainsi que les sous-totaux et le total.

Règles de conception
--------------------
* On ne réenregistre JAMAIS le classeur avec openpyxl : il supprime les images et peut abîmer
  les macros. On modifie uniquement le XML de la feuille de prix ; toutes les autres parties du
  fichier sont recopiées octet pour octet.
* Prix total d'un poste : formule  = Quantité × PU.
* Sous-totaux : SOUS.TOTAL(9; …), qui ignore les autres SOUS.TOTAL de la plage : aucun double compte,
  même quand le bas du tableau répète des sous-totaux. Total du lot : SOMMEPROD(Quantités; PU).
* Chaque formule reçoit aussi sa valeur calculée (aperçus, conversions PDF) et le classeur est
  marqué « recalcul complet à l'ouverture » pour Excel.
* Rien n'est inventé : un poste sans quantité ou sans prix reste vide et apparaît dans les contrôles.
"""
from __future__ import annotations

import difflib
import io
import posixpath
import re
import unicodedata
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

MENTIONS = {'SO', 'S.O', 'S.O.', 'SANS OBJET', 'PM', 'P.M', 'P.M.', 'POUR MEMOIRE', 'POUR MÉMOIRE', 'INCLUS', 'NC'}

# --------------------------------------------------------------------------- outils


def _sans_accents(s: str) -> str:
    return ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn')


def _cle(s) -> str:
    s = _sans_accents(str(s or '')).lower()
    return re.sub(r'[^a-z0-9]+', ' ', s).strip()


def col_lettre(n: int) -> str:
    s = ''
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def col_index(lettres: str) -> int:
    n = 0
    for ch in lettres:
        n = n * 26 + ord(ch) - 64
    return n


def _nombre(v):
    if v is None or v == '':
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).replace('\xa0', '').replace(' ', '').replace(',', '.')
    try:
        return float(s)
    except ValueError:
        return None

# --------------------------------------------------------------------------- lecture de la structure


ENTETES = {
    'numero': r'^(n|n°|no|num|numero|n prix|article|art|repere|ref|code|item)$',
    'designation': r'designation|libelle|description',
    'unite': r'^(u|unite|unites|un)$',
    'qte': r'^(q|qte|qt|quantite|quantites)$',
    'pu': r'^(pu|p\.u\.?|pu ht|prix unitaire|prix unitaire ht|pu \(?€?\s*ht\)?)',
    'total': r'(prix )?total|montant|^pt$|^pt ht$',
}


def _trouver_entete(lignes):
    """lignes : liste de (numéro de ligne Excel, [valeurs]). Renvoie (ligne d'en-tête, {rôle: colonne})."""
    for r, vals in lignes[:60]:
        roles = {}
        for c, v in enumerate(vals, 1):
            if v is None:
                continue
            t = _cle(v)
            for role, motif in ENTETES.items():
                if role not in roles and re.search(motif, t):
                    roles[role] = c
                    break
        if {'designation', 'unite', 'qte', 'pu'} <= roles.keys():
            return r, roles
    return None, None


def lire(chemin: str | Path) -> dict:
    """Structure de la DPGF : feuille de prix, colonnes, lignes typées, sections, sous-totaux et total."""
    from openpyxl import load_workbook
    donnees = Path(chemin).read_bytes()
    wb_f = load_workbook(io.BytesIO(donnees), read_only=True, data_only=False)
    wb_v = load_workbook(io.BytesIO(donnees), read_only=True, data_only=True)
    feuille, entete, roles, brut, cache = None, None, None, [], []
    for ws in wb_f.worksheets:
        if ws.sheet_state != 'visible':
            continue
        lignes = []
        for i, row in enumerate(ws.iter_rows(max_row=3000, max_col=20, values_only=True), 1):
            lignes.append((i, list(row)))
        r, ro = _trouver_entete(lignes)
        if r:
            feuille, entete, roles, brut = ws.title, r, ro, lignes
            cache = [list(row) for row in wb_v[ws.title].iter_rows(max_row=3000, max_col=20, values_only=True)]
            break
    wb_f.close()
    wb_v.close()
    if not feuille:
        raise ValueError("Aucune feuille de prix reconnue (en-têtes Désignation / Unité / Quantité / PU introuvables).")

    def val(i, role, source='f'):
        c = roles.get(role)
        if not c:
            return None
        tab = brut[i - 1][1] if source == 'f' else (cache[i - 1] if i - 1 < len(cache) else [])
        return tab[c - 1] if c - 1 < len(tab) else None

    derniere = max((r for r, vals in brut if any(v not in (None, '') for v in vals[:max(roles.values())])), default=entete)
    lignes = []
    for r in range(entete + 1, derniere + 1):
        num, des_f, unite = val(r, 'numero'), val(r, 'designation'), val(r, 'unite')
        des = val(r, 'designation', 'v') if isinstance(des_f, str) and des_f.startswith('=') else des_f
        num = '' if num is None else str(num).strip()
        unite = '' if unite is None else str(unite).strip()
        des = '' if des is None else str(des).replace('\xa0', ' ').strip()
        if not num and 'numero' not in roles:   # numéro collé dans la désignation : « 1.1    Consignation… »
            m = re.match(r'^(\d+(?:\.\d+)*)\.?\s{2,}(\S.*)$', des)
            if m:
                num, des = m.group(1), m.group(2).strip()
        ligne = {'row': r, 'numero': num, 'designation': des, 'unite': unite,
                 'qte': _nombre(val(r, 'qte')), 'pu': _nombre(val(r, 'pu'))}
        texte_f = des_f if isinstance(des_f, str) else ''
        refs = [int(x) for x in re.findall(r'\b[A-Z]{1,2}(\d+)\b', texte_f[1:])] if texte_f.startswith('=') else []
        if texte_f.startswith('=') and refs and not unite and not re.search(r'sous[ -]?total', texte_f, re.I):
            ligne['type'] = 'rappel'      # reprend le libellé d'une autre ligne (ex. =CONCATENATE(A251;"";B251))
            ligne['ref'] = refs[0]
        elif re.search(r'sous[ -]?total', texte_f, re.I) or re.match(r'sous[ -]?total', des, re.I):
            ligne['type'] = 'sous_total'
            ligne['ref'] = refs[0] if refs else None
        elif re.search(r'\btotal\b', des, re.I) and not unite:
            ligne['type'] = 'total'
        elif unite and _cle(unite).upper() in {_cle(m).upper() for m in MENTIONS}:
            ligne['type'] = 'mention'     # SO (sans objet), PM (pour mémoire)...
        elif unite:
            ligne['type'] = 'poste'
        elif num and des:
            ligne['type'] = 'titre'
            ligne['niveau'] = num.count('.') + 1
        elif des:
            ligne['type'] = 'texte'
        else:
            continue
        lignes.append(ligne)
    # Un texte sans numéro référencé par un « Sous total » est un titre de section (ex. « EXE »)
    cibles = {l.get('ref') for l in lignes if l['type'] == 'sous_total'}
    for l in lignes:
        if l['type'] == 'texte' and l['row'] in cibles:
            l['type'], l['niveau'] = 'titre', None
    # Rattachement de chaque poste à sa section la plus fine (pour l'affichage et les contrôles)
    titre_courant = []
    for l in lignes:
        if l['type'] == 'titre' and l.get('niveau'):
            titre_courant = [t for t in titre_courant if t['niveau'] < l['niveau']] + [l]
        elif l['type'] in ('poste', 'mention'):
            l['section'] = titre_courant[-1]['numero'] if titre_courant else ''
    return {'feuille': feuille, 'entete': entete, 'colonnes': {k: col_lettre(v) for k, v in roles.items()},
            'derniere_ligne': derniere, 'lignes': lignes}


def plages_sous_totaux(structure: dict) -> dict:
    """row du sous-total / total -> (première ligne, dernière ligne) additionnées."""
    lignes = structure['lignes']
    par_row = {l['row']: l for l in lignes}
    titres = [l for l in lignes if l['type'] == 'titre']
    plages = {}
    for l in lignes:
        if l['type'] == 'sous_total' and l.get('ref') in par_row:
            h = par_row[l['ref']]
            fin = l['row'] - 1 if l['row'] > h['row'] else structure['derniere_ligne']
            if h.get('niveau'):
                suivants = [t['row'] for t in titres if t['row'] > h['row'] and t.get('niveau') and t['niveau'] <= h['niveau']]
                if suivants:
                    fin = min(fin, suivants[0] - 1)
            plages[l['row']] = (h['row'] + 1, fin)
    for l in lignes:
        if l['type'] == 'rappel' and l.get('ref') in plages:
            plages[l['row']] = plages[l['ref']]
        elif l['type'] == 'total':
            plages[l['row']] = (structure['entete'] + 1, l['row'] - 1)
    return plages

# --------------------------------------------------------------------------- calculs et contrôles


def calculer(structure: dict, saisies: dict) -> dict:
    """saisies : {row: {'qte': float|None, 'pu': float|None}}. Montants, sous-totaux et contrôles."""
    montants = {}
    for l in structure['lignes']:
        if l['type'] in ('poste', 'mention'):
            s = saisies.get(l['row']) or {}
            q, p = s.get('qte'), s.get('pu')
            if q is not None and p is not None:
                montants[l['row']] = round(q * p, 2)
    plages = plages_sous_totaux(structure)
    totaux = {row: round(sum(v for r, v in montants.items() if a <= r <= b), 2) for row, (a, b) in plages.items()}
    sans_qte, sans_pu, mentions_chiffrees, negatifs = [], [], [], []
    for l in structure['lignes']:
        s = saisies.get(l['row']) or {}
        if l['type'] == 'poste':
            if s.get('qte') is None:
                sans_qte.append(l['row'])
            if s.get('pu') is None:
                sans_pu.append(l['row'])
        if l['type'] == 'mention' and (s.get('qte') or s.get('pu')):
            mentions_chiffrees.append(l['row'])
        if (s.get('qte') or 0) < 0 or (s.get('pu') or 0) < 0:
            negatifs.append(l['row'])
    total_rows = [l['row'] for l in structure['lignes'] if l['type'] == 'total']
    postes = [l for l in structure['lignes'] if l['type'] == 'poste']
    return {
        'montants': montants, 'totaux': totaux,
        'total_general': totaux.get(total_rows[0]) if total_rows else round(sum(montants.values()), 2),
        'postes': len(postes), 'postes_complets': sum(1 for l in postes if l['row'] in montants),
        'sans_quantite': sans_qte, 'sans_prix': sans_pu, 'mentions_chiffrees': mentions_chiffrees, 'negatifs': negatifs,
        'pret': not sans_qte and not sans_pu and not negatifs,
    }

# --------------------------------------------------------------------------- rapprochement avec les métrés / prix


def rapprocher(structure: dict, sources: list[dict], seuil: float = 0.82) -> list[dict]:
    """Propose, pour chaque poste, la ligne source (métré ou prix) correspondante. Jamais appliqué automatiquement.
    sources : [{reference, designation, unite, quantite, pu, origine}]"""
    propositions = []
    par_ref = {}
    for s in sources:
        if s.get('reference'):
            par_ref.setdefault(str(s['reference']).strip().rstrip('.'), []).append(s)
    for l in structure['lignes']:
        if l['type'] not in ('poste', 'mention'):
            continue
        meilleur, score, mode = None, 0.0, None
        if l['numero'] and l['numero'].rstrip('.') in par_ref:
            meilleur, score, mode = par_ref[l['numero'].rstrip('.')][0], 1.0, 'numéro identique'
        else:
            cle = _cle(l['designation'])
            for s in sources:
                r = difflib.SequenceMatcher(None, cle, _cle(s.get('designation'))).ratio()
                if r > score:
                    meilleur, score, mode = s, r, 'désignation proche'
        if meilleur and score >= seuil:
            u1, u2 = _cle(l['unite']), _cle(meilleur.get('unite'))
            propositions.append({'row': l['row'], 'numero': l['numero'], 'designation': l['designation'], 'unite': l['unite'],
                                 'source': meilleur, 'score': round(score, 2), 'mode': mode,
                                 'unite_differente': bool(u1 and u2 and u1 != u2)})
    return propositions

# --------------------------------------------------------------------------- génération du fichier


def _chemin_feuille(z: zipfile.ZipFile, nom_feuille: str) -> str:
    wb = z.read('xl/workbook.xml').decode('utf-8')
    rels = z.read('xl/_rels/workbook.xml.rels').decode('utf-8')
    for m in re.finditer(r'<sheet\b[^>]*>', wb):
        tag = m.group(0)
        nom = re.search(r'name="([^"]*)"', tag).group(1)
        if nom.replace('&amp;', '&').replace('&apos;', "'") == nom_feuille:
            rid = re.search(r'r:id="([^"]+)"', tag).group(1)
            cible = re.search(r'<Relationship\b[^>]*Id="%s"[^>]*>' % re.escape(rid), rels).group(0)
            t = re.search(r'Target="([^"]+)"', cible).group(1)
            return t.lstrip('/') if t.startswith('/') else posixpath.normpath(posixpath.join('xl', t))
    raise ValueError(f'Feuille introuvable : {nom_feuille}')


def _fmt(v: float) -> str:
    return repr(float(v)) if v != int(v) else str(int(v))


def _cellule(ref: str, attrs: str, valeur=None, formule=None) -> str:
    attrs = re.sub(r'\s+t="[^"]*"', '', attrs or '')   # le type « chaîne » éventuel ne s'applique plus
    inner = ''
    if formule is not None:
        inner += f'<f>{escape(formule)}</f>'
    if valeur is not None:
        inner += f'<v>{_fmt(valeur)}</v>'
    return f'<c r="{ref}"{attrs}>{inner}</c>' if inner else f'<c r="{ref}"{attrs}/>'


def _modifier_ligne(xml_ligne: str, r: int, cellules: dict) -> str:
    """cellules : {lettre: (valeur, formule)} ; insère ou remplace en respectant l'ordre des colonnes."""
    m = re.match(r'(<row\b[^>]*?)(/>|>)(.*?)(</row>)?$', xml_ligne, re.S)
    debut, fermeture, contenu = m.group(1), m.group(2), m.group(3) or ''
    if fermeture == '/>':
        contenu = ''
    for lettre, (valeur, formule) in sorted(cellules.items(), key=lambda kv: col_index(kv[0])):
        ref = f'{lettre}{r}'
        motif = re.compile(r'<c r="%s"(\s[^>]*?)?(?:/>|>.*?</c>)' % ref, re.S)
        mc = motif.search(contenu)
        if mc:
            contenu = contenu[:mc.start()] + _cellule(ref, mc.group(1), valeur, formule) + contenu[mc.end():]
        else:
            pos = len(contenu)
            for mx in re.finditer(r'<c r="([A-Z]+)\d+"', contenu):
                if col_index(mx.group(1)) > col_index(lettre):
                    pos = mx.start()
                    break
            contenu = contenu[:pos] + _cellule(ref, '', valeur, formule) + contenu[pos:]
    debut = re.sub(r'\s+spans="[^"]*"', '', debut)  # « spans » n'est qu'une indication : on la retire si on élargit la ligne
    return f'{debut}>{contenu}</row>'


def generer(source: str | Path, destination: str | Path, structure: dict, saisies: dict) -> dict:
    """Écrit quantités, PU et formules dans une copie du classeur de l'acheteur. Renvoie les contrôles."""
    calc = calculer(structure, saisies)
    col = structure['colonnes']
    D, E, F = col['qte'], col['pu'], col.get('total')
    if not F:
        raise ValueError('Colonne « Prix total » introuvable dans la DPGF.')
    plages = plages_sous_totaux(structure)
    a_ecrire = {}   # row -> {lettre: (valeur, formule)}
    for l in structure['lignes']:
        r = l['row']
        if l['type'] in ('poste', 'mention'):
            s = saisies.get(r) or {}
            cell = {}
            if s.get('qte') is not None:
                cell[D] = (s['qte'], None)
            if s.get('pu') is not None:
                cell[E] = (s['pu'], None)
            if l['type'] == 'poste' or cell:
                cell[F] = (calc['montants'].get(r, 0), f'{D}{r}*{E}{r}')
            a_ecrire[r] = cell
        elif l['type'] == 'total' and r in plages:
            # Total du lot : somme des Quantité × PU. Pas de SOUS.TOTAL ici, sinon une feuille de récapitulatif
            # qui additionne ce total avec SOUS.TOTAL l'ignorerait (comportement de LibreOffice notamment).
            a, b = plages[r]
            a_ecrire[r] = {F: (calc['totaux'].get(r, 0), f'SUMPRODUCT({D}{a}:{D}{b},{E}{a}:{E}{b})')}
        elif r in plages:
            a, b = plages[r]
            a_ecrire[r] = {F: (calc['totaux'].get(r, 0), f'SUBTOTAL(9,{F}{a}:{F}{b})')}

    with zipfile.ZipFile(source) as zin:
        chemin = _chemin_feuille(zin, structure['feuille'])
        feuille_xml = zin.read(chemin).decode('utf-8')

        def remplacer(m):
            r = int(m.group(1))
            return _modifier_ligne(m.group(0), r, a_ecrire[r]) if a_ecrire.get(r) else m.group(0)
        feuille_xml = re.sub(r'<row r="(\d+)"[^>]*?(?:/>|>.*?</row>)', remplacer, feuille_xml, flags=re.S)
        manquantes = [r for r in a_ecrire if not re.search(r'<row r="%d"' % r, feuille_xml)]

        # Valeur en cache des cellules d'autres feuilles qui reprennent directement le total (ex. récapitulatif)
        total_rows = [l['row'] for l in structure['lignes'] if l['type'] == 'total']
        nom_q = re.escape(structure['feuille'])
        cibles = {f'{F}{r}': calc['totaux'].get(r, 0) for r in total_rows}

        dest = io.BytesIO()
        with zipfile.ZipFile(dest, 'w', zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                nom = item.filename
                if nom == 'xl/calcChain.xml':
                    continue   # reconstruite par Excel ; une chaîne périmée provoquerait une « réparation »
                data = zin.read(nom)
                if nom == chemin:
                    data = feuille_xml.encode('utf-8')
                elif nom == 'xl/workbook.xml':
                    t = data.decode('utf-8')
                    if '<calcPr' in t:
                        t = re.sub(r'<calcPr\b([^>]*?)\s*fullCalcOnLoad="[^"]*"', r'<calcPr\1', t)
                        t = re.sub(r'<calcPr\b', '<calcPr fullCalcOnLoad="1"', t, count=1)
                    else:
                        t = t.replace('</workbook>', '<calcPr fullCalcOnLoad="1"/></workbook>')
                    data = t.encode('utf-8')
                elif nom == '[Content_Types].xml':
                    data = re.sub(rb'<Override[^>]*calcChain[^>]*/>', b'', data)
                elif nom == 'xl/_rels/workbook.xml.rels':
                    data = re.sub(rb'<Relationship[^>]*calcChain[^>]*/>', b'', data)
                elif nom.startswith('xl/worksheets/sheet') and nom.endswith('.xml') and cibles:
                    t = data.decode('utf-8')
                    for ref, v in cibles.items():
                        t = re.sub(r"(<f>[+=]?'?%s'?!\$?%s\$?%s</f>)<v>[^<]*</v>" % (nom_q, re.escape(re.match(r'[A-Z]+', ref).group(0)),
                                                                                  re.escape(ref[len(re.match(r'[A-Z]+', ref).group(0)):])),
                                   lambda m, v=v: m.group(1) + f'<v>{_fmt(v)}</v>', t)
                    data = t.encode('utf-8')
                zout.writestr(item, data)
    Path(destination).write_bytes(dest.getvalue())
    calc['lignes_absentes_du_fichier'] = manquantes
    calc['feuille'] = structure['feuille']
    return calc
