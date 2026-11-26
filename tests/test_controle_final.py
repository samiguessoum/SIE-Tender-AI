"""Tests du contrôle final (module controle_final)."""
import hashlib
import sys
import unicodedata
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import analyse_dce as A  # noqa: E402
import controle_final as C  # noqa: E402
import dpgf_acheteur as D  # noqa: E402

POLY = ROOT / 'exemples' / 'DCE_POLYTECHNIQUE_TEST'

ANALYSE = {'fiche': {
    'pieces_exigees': {'valeur': [
        {'piece': 'Attestation de visite signée', 'obligatoire': True, 'eliminatoire': True, 'source': 'RC.pdf', 'page': 6},
        {'piece': 'Cadre de réponse technique', 'obligatoire': True, 'eliminatoire': True, 'source': 'RC.pdf', 'page': 7},
        {'piece': 'DC1 (lettre de candidature) ou DUME', 'obligatoire': True, 'eliminatoire': False, 'source': 'RC.pdf', 'page': 6},
        {'piece': 'Mémoire technique', 'obligatoire': False, 'eliminatoire': False, 'source': 'RC.pdf', 'page': 7},
    ]},
    'visite': {'valeur': 'oui', 'source': 'RC.pdf', 'page': 5},
    'date_limite': {'valeur': '12/10/2026 à 15h00', 'iso': '2026-10-12T15:00', 'source': 'QR.pdf', 'page': 5},
}}
DPGF_OK = [{'lot': '3', 'origine': 'outil', 'controles': {'pret': True, 'sans_quantite': [], 'sans_prix': [], 'postes': 10, 'total_general': 1000}}]
FICHE = {'lots': [{'numero': 'Lot 3', 'retenu': True}, {'numero': 'Lot 4', 'retenu': False}]}
AVANT = datetime(2026, 10, 1, 9, 0)


def depose(*noms):
    return [{'relpath': 'Offre/' + n, 'filename': n, 'size': 1000, 'category': 'reponse'} for n in noms]


def test_piece_eliminatoire_absente_bloque():
    r = C.controler(analyse=ANALYSE, deposes=depose('DC1.pdf', 'Cadre de reponse technique.pdf'), alertes=[], fiche=FICHE,
                    dpgf=DPGF_OK, derogations={}, maintenant=AVANT)
    assert r['verdict'] == 'bloque'
    bloquants = [p['titre'] for p in r['points'] if p['niveau'] == 'bloquant']
    assert bloquants == ['Attestation de visite signée']


def test_dossier_complet_pret_pour_validation():
    r = C.controler(analyse=ANALYSE, deposes=depose('DC1.pdf', '01 - Attestation de visite.pdf', 'CRT.pdf', 'RIB.pdf', 'Kbis.pdf',
                                                    'URSSAF.pdf', 'Attestation fiscale.pdf', 'Assurance.pdf', 'Salaries etrangers.pdf'),
                    alertes=[], fiche=FICHE, dpgf=DPGF_OK, derogations={}, maintenant=AVANT)
    assert r['verdict'] == 'pret' and r['compteurs']['bloquants'] == 0


def test_derogation_leve_un_bloquant():
    args = dict(analyse=ANALYSE, deposes=depose('DC1.pdf', 'CRT.pdf'), alertes=[], fiche=FICHE, dpgf=DPGF_OK, maintenant=AVANT)
    code = next(p['code'] for p in C.controler(derogations={}, **args)['points'] if p['niveau'] == 'bloquant')
    r = C.controler(derogations={code: {'justification': 'Visite faite, attestation envoyée par mail', 'auteur': 'Direction', 'created': 'x'}}, **args)
    assert r['compteurs']['bloquants'] == 0 and r['compteurs']['derogations'] == 1


def test_dpgf_incomplete_et_alerte_bloquante():
    dpgf = [{'lot': '3', 'origine': 'outil', 'controles': {'pret': False, 'sans_quantite': list(range(8)), 'sans_prix': list(range(8)),
                                                           'postes': 10, 'total_general': 0}}]
    alertes = [{'id': 1, 'titre': 'Pièce manquante au DCE', 'statut': 'Bloquant', 'priorite': 'haute', 'detail': 'x'}]
    r = C.controler(analyse=ANALYSE, deposes=depose('DC1.pdf', 'Attestation de visite.pdf', 'CRT.pdf'), alertes=alertes,
                    fiche=FICHE, dpgf=dpgf, derogations={}, maintenant=AVANT)
    titres = {p['titre'] for p in r['points'] if p['niveau'] == 'bloquant'}
    assert titres == {'DPGF du lot 3', 'Pièce manquante au DCE'}


def test_delai_depasse():
    r = C.controler(analyse=ANALYSE, deposes=depose('DC1.pdf'), alertes=[], fiche=FICHE, dpgf=DPGF_OK, derogations={},
                    maintenant=datetime(2026, 10, 13))
    p = next(p for p in r['points'] if p['code'] == 'date_limite')
    assert p['statut'] == 'manquant' and 'dépassée' in p['detail']


def _docs(dossier, categorie):
    out = []
    for p in sorted(dossier.rglob('*')):
        if p.is_file() and p.name not in ('.DS_Store', 'Thumbs.db'):
            out.append({'id': hashlib.md5(str(p).encode()).hexdigest(), 'relpath': unicodedata.normalize('NFC', str(p.relative_to(dossier.parent))),
                        'filename': p.name, 'storepath': str(p), 'size': p.stat().st_size, 'sha256': None, 'category': categorie})
    return out


@pytest.mark.skipif(not (POLY / 'Dossier de réponse').exists(), reason='Dossier Polytechnique absent (exemples/ non versionné)')
def test_dossier_reellement_depose_par_sie(tmp_path):
    analyse = A.analyser(_docs(POLY / 'V1 - MX25-132 DCE', 'dce'), cache_dir=tmp_path)
    deposes = _docs(POLY / 'Dossier de réponse', 'reponse')
    alertes = [dict(a, id=i, statut='Traité') for i, a in enumerate(analyse['alertes'])]   # alertes supposées traitées
    xlsm = next(d for d in deposes if d['filename'].endswith('.xlsm'))
    st = D.lire(xlsm['storepath'])
    propres = {l['row']: {'qte': l['qte'], 'pu': l['pu']} for l in st['lignes'] if l['type'] in ('poste', 'mention')}
    dpgf = [{'lot': '3', 'origine': 'depose', 'filename': xlsm['filename'], 'relpath': xlsm['relpath'], 'controles': D.calculer(st, propres)}]
    r = C.controler(analyse=analyse, deposes=deposes, alertes=alertes, fiche=FICHE, dpgf=dpgf, derogations={},
                    maintenant=datetime(2026, 10, 10, 9))
    # Les 12 pièces exigées par le RC sont retrouvées dans le dossier remis
    pieces = [p for p in r['points'] if p['code'].startswith('piece:')]
    assert len(pieces) == 12 and all(p['statut'] == 'ok' for p in pieces)
    # Restent exactement les deux vrais points d'attention : qualification amiante et une ligne vide de la DPGF
    a_voir = sorted(p['titre'] for p in r['points'] if p['statut'] != 'ok' and p['niveau'] != 'info')
    assert a_voir == ['DPGF du lot 3', 'Qualification exigée (Q/R n°18)']
    assert r['verdict'] == 'a_verifier' and r['compteurs']['bloquants'] == 0
    dpgf_point = next(p for p in r['points'] if p['code'] == 'dpgf:3')
    assert 'lignes Excel 129' in dpgf_point['detail']   # « Bloc de télécommande » laissé vide
