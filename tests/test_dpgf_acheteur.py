"""Tests de la DPGF de l'acheteur (module dpgf_acheteur)."""
import hashlib
import io
import re
import sys
import zipfile
from pathlib import Path

import pytest
from openpyxl import Workbook, load_workbook

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import dpgf_acheteur as D  # noqa: E402

DPGF_LOT3 = ROOT / 'exemples' / 'DCE_POLYTECHNIQUE_TEST' / 'V1 - MX25-132 DCE' / 'DPGF' / 'POLYTECHNIQUE_SACLAY AILE 3_DCE_Lot3_DPGF_V1.xlsm'


def classeur_type(chemin: Path):
    """DPGF de synthèse : 2 sections, un SO, sous-totaux, un rappel de sous-total et un total."""
    wb = Workbook()
    ws = wb.active
    ws.title = 'Lot ELEC'
    ws.append(['DPGF lot 3'])
    ws.append([])
    ws.append(['N°', 'DESIGNATION DES OUVRAGES', 'Unité', 'Qté', 'PU HT', 'Prix Total HT'])   # ligne 3
    ws.append(['1', 'COURANT FORT'])                                                         # 4
    ws.append(['1.1', 'Tableau général', 'U'])                                               # 5
    ws.append(['1.2', 'Câbles', 'ml'])                                                       # 6
    ws.append(['1.3', 'Source de secours', 'SO'])                                            # 7
    ws.append([None, '=CONCATENATE("Sous Total ",A4,".",B4)'])                               # 8
    ws.append(['2', 'COURANT FAIBLE'])                                                       # 9
    ws.append(['2.1', 'Prises RJ45', 'U'])                                                   # 10
    ws.append([None, '=CONCATENATE("Sous Total ",A9,".",B9)'])                               # 11
    ws.append([None, '=CONCATENATE(A8,"",B8)'])                                              # 12 (rappel)
    ws.append([None, 'TOTAL BASE HT'])                                                       # 13
    wb.create_sheet('RECAP')['B2'] = "='Lot ELEC'!F13"
    wb.save(chemin)


def test_structure(tmp_path):
    f = tmp_path / 'dpgf.xlsx'
    classeur_type(f)
    st = D.lire(f)
    assert st['feuille'] == 'Lot ELEC' and st['entete'] == 3
    assert st['colonnes'] == {'numero': 'A', 'designation': 'B', 'unite': 'C', 'qte': 'D', 'pu': 'E', 'total': 'F'}
    types = {l['row']: l['type'] for l in st['lignes']}
    assert types == {4: 'titre', 5: 'poste', 6: 'poste', 7: 'mention', 8: 'sous_total', 9: 'titre', 10: 'poste',
                     11: 'sous_total', 12: 'rappel', 13: 'total'}
    pl = D.plages_sous_totaux(st)
    assert pl[8] == (5, 7) and pl[11] == (10, 10) and pl[12] == (5, 7) and pl[13] == (4, 12)


def test_calculs_et_controles(tmp_path):
    f = tmp_path / 'dpgf.xlsx'
    classeur_type(f)
    st = D.lire(f)
    calc = D.calculer(st, {5: {'qte': 2, 'pu': 100}, 6: {'qte': 10.5, 'pu': 3}, 10: {'qte': 4, 'pu': None}})
    assert calc['totaux'][8] == 231.5 and calc['totaux'][12] == 231.5
    assert calc['total_general'] == 231.5          # le rappel (ligne 12) n'est pas compté deux fois
    assert calc['sans_prix'] == [10] and calc['sans_quantite'] == [] and not calc['pret']


