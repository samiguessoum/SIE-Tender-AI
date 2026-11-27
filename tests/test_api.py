import io
import os
import sys
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook,load_workbook

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


@pytest.fixture(scope='module')
def client(tmp_path_factory):
    os.environ['SIE_DATA_DIR']=str(tmp_path_factory.mktemp('sie-data'))
    import server
    with TestClient(server.app) as test:
        yield test


def test_health_and_state(client):
    assert client.get('/api/health').json()['status']=='ok'
    body={'state':{'lines':[{'id':'L1','name':'Cheminement','qty':5,'unit':'ml','price':24.5}],'docs':[]},
          'sieContexts':{'AO1':{'lines':[{'id':'L1','name':'Cheminement','qty':5,'unit':'ml','price':24.5}]}},
          'fiches':{},'metresStore':{},'sieMemoStore':{}}
    assert client.put('/api/state',json=body).status_code==200
    assert client.get('/api/state').json()['data']==body


def test_files_and_analysis(client):
    data=b'Date limite de remise : 15 novembre 2026\nVisite obligatoire.\nGestion des dechets du chantier.\n'
    response=client.post('/api/files/AO1/upload',files={'file':('RC.txt',data,'text/plain')},data={'category':'dce','relpath':'DCE/RC.txt'})
    assert response.status_code==200,response.text
    doc_id=response.json()['file']['id']
    assert client.get('/api/files/AO1').json()['files'][0]['id']==doc_id
    findings=client.post('/api/analyse/AO1').json()['findings']
    assert len(findings)>=2
    assert any(f['source']=='DCE/RC.txt' for f in findings)
    assert client.get(f'/api/files/AO1/{doc_id}/download').content==data
    assert client.delete(f'/api/files/AO1/{doc_id}').status_code==200


def test_excel_and_export(client):
    wb=Workbook();wb.active.append(['Désignation','Unité','Quantité']);wb.active.append(['Tableau','U',3]);mem=io.BytesIO();wb.save(mem)
    response=client.post('/api/spreadsheet/parse',files={'file':('metres.xlsx',mem.getvalue(),'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')})
    assert response.status_code==200
    assert response.json()['sheets'][0]['rows'][1][0]=='Tableau'
    excel=client.get('/api/export/AO1/dpgf.xlsx')
    assert excel.status_code==200
    wb=load_workbook(io.BytesIO(excel.content))
    assert wb['DPGF ST']['D27'].value==5
    data=client.get('/api/export/AO1/dossier.zip')
    assert data.status_code==200
    with zipfile.ZipFile(io.BytesIO(data.content)) as z:
        assert '00_A_LIRE_AVANT_DEPOT.txt' in z.namelist()
        assert 'Offre/SIE_DPGF_PROVISOIRE.xlsx' in z.namelist()
        assert b'PAS UNE OFFRE' in z.read('00_A_LIRE_AVANT_DEPOT.txt')


def test_archive_search(client):
    data=b'Nous garantissons une bonne gestion des dechets et la limitation des nuisances du chantier.'
    response=client.post('/api/files/AO2/upload',files={'file':('memoire.txt',data,'text/plain')},data={'category':'memoire'})
    assert response.status_code==200
    results=client.get('/api/history/search',params={'q':'dechets'}).json()['results']
    assert len(results)>=1
    assert results[0]['filename']=='memoire.txt'


def test_security_paths(client):
    resp=client.post('/api/files/../upload',files={'file':('x.txt',b'file','text/plain')},data={'category':'dce'})
    assert resp.status_code in (400,404,405)
    resp=client.post('/api/files/AO1/upload',files={'file':('x.txt',b'file','text/plain')},data={'category':'dce','relpath':'../../x.txt'})
    assert resp.status_code==400


