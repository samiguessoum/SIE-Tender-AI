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