def test_generation_formules_et_valeurs(tmp_path):
    f, out = tmp_path / 'dpgf.xlsx', tmp_path / 'dpgf_SIE.xlsx'
    classeur_type(f)
    st = D.lire(f)
    D.generer(f, out, st, {5: {'qte': 2, 'pu': 100}, 6: {'qte': 10.5, 'pu': 3}, 10: {'qte': 4, 'pu': 25}})
    wf = load_workbook(out)['Lot ELEC']
    assert wf['D5'].value == 2 and wf['E5'].value == 100 and wf['F5'].value == '=D5*E5'
    assert wf['F8'].value == '=SUBTOTAL(9,F5:F7)' and wf['F12'].value == '=SUBTOTAL(9,F5:F7)'
    assert wf['F13'].value == '=SUMPRODUCT(D4:D12,E4:E12)'
    assert wf['F7'].value is None                  # ligne SO non chiffrée : laissée vide
    wv = load_workbook(out, data_only=True)
    assert wv['Lot ELEC']['F13'].value == 331.5 and wv['Lot ELEC']['F6'].value == 31.5
    assert wv['RECAP']['B2'].value in (None, 331.5)  # valeur en cache mise à jour si présente ; Excel recalcule à l'ouverture
    with zipfile.ZipFile(out) as z:
        assert 'fullCalcOnLoad="1"' in z.read('xl/workbook.xml').decode()
    # l'original n'est pas modifié
    assert load_workbook(f)['Lot ELEC']['D5'].value is None


@pytest.mark.skipif(not DPGF_LOT3.exists(), reason='DPGF Polytechnique absente (exemples/ non versionné)')
def test_dpgf_polytechnique_lot3(tmp_path):
    st = D.lire(DPGF_LOT3)
    assert st['feuille'] == 'Lot ELECTRICITE' and st['entete'] == 11
    postes = [l['row'] for l in st['lignes'] if l['type'] == 'poste']
    assert len(postes) == 118      # 130 lignes avec unité, dont 12 « cis » (compris ailleurs)
    assert sum(1 for l in st['lignes'] if l['type'] == 'mention') == 21
    total = next(l for l in st['lignes'] if l['type'] == 'total')
    assert total['row'] == 257
    pl = D.plages_sous_totaux(st)
    assert pl[179] == (14, 178) and pl[255] == (14, 179) and pl[256] == pl[251] == (181, 250)
    out = tmp_path / 'lot3_SIE.xlsm'
    rap = D.generer(DPGF_LOT3, out, st, {r: {'qte': 2, 'pu': 10.5} for r in postes})
    assert rap['pret'] and rap['total_general'] == 118 * 21
    # Seules la feuille de prix et quelques parties techniques changent : macros, images, autres feuilles identiques
    a, b = zipfile.ZipFile(DPGF_LOT3), zipfile.ZipFile(out)
    assert set(a.namelist()) - set(b.namelist()) == {'xl/calcChain.xml'}
    modifiees = {n for n in b.namelist() if a.read(n) != b.read(n)}
    assert modifiees <= {'[Content_Types].xml', 'xl/_rels/workbook.xml.rels', 'xl/workbook.xml',
                         'xl/worksheets/sheet3.xml', 'xl/worksheets/sheet4.xml'}
    assert hashlib.sha256(a.read('xl/vbaProject.bin')).digest() == hashlib.sha256(b.read('xl/vbaProject.bin')).digest()
    feuille = b.read('xl/worksheets/sheet4.xml').decode()
    assert '<c r="F257" s="111"><f>SUMPRODUCT(D12:D256,E12:E256)</f><v>2478</v></c>' in feuille
    assert re.search(r'<c r="F21"[^>]*><f>D21\*E21</f><v>21</v></c>', feuille)


def test_rapprochement_par_numero_et_designation(tmp_path):
    f = tmp_path / 'dpgf.xlsx'
    classeur_type(f)
    st = D.lire(f)
    props = D.rapprocher(st, [
        {'reference': '1.1', 'designation': 'autre libellé', 'unite': 'U', 'quantite': 3},
        {'reference': '', 'designation': 'Prises RJ 45', 'unite': 'ml', 'quantite': 40},
        {'reference': '', 'designation': 'Sans rapport avec la DPGF', 'unite': 'U', 'quantite': 1},
    ])
    par_row = {p['row']: p for p in props}
    assert par_row[5]['mode'] == 'numéro identique' and par_row[5]['score'] == 1.0
    assert par_row[10]['mode'] == 'désignation proche' and par_row[10]['unite_differente']
    assert 6 not in par_row