def test_analyse_structuree_et_alertes(client):
    rc=('Règlement de la consultation\nConsultation n° TEST-42\n'
        'Date limite de remise des plis 15 / 11 / 2026 à 12 heures\n'
        'Les candidats doivent obligatoirement effectuer une visite du site.\n').encode('utf-8')
    r=client.post('/api/files/AO3/upload',files={'file':('RC.txt',rc,'text/plain')},data={'category':'dce','relpath':'DCE/TEST-42 RC.txt'})
    assert r.status_code==200,r.text
    body=client.post('/api/analyse/AO3').json()
    fiche=body['analyse']['fiche']
    assert fiche['reference']['valeur']=='TEST-42'
    assert fiche['date_limite']['valeur']=='15/11/2026 à 12h00'
    assert fiche['date_limite']['source']=='DCE/TEST-42 RC.txt'
    assert fiche['visite']['valeur']=='oui'
    assert body['fiche_interface']['visiteCondition']=='oui'
    # Les alertes sont persistées et suivies par un humain
    alertes=client.get('/api/alertes/AO3').json()['alertes']
    visite=next(a for a in alertes if a['titre']=='Visite obligatoire')
    assert visite['statut']=='À vérifier'
    assert client.patch(f"/api/alertes/AO3/{visite['id']}",json={'statut':'Traité','responsable':'Chargé d’affaires'}).status_code==200
    assert client.patch(f"/api/alertes/AO3/{visite['id']}",json={'statut':'N’importe quoi'}).status_code==400
    # Relancer l'analyse ne réinitialise pas le suivi humain
    client.post('/api/analyse/AO3')
    visite=next(a for a in client.get('/api/alertes/AO3').json()['alertes'] if a['titre']=='Visite obligatoire')
    assert visite['statut']=='Traité' and visite['responsable']=='Chargé d’affaires'
    # Dernière analyse relisible, journal alimenté
    assert client.get('/api/analyse/AO3').json()['analyse']['fiche']['reference']['valeur']=='TEST-42'
    actions=[j['action'] for j in client.get('/api/journal/AO3').json()['journal']]
    assert 'import_fichier' in actions and 'analyse_dce' in actions and 'alerte_modifiee' in actions


def test_pas_de_melange_entre_consultations_proches(client):
    # AO1 ne doit pas récupérer les brouillons d'AO10 (ancien filtre « consultation in clé »)
    body={'state':{'lines':[],'docs':[]},'sieContexts':{},'fiches':{},'metresStore':{},
          'sieMemoStore':{'AO1::1::Lot 1':{'sections':{'m':'texte AO1'}},'AO10::1::Lot 1':{'sections':{'m':'texte AO10'}}}}
    assert client.put('/api/state',json=body).status_code==200
    data=client.get('/api/export/AO1/dossier.zip')
    with zipfile.ZipFile(io.BytesIO(data.content)) as z:
        memos=z.read('Suivi/brouillons_memoire.json').decode('utf-8')
    assert 'texte AO1' in memos and 'texte AO10' not in memos


def test_import_par_blocs_rattache_a_sa_consultation(client):
    uid='a'*32
    r=client.post('/api/files/AO4/chunk',params={'upload_id':uid,'filename':'gros.txt','relpath':'DCE/gros.txt','index':0,'total':2},content=b'debut ')
    assert r.json()=={'complete':False,'next':1}
    # un autre dossier ne peut pas terminer cet import
    r=client.post('/api/files/AO5/chunk',params={'upload_id':uid,'filename':'gros.txt','relpath':'DCE/gros.txt','index':1,'total':2},content=b'fin')
    assert r.status_code==409
    r=client.post('/api/files/AO4/chunk',params={'upload_id':uid,'filename':'gros.txt','relpath':'DCE/gros.txt','index':1,'total':2},content=b'fin')
    assert r.json()['complete'] is True
    doc=r.json()['file']
    assert client.get(f"/api/files/AO4/{doc['id']}/download").content==b'debut fin'


