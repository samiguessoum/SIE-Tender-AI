"""Tests de l'analyse structurée du DCE (module analyse_dce).

Le test « Polytechnique » utilise le vrai DCE rangé dans exemples/ (non versionné, confidentiel) :
il est ignoré automatiquement sur un poste qui ne l'a pas.
"""
import hashlib
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import analyse_dce as A  # noqa: E402

DCE_POLY = ROOT / 'exemples' / 'DCE_POLYTECHNIQUE_TEST' / 'V1 - MX25-132 DCE'
REFERENCE = json.loads((ROOT / 'tests' / 'fixtures' / 'MX25-132_reference.json').read_text('utf-8'))


@pytest.mark.parametrize('chemin,attendu', [
    ('DCE/MX25-132 RC.pdf', 'RC'),
    ('DCE/Annexe 3 au RC.docx', 'RC_ANNEXE'),
    ('DCE/Questions-réponses 06.10.2026.pdf', 'QR'),
    ('DCE/MX25-132 CCAP.pdf', 'CCAP'),
    ('DCE/MX25-132_Cadre de reponse technique.docx', 'CRT'),
    ('DCE/MX25-132_AE lot 3.docx', 'AE'),
    ('DCE/MX25-132 Attestation de visite du site.docx', 'ATTESTATION_VISITE'),
    ('DCE/DPGF/POLYTECHNIQUE_SACLAY AILE 3_DCE_Lot3_DPGF_V1.xlsm', 'DPGF'),
    ('DCE/CCTP-CCTC/CCTP et CCTC/LOT 3/POLYTECH_SACLAY_LABO AILE 3-DCE_LOT 3 ELECTRICITE CFO CFA V1.pdf', 'CCTP'),
    ('DCE/CCTP-CCTC/CCTP et CCTC/MACRO LOT 2/POLYTECH-DCE_MACRO LOT 2.2 CCTP PLOMBERIE V1.pdf', 'CCTP'),
    ('DCE/CCTP-CCTC/PLOMB AVANT TRAVAUX- AILE 3.pdf', 'DIAGNOSTIC'),
    ('DCE/PG Techniques/LOT 3/5101 - PLAN ELEC RDC.pdf', 'PLAN'),
    ('DCE/PG Architecte.zip', 'ARCHIVE'),
    ('DCE/DC1-2019.doc', 'FORMULAIRE'),
])
def test_classement_des_pieces(chemin, attendu):
    assert A.classer(chemin) == attendu


def test_lot_detecte_dans_le_chemin():
    assert A.detecter_lot('DCE/MX25-132_AE lot 3.docx') == '3'
    assert A.detecter_lot('DCE/MX25-132_AE macro lot 2.docx') == 'ML2'
    assert A.detecter_lot('DCE/DPGF/POLYTECHNIQUE_SACLAY AILE 3_DCE_ML1_DPGF_V1.xlsm') == 'ML1'


def test_fusion_qr_prefere_le_tableur():
    pdf = [{'num': 3, 'texte': 'texte du PDF qui a avalé la question 4 et bien plus encore', 'question': None, 'source': 'a.pdf', 'page': 1}]
    tab = [{'num': 3, 'texte': 'question trois réponse trois', 'question': 'q', 'reponse': 'r', 'source': 'b.xlsx', 'page': 1}]
    fusion = A.fusionner_qr([pdf, tab])
    assert len(fusion) == 1 and fusion[0]['source'] == 'b.xlsx'


def test_champ_absent_vaut_a_verifier():
    res = A.analyser([])
    assert res['fiche']['date_limite']['valeur'] == A.A_VERIFIER
    assert res['fiche']['date_limite']['statut'] == 'a_verifier'


def _documents_depuis_dossier(dossier: Path):
    docs = []
    for chemin in sorted(dossier.rglob('*')):
        if not chemin.is_file() or chemin.name == '.DS_Store':
            continue
        data = chemin.read_bytes()
        docs.append({'id': hashlib.md5(str(chemin).encode()).hexdigest(), 'relpath': str(chemin.relative_to(dossier.parent)),
                     'filename': chemin.name, 'storepath': str(chemin), 'size': len(data),
                     'sha256': hashlib.sha256(data).hexdigest()})
    return docs


