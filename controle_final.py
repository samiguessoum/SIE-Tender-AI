"""Contrôle final avant dépôt : les pièces exigées par le DCE sont-elles toutes dans le dossier de réponse ?

Le contrôle s'appuie sur :
* la dernière analyse du DCE (pièces exigées par le RC, visite, date limite, qualifications citées en Q/R) ;
* les pièces réellement importées dans le dossier de réponse (catégories reponse / devis / memoire / autre) ;
* le registre des alertes (statut humain) ;
* la DPGF de l'acheteur des lots retenus.

Règles :
* une pièce éliminatoire absente, une alerte marquée « Bloquant » ou un fichier vide bloque le dossier ;
* tout point bloquant peut être levé par une dérogation écrite (auteur, justification, date), tracée ;
* l'outil ne déclare jamais un dossier « déposé » : au mieux « prêt pour validation par SIE ».
On ne lit que les noms des fichiers déposés (jamais leur contenu) : le rapprochement est indicatif.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime

BLOQUANT, MAJEUR, INFO = 'bloquant', 'majeur', 'info'


def _cle(s) -> str:
    s = ''.join(c for c in unicodedata.normalize('NFD', str(s or '')) if unicodedata.category(c) != 'Mn').lower()
    return re.sub(r'[^a-z0-9]+', ' ', s).strip()


# Pièce exigée (libellé produit par analyse_dce) -> motifs de reconnaissance dans le nom des fichiers déposés
MOTIFS = {
    'DC1 (lettre de candidature) ou DUME': r'\bdc ?1\b|lettre de candidature|\bdume\b',
    'DC2 (déclaration du candidat) ou DUME': r'\bdc ?2\b|declaration du candidat|\bdume\b',
    "Chiffre d'affaires des 3 derniers exercices": r"chiffre d ?affaire|\bca\b.*20\d\d|bilan|liasse",
    'Annexe au RC : capacités techniques et professionnelles': r'annexe \d+ au rc|capacites? techniques?|moyens en materiel|effectifs?',
    'Certificats de qualifications professionnelles': r'qualif|qualibat|qualifelec|certificats? de capacite',
    'Certificats de qualité': r'\biso\b|certificats? (de )?qualite|qualifelec|qualibat|certificats? de capacite',
    'Attestation de visite signée': r'attestation de visite|\bvisite\b',
    'Cadre de réponse technique': r'cadre de reponse|\bcrt\b',
    'DPGF': r'\bdpgf\b|decomposition du prix|\bbpu\b|\bdqe\b',
    "Acte d'engagement": r'\bae\b|acte d engagement',
    "Planning d'exécution détaillé": r'planning',
    'Mémoire technique': r'memoire|cadre de reponse',
}

# Pièces demandées à l'attributaire (non exigées au dépôt, mais souvent jointes ; utiles à anticiper)
ATTRIBUTAIRE = [
    ("Attestation d'assurance", r'assurance'),
    ('Régularité fiscale (DGFIP)', r'fiscal'),
    ('Régularité sociale (URSSAF)', r'urssaf'),
    ('RIB / IBAN', r'\brib\b|\biban\b'),
    ('Extrait Kbis / SIREN', r'kbis|siren|siret'),
    ('Liste des salariés étrangers ou déclaration sur l’honneur', r'etranger|declaration sur l honneur'),
]


def _lot_code(numero: str) -> str:
    s = _cle(numero)
    m = re.match(r'macro lot (\d+)', s)
    if m:
        return 'ML' + m.group(1)
    m = re.search(r'(\d+(?:\.\d+)?)', s)
    return m.group(1) if m else s


def controler(*, analyse: dict | None, deposes: list[dict], alertes: list[dict], fiche: dict | None,
              dpgf: list[dict], derogations: dict, maintenant: datetime | None = None) -> dict:
    """deposes : [{relpath, filename, size, category, document_type}] ; dpgf : [{lot, filename, controles}] ;
    derogations : {code: {justification, auteur, created}}."""
    maintenant = maintenant or datetime.now()
    points = []

    def point(code, titre, statut, niveau, detail='', preuves=None, source=None):
        p = {'code': code, 'titre': titre, 'statut': statut, 'niveau': niveau if statut != 'ok' else INFO,
             'detail': detail, 'preuves': preuves or [], 'source': source}
        if statut != 'ok' and code in derogations:
            p['derogation'] = derogations[code]
            p['niveau_initial'], p['niveau'] = p['niveau'], INFO
        points.append(p)

    noms = [(_cle(d['relpath']), d) for d in deposes]

    def chercher(motif):
        return [d for k, d in noms if re.search(motif, k)]

    if not analyse:
        point('analyse', 'Analyse du DCE', 'manquant', BLOQUANT,
              "Le DCE n'a pas été analysé : impossible de connaître les pièces exigées. Lancez l'analyse dans « Analyse du DCE ».")
    fiche_dce = (analyse or {}).get('fiche', {})

    # 1. Pièces exigées par le RC
    for p in (fiche_dce.get('pieces_exigees') or {}).get('valeur') or []:
        trouves = chercher(MOTIFS.get(p['piece'], re.escape(_cle(p['piece']))))
        code = 'piece:' + _cle(p['piece'])[:40]
        src = {'fichier': p.get('source'), 'page': p.get('page')}
        if trouves:
            point(code, p['piece'], 'ok', INFO, f"{len(trouves)} pièce(s) correspondante(s)", [d['relpath'] for d in trouves][:6], src)
        elif not p.get('obligatoire'):
            point(code, p['piece'] + ' (facultatif)', 'a_verifier', INFO, 'Pièce facultative non trouvée dans le dossier.', source=src)
        else:
            point(code, p['piece'], 'manquant', BLOQUANT if p.get('eliminatoire') else MAJEUR,
                  ('Pièce éliminatoire exigée par le RC, absente du dossier.' if p.get('eliminatoire')
                   else 'Pièce exigée par le RC, absente du dossier.'), source=src)

    # 2. Qualifications exigées en questions-réponses (ex. qualification amiante pour le lot 3)
    lots_retenus = [_lot_code(l.get('numero', '')) for l in (fiche or {}).get('lots', []) if l.get('retenu')]
    for a in alertes:
        if not a['titre'].startswith('Qualification exigée'):
            continue
        objet = re.search(r'qualification\s+([a-zé]+)', a.get('detail') or '', re.I)
        mot = _cle(objet.group(1)) if objet else ''
        lots = a.get('lots') or []
        if lots_retenus and lots and not set(lots) & set(lots_retenus):
            continue
        trouves = chercher(re.escape(mot)) if mot and mot not in ('sous', 'professionnelle') else []
        code = 'qualif:' + _cle(a['titre'])[:40]
        if trouves:
            point(code, a['titre'], 'ok', INFO, 'Justificatif repéré par son nom.', [d['relpath'] for d in trouves][:4],
                  {'fichier': a.get('source'), 'page': a.get('page')})
        else:
            point(code, a['titre'], 'a_verifier', MAJEUR,
                  f"Aucun fichier dont le nom évoque « {mot or 'la qualification'} ». Vérifier qu'un certificat (ou la formation "
                  f"équivalente) figure dans les pièces de candidature.", source={'fichier': a.get('source'), 'page': a.get('page')})

    # 3. Visite obligatoire
    visite = fiche_dce.get('visite') or {}
    deja = any(p['titre'].startswith('Attestation de visite') for p in points)
    if visite.get('valeur') == 'oui' and not deja:
        trouves = chercher(MOTIFS['Attestation de visite signée'])
        point('visite', 'Attestation de visite (visite obligatoire)', 'ok' if trouves else 'manquant', BLOQUANT,
              'Visite obligatoire selon le RC : l’attestation signée doit être jointe.', [d['relpath'] for d in trouves][:3],
              {'fichier': visite.get('source'), 'page': visite.get('page')})

    # 4. Date limite de remise
    dl = fiche_dce.get('date_limite') or {}
    if dl.get('iso'):
        echeance = datetime.fromisoformat(dl['iso'])
        reste = echeance - maintenant
        heures = reste.total_seconds() / 3600
        if heures < 0:
            point('date_limite', f"Date limite : {dl['valeur']}", 'manquant', MAJEUR,
                  f"Date limite dépassée depuis {int(-heures // 24)} jour(s) : une offre remise hors délai est rejetée sans être "
                  f"examinée.", source={'fichier': dl.get('source'), 'page': dl.get('page')})
        else:
            point('date_limite', f"Date limite : {dl['valeur']}", 'ok' if heures > 48 else 'a_verifier', MAJEUR,
                  f"Il reste {int(heures // 24)} j {int(heures % 24)} h. Déposer suffisamment tôt (plis volumineux).",
                  source={'fichier': dl.get('source'), 'page': dl.get('page')})
    else:
        point('date_limite', 'Date limite de remise', 'a_verifier', MAJEUR, 'Date limite non déterminée par l’analyse : la saisir.')

    # 5. Alertes du registre
    for a in alertes:
        if a.get('statut') in ('Traité', 'Sans objet'):
            continue
        code = f"alerte:{a['id']}"
        if a.get('statut') == 'Bloquant':
            point(code, a['titre'], 'manquant', BLOQUANT, f"Alerte marquée « Bloquant » : {a.get('detail') or ''}"[:400],
                  source={'fichier': a.get('source'), 'page': a.get('page')})
        elif a.get('priorite') == 'haute':
            point(code, a['titre'], 'a_verifier', MAJEUR,
                  f"Alerte prioritaire au statut « {a.get('statut')} » : la traiter ou la classer sans objet."[:400],
                  source={'fichier': a.get('source'), 'page': a.get('page')})

    # 6. DPGF des lots retenus : on contrôle de préférence le fichier réellement déposé dans le dossier de réponse
    #    (origine « depose »), sinon la saisie faite dans l'outil (origine « outil »).
    if lots_retenus:
        for lot in lots_retenus:
            fichiers = [x for x in dpgf if x.get('lot') == lot]
            depose = next((x for x in fichiers if x.get('origine') == 'depose'), None)
            outil = next((x for x in fichiers if x.get('origine', 'outil') == 'outil'), None)
            choix = depose if depose and (not outil or not outil['controles']['pret']) else outil
            if not choix:
                point(f'dpgf:{lot}', f'DPGF du lot {lot}', 'a_verifier', MAJEUR, 'Aucune DPGF de l’acheteur reconnue pour ce lot.')
                continue
            c = choix['controles']
            ou = f"fichier déposé « {choix.get('filename')} »" if choix is depose else 'saisie dans l’outil'
            if c['pret']:
                point(f'dpgf:{lot}', f'DPGF du lot {lot}', 'ok', INFO,
                      f"{ou} : {c['postes']} postes chiffrés — total HT {c['total_general']:,.2f} €".replace(',', ' '),
                      [choix.get('relpath')] if choix is depose else [])
            else:
                exemples = ', '.join(str(x) for x in (c['sans_quantite'] + c['sans_prix'])[:8])
                incomplet = sorted(set(c['sans_quantite']) | set(c['sans_prix']))
                grave = len(incomplet) > max(3, c['postes'] // 10)
                point(f'dpgf:{lot}', f'DPGF du lot {lot}', 'manquant' if grave else 'a_verifier', BLOQUANT if grave else MAJEUR,
                      f"{ou} : {len(c['sans_quantite'])} poste(s) sans quantité, {len(c['sans_prix'])} sans prix sur {c['postes']} "
                      f"(lignes Excel {exemples}…). Vérifier : poste inclus ailleurs, sans objet, ou oubli ?",
                      [choix.get('relpath')] if choix is depose else [])
    else:
        point('lots', 'Lots retenus', 'a_verifier', MAJEUR,
              'Aucun lot coché « retenu » dans la fiche de renseignement : impossible de contrôler les DPGF des lots chiffrés.')

    # 7. Fichiers déposés vides ou volumineux
    for d in deposes:
        if not d.get('size'):
            point('vide:' + d['relpath'][-60:], f"Fichier vide : {d['filename']}", 'manquant', BLOQUANT,
                  'Ce fichier fait 0 octet : il ne pourra pas être lu par l’acheteur.', [d['relpath']])
    total = sum(d.get('size') or 0 for d in deposes)

    # 8. Pièces demandées à l'attributaire (information)
    manquantes = [lib for lib, motif in ATTRIBUTAIRE if not chercher(motif)]
    point('attributaire', 'Pièces de l’attributaire (à fournir si retenu)', 'ok' if not manquantes else 'a_verifier', INFO,
          ('Toutes présentes.' if not manquantes else 'Non trouvées : ' + ', '.join(manquantes) + '. À préparer pour l’attribution.'))

    bloquants = [p for p in points if p['niveau'] == BLOQUANT]
    majeurs = [p for p in points if p['niveau'] == MAJEUR]
    if not deposes:
        verdict, libelle = 'vide', 'Aucune pièce de réponse importée'
    elif bloquants:
        verdict, libelle = 'bloque', f'{len(bloquants)} point(s) bloquant(s) : dossier non prêt'
    elif majeurs:
        verdict, libelle = 'a_verifier', f'{len(majeurs)} point(s) à vérifier avant validation'
    else:
        verdict, libelle = 'pret', 'Prêt pour validation par SIE (le dépôt reste manuel)'
    ordre = {BLOQUANT: 0, MAJEUR: 1, INFO: 2}
    points.sort(key=lambda p: (ordre[p['niveau']], p['statut'] == 'ok', p['titre']))
    return {'verdict': verdict, 'libelle': libelle, 'points': points,
            'compteurs': {'bloquants': len(bloquants), 'a_verifier': len(majeurs), 'ok': sum(1 for p in points if p['statut'] == 'ok'),
                          'derogations': sum(1 for p in points if p.get('derogation'))},
            'pieces_deposees': len(deposes), 'volume_octets': total, 'lots_retenus': lots_retenus,
            'date': maintenant.isoformat(timespec='seconds'),
            'avertissement': "Contrôle indicatif fondé sur le nom des fichiers et les données saisies. Il ne remplace pas la relecture "
                             "du RC ni la validation administrative, technique et financière par SIE."}