def test_dpgf_acheteur_de_bout_en_bout(client, tmp_path):
    from openpyxl import Workbook
    wb=Workbook(); ws=wb.active; ws.title='Lot 3'
    ws.append(['N°','DESIGNATION','Unité','Qté','PU HT','Prix Total HT'])
    ws.append(['1','COURANT FORT']); ws.append(['1.1','Tableau','U']); ws.append(['1.2','Câbles','ml'])
    ws.append([None,'=CONCATENATE("Sous Total ",A2,".",B2)']); ws.append([None,'TOTAL BASE HT'])
    mem=io.BytesIO(); wb.save(mem)
    r=client.post('/api/files/AO6/upload',files={'file':('DPGF lot 3.xlsx',mem.getvalue(),'application/octet-stream')},data={'category':'dce','relpath':'DCE/DPGF/AO6 DPGF lot 3.xlsx'})
    assert r.status_code==200,r.text
    fichiers=client.get('/api/dpgf/AO6').json()['fichiers']
    assert len(fichiers)==1 and fichiers[0]['lot']=='3'
    doc=fichiers[0]['id']
    vue=client.get(f'/api/dpgf/AO6/{doc}').json()
    assert vue['controles']['postes']==2 and not vue['controles']['pret']
    # une ligne qui n'est pas un poste est refusée
    assert client.put(f'/api/dpgf/AO6/{doc}/saisies',json={'saisies':[{'ligne':2,'qte':1}]}).status_code==400
    assert client.put(f'/api/dpgf/AO6/{doc}/saisies',json={'saisies':[{'ligne':3,'qte':-1}]}).status_code==400
    vue=client.put(f'/api/dpgf/AO6/{doc}/saisies',json={'saisies':[{'ligne':3,'qte':2,'pu':150},{'ligne':4,'qte':12.5,'pu':4}]}).json()
    assert vue['controles']['pret'] and vue['controles']['total_general']==350
    # mise à jour partielle : seul le PU change, la quantité est conservée
    vue=client.put(f'/api/dpgf/AO6/{doc}/saisies',json={'saisies':[{'ligne':4,'pu':5}]}).json()
    assert vue['saisies']['4']['qte']==12.5 and vue['controles']['total_general']==362.5
    props=client.post(f'/api/dpgf/AO6/{doc}/rapprocher',json={'lignes':[{'reference':'1.2','designation':'x','quantite':20}]}).json()['propositions']
    assert props[0]['row']==4
    exp=client.get(f'/api/dpgf/AO6/{doc}/export')
    assert exp.status_code==200 and exp.headers['x-sie-total']=='362.5'
    out=load_workbook(io.BytesIO(exp.content))['Lot 3']
    assert out['D3'].value==2 and out['E3'].value==150 and out['F3'].value=='=D3*E3' and out['F6'].value=='=SUMPRODUCT(D2:D5,E2:E5)'
    assert 'dpgf_export' in [j['action'] for j in client.get('/api/journal/AO6').json()['journal']]


def test_controle_final_et_derogation(client):
    rc=('Règlement de la consultation\nConsultation n° CTL-1\nDate limite de remise des plis 15 / 12 / 2099 à 12 heures\n'
        'Les candidats doivent obligatoirement effectuer une visite du site.\n'
        'Le candidat remet l’attestation de visite signée et le cadre de réponse, sous peine de rejet de l’offre.\n').encode('utf-8')
    assert client.post('/api/files/AO7/upload',files={'file':('RC.txt',rc,'text/plain')},data={'category':'dce','relpath':'DCE/CTL-1 RC.txt'}).status_code==200
    client.post('/api/analyse/AO7')
    r=client.get('/api/controle/AO7').json()
    assert r['verdict']=='vide'
    assert client.post('/api/files/AO7/upload',files={'file':('Cadre de reponse.pdf',b'%PDF-1.4 x','application/pdf')},data={'category':'reponse','relpath':'Offre/Cadre de reponse.pdf'}).status_code==200
    r=client.get('/api/controle/AO7').json()
    visite=next(p for p in r['points'] if p['titre'].startswith('Attestation de visite'))
    assert visite['niveau']=='bloquant' and r['verdict']=='bloque'
    assert client.post('/api/controle/AO7/derogations',json={'code':visite['code'],'justification':'court'}).status_code==400
    r=client.post('/api/controle/AO7/derogations',json={'code':visite['code'],'justification':'Attestation remise en main propre le 12/12','auteur':'Directeur'}).json()
    assert not any(p['niveau']=='bloquant' for p in r['points'] if p['code']==visite['code'])
    data=client.get('/api/export/AO7/dossier.zip')
    with zipfile.ZipFile(io.BytesIO(data.content)) as z:
        assert 'Suivi/controle_final.json' in z.namelist()
        assert 'DÉROGATION' in z.read('00_A_LIRE_AVANT_DEPOT.txt').decode('utf-8')
    assert client.delete('/api/controle/AO7/derogations',params={'code':visite['code']}).status_code==200
    assert 'controle_derogation' in [j['action'] for j in client.get('/api/journal/AO7').json()['journal']]


