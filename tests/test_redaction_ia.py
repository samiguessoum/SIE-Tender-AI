import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import redaction_ia as ia  # noqa: E402


EXTRAITS = [
    {'origine': 'dce', 'source': 'DCE/CCTP_Lot3.pdf', 'page': 4, 'texte': "Les travaux se déroulent en site occupé. "
     "Le titulaire assure la gestion des déchets de chantier et le tri sélectif."},
    {'origine': 'archive', 'source': 'Archives/Memoire_2024.docx', 'page': 2, 'texte': "Notre chef de chantier organise "
     "une réunion hebdomadaire de coordination avec l'exploitant et les autres corps d'état."},
    {'origine': 'dce', 'source': 'DCE/RC.pdf', 'page': 9, 'texte': "Critère valeur technique : méthodologie et organisation."},
]


def test_bm25_trouve_l_extrait_pertinent():
    index = ia.IndexBM25([dict(e) for e in EXTRAITS])
    r = index.chercher('gestion des déchets tri', k=2)
    assert r[0]['source'] == 'DCE/CCTP_Lot3.pdf'
    seulement_archives = index.chercher('coordination exploitant', k=3, filtre=lambda e: e['origine'] == 'archive')
    assert [e['source'] for e in seulement_archives] == ['Archives/Memoire_2024.docx']


def test_decoupage_garde_page_et_origine():
    ex = ia.decouper(['mot ' * 600, 'trop court', 'Page deux. ' * 12], 'DCE/CCTP.pdf', 'dce', taille=900)
    assert len(ex) >= 3 and all(len(e['texte']) <= 1000 for e in ex)
    assert {e['origine'] for e in ex} == {'dce'} and ex[0]['page'] == 1 and ex[-1]['page'] == 3


def test_garde_fous_signalent_chiffres_et_sources_inventees():
    texte = ("## Organisation\nNous mobilisons 7 compagnons et un chef de chantier [S2].\n\n"
             "Le tri des déchets atteint 95 % de valorisation [S1][S9].\n\n"
             "1. Réunion de coordination hebdomadaire [S2]\n[À COMPLÉTER : nom du conducteur de travaux]")
    c = ia.verifier(texte, EXTRAITS)
    valeurs = [x['valeur'] for x in c['chiffres_non_sources']]
    assert any('7' in v for v in valeurs) and any('95' in v for v in valeurs)
    assert not any(v.startswith('1') and len(v) == 1 for v in valeurs)   # numérotation ignorée
    assert c['sources_inconnues'] == ['S9']
    assert c['a_completer'] == 1


def test_chiffre_present_dans_les_consignes_n_est_pas_signale():
    c = ia.verifier('Nous affectons 3 techniciens au chantier [S2].', EXTRAITS, consignes='3 techniciens')
    assert c['chiffres_non_sources'] == []


def test_rediger_avec_fournisseur_simule_n_envoie_que_des_extraits():
    capture = {}

    class Espion(ia.FournisseurSimule):
        def generer(self, systeme, utilisateur):
            capture['demande'] = utilisateur
            return super().generer(systeme, utilisateur)

    index = ia.IndexBM25([dict(e) for e in EXTRAITS])
    r = ia.rediger(Espion(), index, {'code': '1.2', 'libelle': 'Gestion des déchets et coordination'}, consignes='site occupé', lot='3')
    assert r['sources'] and all(s['id'].startswith('S') for s in r['sources'])
    assert '[S' in r['texte'] and 'À COMPLÉTER' in r['texte']
    assert 'Gestion des déchets' in capture['demande'] and 'lot 3' in capture['demande']
    assert r['caracteres_envoyes'] < 20000
    assert r['archives_disponibles'] is True


def test_fournisseur_depuis_environnement(monkeypatch):
    monkeypatch.delenv('SIE_IA_FOURNISSEUR', raising=False)
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    assert ia.fournisseur_depuis_environnement() is None
    monkeypatch.setenv('OPENAI_API_KEY', 'sk-test')
    monkeypatch.setenv('OPENAI_BASE_URL', 'https://eu.api.openai.com/v1/')
    f = ia.fournisseur_depuis_environnement()
    assert f.nom == 'openai' and f.modele == ia.MODELE_PAR_DEFAUT and f.base_url == 'https://eu.api.openai.com/v1'
    monkeypatch.setenv('SIE_IA_FOURNISSEUR', 'simule')
    assert ia.fournisseur_depuis_environnement().nom == 'simule'