@pytest.mark.skipif(not DCE_POLY.exists(), reason='DCE Polytechnique absent (exemples/ non versionné)')
def test_dce_polytechnique_conforme_a_la_reference(tmp_path):
    res = A.analyser(_documents_depuis_dossier(DCE_POLY), cache_dir=tmp_path / 'cache', lots_retenus=['3'])
    f, ref = res['fiche'], REFERENCE['fiche']

    # 1. Identification
    assert f['reference']['valeur'] == ref['reference']['valeur']
    assert f['reference']['source'].endswith('MX25-132 RC.pdf')
    assert 'aile 3' in f['objet']['valeur'].lower()
    assert f['procedure']['valeur'].lower().startswith("appel d'offres ouvert")

    # 2. Point de référence n°1 : la date limite est celle des Q/R, pas celle du RC
    assert f['date_limite']['iso'] == ref['date_limite_remise']['valeur']
    assert f['date_limite']['source'].endswith('Questions-réponses 06.10.2026.pdf')
    assert f['date_limite']['historique'][0]['valeur'].startswith('05/10/2026')
    assert f['date_limite_questions']['valeur'].startswith('30/09/2026')

    # 3. Point de référence n°2 : visite obligatoire, 4 créneaux, attestation
    assert f['visite']['valeur'] == 'oui'
    assert len(f['visite']['creneaux']) == len(ref['visite']['creneaux'])
    assert f['visite']['attestation'] is True
    assert f['visite']['rendez_vous']

    # 4. Point de référence n°3 : qualification amiante exigée (Q/R n°18)
    titres = [a['titre'] for a in res['alertes']]
    assert any('Qualification exigée' in t and '18' in t for t in titres)
    assert any('Date limite modifiée' in t for t in titres)
    assert any('Contradiction sur les variantes' in t for t in titres)
    assert any('Fichier vide' in t for t in titres)

    # 5. Clauses et intervenants
    assert f['validite_offres']['valeur'] == '180 jours'
    assert f['delai_execution']['valeur'] == '18 mois'
    assert f['variantes']['valeur'] == 'Non autorisées'
    assert 'ALTEREA' in f['moe']['valeur'] and f['architecte']['valeur'] == 'CODA Architectes'
    assert f['sps']['valeur'] == 'BTP Consultants' and f['controleur_technique']['valeur'] == 'SOCOTEC'
    assert f['ssi']['statut'] == 'a_verifier'  # non nommé dans le DCE : doit rester « À vérifier »
    assert 'Palaiseau' in f['lieu']['valeur']

    # 6. Lots : tous, y compris ceux que SIE ne retiendra pas
    codes = [l['code'] for l in f['lots']['valeur']]
    assert codes == ['ML1', 'ML2', '3', '4']
    assert len(f['lots']['valeur'][0]['sous_lots']) == 8 and len(f['lots']['valeur'][1]['sous_lots']) == 4
    assert 'lectricit' in f['lots']['valeur'][2]['intitule']

    # 7. Critères : total 100 points, sous-critères conformes
    crit = f['criteres']['valeur']
    assert sum(c['poids'] for c in crit) == 100
    attendu = {k[:3]: v for k, v in ref.get('criteres', REFERENCE['criteres'])['technique']['sous_criteres'].items()}
    obtenu = {s['code']: s['poids'] for c in crit for s in c['sous_criteres'] if c['code'] == '1'}
    assert obtenu == attendu

    # 8. Pièces : attestation de visite et cadre de réponse éliminatoires, mémoire facultatif
    pieces = {p['piece']: p for p in f['pieces_exigees']['valeur']}
    assert pieces['Attestation de visite signée']['eliminatoire']
    assert pieces['Cadre de réponse technique']['eliminatoire']
    assert not pieces['Mémoire technique']['obligatoire']
    assert pieces['DPGF']['obligatoire']

    # 9. Clause sociale : 180 h pour le lot 3
    assert {'Lot 3': 180}.items() <= {h['element']: h['heures'] for h in f['heures_insertion']['valeur']}.items()

    # 10. Questions-réponses : toutes les questions publiées sont découpées, sans doublon
    nums = [q['num'] for q in res['questions_reponses']]
    assert len(nums) == len(set(nums)) and len(nums) >= 55

    # 11. Les plans ne sont pas lus pour la fiche ; le RC, le CCAP et les Q/R le sont
    lus = {e['type'] for e in res['inventaire'] if e.get('lu')}
    assert {'RC', 'CCAP', 'QR', 'CRT'} <= lus and 'PLAN' not in lus

    # 12. Format interface : la fiche peut être pré-remplie
    ui = A.fiche_pour_interface(res)
    assert ui['reference'] == 'MX25-132' and ui['visiteCondition'] == 'oui' and len(ui['lots']) == 4


@pytest.mark.parametrize('texte', [
    # restitution ligne par ligne (pdftotext)
    "Le nombre d'heures est fixé à : Elément du contrat Nombre d'heures d'insertion Macro lot 1 (sous-lots 1 à 8) 1 000 heures "
    "Macro lot 2 (sous-lots 9 à 12) 600 heures Lot 3 180 heures Lot 4 20 heures ■",
    # restitution colonne par colonne (PyMuPDF) : deux libellés avant leurs valeurs
    "Le nombre d'heures est fixé à :\nElément du contrat\nNombre d'heures d'insertion\nMacro lot 1 (sous-lots 1 à 8)\n1 000 heures\n"
    "Macro lot 2 (sous-lots 9 à 12)\nLot 3\n600 heures\n180 heures\nLot 4\n20 heures\n■",
])
def test_heures_insertion_independantes_de_l_ordre_de_lecture(tmp_path, texte):
    f = tmp_path / 'ccap.txt'
    f.write_text(texte, encoding='utf-8')
    res = A.analyser([{'id': '1', 'relpath': 'DCE/X CCAP.txt', 'filename': 'X CCAP.txt', 'storepath': str(f),
                       'size': f.stat().st_size, 'sha256': None}])
    h = {x['element']: x['heures'] for x in res['fiche']['heures_insertion']['valeur']}
    assert h == {'Macro lot 1 (sous-lots 1 à 8)': 1000, 'Macro lot 2 (sous-lots 9 à 12)': 600, 'Lot 3': 180, 'Lot 4': 20}