def test_redaction_ia_simulee(client, monkeypatch):
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    monkeypatch.delenv('SIE_IA_FOURNISSEUR', raising=False)
    assert client.get('/api/ia/statut').json()['configure'] is False
    assert client.post('/api/ia/AO7/rediger', json={'critere': '1.1', 'libelle': 'x'}).status_code == 503
    monkeypatch.setenv('SIE_IA_FOURNISSEUR', 'simule')
    cctp = 'CCTP Lot 3 Electricite. Gestion des dechets de chantier : tri selectif et bordereaux de suivi. Site occupe.\n'.encode()
    assert client.post('/api/files/AO7/upload', files={'file': ('CCTP_Lot3.txt', cctp, 'text/plain')},
                       data={'category': 'dce', 'relpath': 'DCE/CCTP_Lot3.txt'}).status_code == 200
    memo = 'Memoire technique SIE. Nos equipes trient les dechets dans des bennes dediees et tiennent un registre.\n'.encode()
    assert client.post('/api/files/AO6/upload', files={'file': ('Memoire_2024.txt', memo, 'text/plain')},
                       data={'category': 'memoire', 'relpath': 'Memoire_2024.txt'}).status_code == 200
    st = client.get('/api/ia/statut').json()
    assert st['configure'] and st['fournisseur'] == 'simule' and st['archives_memoire'] >= 1 and 'sk-' not in str(st)
    r = client.post('/api/ia/AO7/rediger', json={'critere': '2.3', 'libelle': 'Gestion des déchets', 'lot': '3'})
    assert r.status_code == 200, r.text
    body = r.json()
    assert {s['origine'] for s in body['sources']} == {'dce', 'archive'}
    assert client.get('/api/ia/AO7/redactions').json()['redactions'][0]['critere']['code'] == '2.3'
    journal = client.get('/api/journal/AO7').json()
    assert 'Gestion des dechets de chantier' not in str(journal)   # le journal ne garde pas le texte


def test_etat_protege_contre_la_perte_d_une_consultation(client):
    etat = {'state': {'newCases': [{'id': 'AO42', 'name': 'x'}]}, 'baseCases': []}
    assert client.put('/api/state', json=etat).status_code == 200
    assert client.post('/api/files/AO42/upload', files={'file': ('RC.txt', b'reglement', 'text/plain')},
                       data={'category': 'dce', 'relpath': 'RC.txt'}).status_code == 200
    vide = {'state': {'newCases': []}, 'baseCases': []}
    r = client.put('/api/state', json=vide)
    assert r.status_code == 409 and 'AO42' in r.json()['detail']
    assert client.get('/api/state').json()['data']['state']['newCases'][0]['id'] == 'AO42'
    assert client.put('/api/state', json=vide, headers={'X-SIE-Suppression': 'confirmee'}).status_code == 200
    versions = client.get('/api/state/historique').json()['versions']
    assert 'AO42' in versions[0]['consultations']
    assert client.post(f"/api/state/historique/{versions[0]['id']}/restaurer").status_code == 200
    assert client.get('/api/state').json()['data']['state']['newCases'][0]['id'] == 'AO42'
