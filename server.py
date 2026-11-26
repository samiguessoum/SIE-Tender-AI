"""Serveur local SIE Tender Intelligence. Ne pas exposer sur Internet sans authentification."""
from __future__ import annotations

import asyncio
import csv
import hashlib
import io
import json
import os
import re
import shutil
import sqlite3
import tempfile
import threading
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import fitz
from docx import Document
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.background import BackgroundTask
from openpyxl import load_workbook
from openpyxl.styles import Font, PatternFill, Alignment

import analyse_dce

ROOT = Path(__file__).resolve().parent
DATA = Path(os.environ.get('SIE_DATA_DIR', ROOT / 'data')).resolve()
FILES = DATA / 'files'
TEMP = DATA / '.pending'
for path in (DATA, FILES, TEMP):
    path.mkdir(parents=True, exist_ok=True)
DB = DATA / 'sie.db'
LOCK = threading.RLock()
app = FastAPI(title='SIE Tender Intelligence (prototype local)', version='1.0')


def db():
    cx = sqlite3.connect(DB, check_same_thread=False)
    cx.row_factory = sqlite3.Row
    cx.execute('PRAGMA journal_mode=WAL')
    cx.execute('PRAGMA busy_timeout=4000')
    return cx


def setup():
    with db() as cx:
        cx.execute('CREATE TABLE IF NOT EXISTS app_state (id INTEGER PRIMARY KEY CHECK (id = 1), payload TEXT NOT NULL, updated TEXT NOT NULL)')
        cx.execute('''CREATE TABLE IF NOT EXISTS documents (
            id TEXT PRIMARY KEY, consultation TEXT NOT NULL, category TEXT NOT NULL,
            relpath TEXT NOT NULL, filename TEXT NOT NULL, storepath TEXT NOT NULL,
            size INTEGER NOT NULL, sha256 TEXT NOT NULL, created TEXT NOT NULL,
            document_type TEXT NOT NULL DEFAULT '')''')
        cx.execute('CREATE INDEX IF NOT EXISTS idx_documents_consultation ON documents(consultation)')
        # Résultats d'analyse du DCE (historisés : on garde chaque passage)
        cx.execute('CREATE TABLE IF NOT EXISTS analyses (id INTEGER PRIMARY KEY AUTOINCREMENT, consultation TEXT NOT NULL, '
                   'created TEXT NOT NULL, resultat TEXT NOT NULL)')
        cx.execute('CREATE INDEX IF NOT EXISTS idx_analyses_consultation ON analyses(consultation)')
        # Registre des alertes / exigences sourcées, avec suivi humain (statut, responsable)
        cx.execute("CREATE TABLE IF NOT EXISTS alertes (id INTEGER PRIMARY KEY AUTOINCREMENT, consultation TEXT NOT NULL, "
                   "cle TEXT NOT NULL, categorie TEXT, priorite TEXT, titre TEXT NOT NULL, detail TEXT, source TEXT, page INTEGER, "
                   "lots TEXT, statut TEXT NOT NULL DEFAULT 'À vérifier', responsable TEXT NOT NULL DEFAULT '', "
                   "note TEXT NOT NULL DEFAULT '', origine TEXT NOT NULL DEFAULT 'analyse', created TEXT NOT NULL, "
                   "updated TEXT NOT NULL, UNIQUE(consultation, cle))")
        # Journal des actions (traçabilité demandée par les spécifications)
        cx.execute('CREATE TABLE IF NOT EXISTS journal (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, '
                   'consultation TEXT, action TEXT NOT NULL, detail TEXT)')
        cx.execute('CREATE INDEX IF NOT EXISTS idx_journal_consultation ON journal(consultation)')
setup()


def journaliser(consultation, action: str, detail=''):
    try:
        with LOCK, db() as cx:
            cx.execute('INSERT INTO journal(ts,consultation,action,detail) VALUES (?,?,?,?)',
                       (timestamp(), consultation, action, detail if isinstance(detail, str) else json.dumps(detail, ensure_ascii=False)))
    except sqlite3.Error:
        pass


def safe_id(value: str):
    if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_.-]{0,95}', value):
        raise HTTPException(400, 'Identifiant de consultation invalide')
    return value


def safe_relpath(value: str):
    parts = [p.strip() for p in value.replace('\\', '/').split('/') if p.strip()]
    if not parts or any(p in ('.','..') or '\x00' in p or ':' in p for p in parts):
        raise HTTPException(400, 'Chemin de fichier invalide')
    cleaned = [re.sub(r'[<>:"|?*\x00-\x1f]', '_', p)[:180] for p in parts]
    return '/'.join(cleaned)[:1000]


def safe_category(value: str):
    if value not in ('dce', 'reponse', 'devis', 'memoire', 'metres', 'autre'):
        raise HTTPException(400, 'Catégorie invalide')
    return value


def timestamp():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def record_document(consultation: str, category: str, relative_path: str, path: Path, doc_type: str = ''):
    doc_id = uuid.uuid4().hex
    targetdir = FILES / consultation
    targetdir.mkdir(parents=True, exist_ok=True)
    target = targetdir / doc_id
    checksum = hashlib.sha256()
    with path.open('rb') as reader, target.open('wb') as writer:
        while chunk := reader.read(1024 * 1024):
            checksum.update(chunk)
            writer.write(chunk)
    size = target.stat().st_size
    row = (doc_id, consultation, category, relative_path, Path(relative_path).name, str(target), size, checksum.hexdigest(), timestamp(), doc_type[:100])
    with LOCK, db() as cx:
        cx.execute('INSERT INTO documents VALUES (?,?,?,?,?,?,?,?,?,?)', row)
    return {'id':doc_id,'consultation':consultation,'category':category,'relpath':relative_path,'filename':Path(relative_path).name,'size':size,'sha256':checksum.hexdigest(),'created':row[-2],'document_type':doc_type}


def row_public(row):
    return {k: row[k] for k in row.keys() if k != 'storepath'}


def get_doc(consultation, doc_id):
    safe_id(consultation)
    if not re.fullmatch(r'[a-f0-9]{32}', doc_id):
        raise HTTPException(404, 'Fichier introuvable')
    with db() as cx:
        row = cx.execute('SELECT * FROM documents WHERE consultation=? AND id=?', (consultation, doc_id)).fetchone()
    if row is None:
        raise HTTPException(404, 'Fichier introuvable')
    return row


def get_state():
    with db() as cx:
        row = cx.execute('SELECT payload FROM app_state WHERE id=1').fetchone()
    return json.loads(row['payload']) if row else None


@app.get('/')
def root():
    return FileResponse(ROOT / 'static' / 'index.html')


@app.get('/api/health')
def health():
    return {'status':'ok','mode':'local','version':'1.0','storage':str(DATA)}


@app.get('/api/state')
def state_get():
    return {'data':get_state()}


@app.put('/api/state')
async def state_put(request: Request):
    raw = await request.body()
    if len(raw) > 12 * 1024 * 1024:
        raise HTTPException(413, 'État applicatif trop volumineux')
    try:
        state = json.loads(raw)
        if not isinstance(state, dict):
            raise ValueError('L’état doit être un objet')
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(400, 'JSON invalide')
    with LOCK, db() as cx:
        cx.execute('INSERT INTO app_state(id,payload,updated) VALUES(1,?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload,updated=excluded.updated', (json.dumps(state,ensure_ascii=False),timestamp()))
    return {'ok':True,'saved_at':timestamp()}


@app.get('/api/files/{consultation}')
def files_list(consultation: str):
    safe_id(consultation)
    with db() as cx:
        rows = cx.execute('SELECT * FROM documents WHERE consultation=? ORDER BY created DESC', (consultation,)).fetchall()
    return {'files':[row_public(row) for row in rows]}


@app.post('/api/files/{consultation}/upload')
async def files_upload(consultation: str, file: UploadFile = File(...), category: str = Form('dce'), relpath: str = Form(''), document_type: str = Form('')):
    safe_id(consultation)
    safe_category(category)
    relative = safe_relpath(relpath or file.filename or 'document')
    with tempfile.NamedTemporaryFile(dir=TEMP, delete=False) as tmp:
        temp = Path(tmp.name)
        try:
            while chunk := await file.read(1024 * 1024):
                tmp.write(chunk)
        except Exception:
            temp.unlink(missing_ok=True)
            raise
    try:
        saved = record_document(consultation,category,relative,temp,document_type)
    finally:
        temp.unlink(missing_ok=True)
        await file.close()
    journaliser(consultation, 'import_fichier', {'fichier': relative, 'categorie': category, 'taille': saved['size']})
    return {'file':saved}


_IMPORTS_EN_COURS: dict[str, asyncio.Lock] = {}


@app.post('/api/files/{consultation}/chunk')
async def files_chunk(request: Request, consultation: str, upload_id: str, filename: str, relpath: str, category: str='dce', document_type: str='', index: int=0, total: int=1):
    safe_id(consultation); safe_category(category)
    relpath=safe_relpath(relpath or filename)
    if not re.fullmatch(r'[a-f0-9]{32}',upload_id) or total<1 or total>200000 or index<0 or index>=total:
        raise HTTPException(400,'Session d’import invalide')
    source=TEMP / (upload_id+'.part')
    pos=TEMP / (upload_id+'.next')
    owner=TEMP / (upload_id+'.owner')
    # Verrou asyncio propre à cet import : l'ancien RLock de threading ne protégeait rien entre deux « await ».
    verrou=_IMPORTS_EN_COURS.setdefault(upload_id, asyncio.Lock())
    async with verrou:
        if index == 0:
            owner.write_text(consultation)
        elif not owner.exists() or owner.read_text() != consultation:
            raise HTTPException(409,'Import rattaché à une autre consultation ou expiré')
        expected=int(pos.read_text()) if pos.exists() else 0
        if index != expected:
            raise HTTPException(409,f'Bloc attendu : {expected}')
        size=0
        try:
            with source.open('ab' if index else 'wb') as stream:
                async for chunk in request.stream():
                    size+=len(chunk)
                    if size>10*1024*1024:
                        raise HTTPException(413,'Bloc trop volumineux (10 Mo max)')
                    stream.write(chunk)
        except HTTPException:
            source.unlink(missing_ok=True); pos.unlink(missing_ok=True); owner.unlink(missing_ok=True)
            raise
        if index == total-1:
            try:
                saved = record_document(consultation,category,relpath,source,document_type)
            finally:
                source.unlink(missing_ok=True); pos.unlink(missing_ok=True); owner.unlink(missing_ok=True)
                _IMPORTS_EN_COURS.pop(upload_id, None)
            journaliser(consultation, 'import_fichier', {'fichier': relpath, 'categorie': category, 'taille': saved['size'], 'blocs': total})
            return {'complete':True,'file':saved}
        pos.write_text(str(index+1))
    return {'complete':False,'next':index+1}


@app.get('/api/files/{consultation}/{doc_id}/download')
def files_download(consultation: str, doc_id: str):
    row=get_doc(consultation,doc_id)
    return FileResponse(row['storepath'], filename=row['filename'], media_type='application/octet-stream')


@app.delete('/api/files/{consultation}/{doc_id}')
def files_delete(consultation: str, doc_id: str):
    row=get_doc(consultation,doc_id)
    with LOCK, db() as cx:
        cx.execute('DELETE FROM documents WHERE consultation=? AND id=?',(consultation,doc_id))
    Path(row['storepath']).unlink(missing_ok=True)
    journaliser(consultation, 'suppression_fichier', {'fichier': row['relpath']})
    return {'ok':True}


@app.post('/api/pdf/info')
async def pdf_info(file: UploadFile=File(...)):
    if not (file.filename or '').lower().endswith('.pdf'):
        raise HTTPException(400,'Sélectionnez un PDF')
    content=await file.read(60*1024*1024+1)
    if len(content)>60*1024*1024:
        raise HTTPException(413,'PDF trop volumineux pour lecture directe (60 Mo)')
    try:
        with fitz.open(stream=content,filetype='pdf') as pdf:
            return {'pages':len(pdf)}
    except Exception:
        raise HTTPException(400,'PDF illisible')


@app.post('/api/pdf/extract')
async def pdf_extract(file:UploadFile=File(...), ranges: str=Form(...)):
    try:
        pages=json.loads(ranges)
        if not isinstance(pages,list) or len(pages)>80:
            raise ValueError()
    except (ValueError, TypeError):
        raise HTTPException(400,'Plages de pages invalides')
    content=await file.read(60*1024*1024+1)
    if len(content)>60*1024*1024:
        raise HTTPException(413,'PDF trop volumineux pour lecture directe (60 Mo)')
    try:
        source=fitz.open(stream=content,filetype='pdf')
        out=fitz.open()
        for item in pages:
            a,b=int(item['start']),int(item['end'])
            if a<1 or b<a or b>len(source):
                raise ValueError('Pages en dehors du document')
            out.insert_pdf(source,from_page=a-1,to_page=b-1)
        result=out.tobytes(garbage=3,deflate=True)
        out.close(); source.close()
    except Exception as exc:
        raise HTTPException(400,f'Extraction PDF impossible : {exc}')
    return Response(result,media_type='application/pdf',headers={'Content-Disposition':'attachment; filename="CCTP_extraits_SIE.pdf"'})


RULES = {
    'Administratif': [r'limite de remise',r'date limite',r'visite obligatoire',r'attestation de visite',r'signature',r'candidature',r'qualification'],
    'Technique': [r'coactivit[eé]',r'interfaces?',r'CFO',r'CFA',r'courants? faibles?',r'courants? forts?',r'SSI',r'd[eé]senfumage',r'phasage'],
    'RSE / environnement': [r'insertion',r'heures? d.insertion',r'd[eé]chets?',r'nuisances?',r'environnement',r'empreinte carbone'],
    'Économique': [r'DPGF',r'prix forfaitaires?',r'r[eé]vision des prix',r'montant total',r'variantes?'],
}


def lines_from_document(filename: str, contents: bytes):
    suffix=Path(filename).suffix.lower()
    if suffix == '.pdf':
        try:
            with fitz.open(stream=contents,filetype='pdf') as pdf:
                for page in range(min(len(pdf),500)):
                    text=pdf[page].get_text('text')
                    for line in text.splitlines():
                        if line.strip(): yield page+1,line.strip()
        except Exception:
            return
    elif suffix == '.docx':
        try:
            d=Document(io.BytesIO(contents))
            for p in d.paragraphs:
                if p.text.strip():yield None,p.text.strip()
            for t in d.tables:
                for row in t.rows:
                    text=' | '.join(c.text.strip() for c in row.cells)
                    if text.strip():yield None,text
        except Exception:
            return
    elif suffix in ('.txt','.md','.csv'):
        for i,line in enumerate(contents.decode('utf-8',errors='replace').splitlines()[:10000],1):
            if line.strip(): yield i,line.strip()


def scan_one(filename: str, contents: bytes, prefix=''):
    if len(contents)>35*1024*1024:
        return []
    out=[]
    if filename.lower().endswith('.zip'):
        try:
            with zipfile.ZipFile(io.BytesIO(contents)) as z:
                files=[x for x in z.infolist() if not x.is_dir() and x.file_size<=18*1024*1024]
                for f in files[:120]:
                    if sum(x.file_size for x in files[:120])>100*1024*1024:break
                    if Path(f.filename).suffix.lower() not in ('.pdf','.docx','.txt','.md','.csv'):continue
                    out.extend(scan_one(f.filename,z.read(f),prefix+filename+' / '))
                    if len(out)>100:break
        except Exception:
            pass
        return out[:100]
    for page,line in lines_from_document(filename,contents):
        if len(line)<12:continue
        for category,patterns in RULES.items():
            if any(re.search(p,line,re.IGNORECASE) for p in patterns):
                out.append({'category':category,'source':prefix+filename,'page':page,'excerpt':line[:360],'status':'À vérifier','validated':False})
                break
        if len(out)>=80:break
    return out


def _cle_alerte(a):
    return hashlib.sha1(((a.get('titre') or '') + '|' + (a.get('source') or '')).encode('utf-8')).hexdigest()


def _alertes(consultation):
    with db() as cx:
        rows = cx.execute("SELECT * FROM alertes WHERE consultation=? ORDER BY CASE priorite WHEN 'haute' THEN 0 "
                          "WHEN 'moyenne' THEN 1 ELSE 2 END, id", (consultation,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d.pop('cle', None)
        d['lots'] = json.loads(d['lots']) if d.get('lots') else []
        out.append(d)
    return out


@app.post('/api/analyse/{consultation}')
def analyse_documents(consultation: str):
    # Analyse structurée du DCE : classement des pièces, lecture par priorité (Q/R, RC, CCAP, cadre de réponse...),
    # extraction de la fiche avec sources, alertes et vigilances. Le repérage lexical d'origine est conservé en complément.
    safe_id(consultation)
    with db() as cx:
        rows=cx.execute("SELECT * FROM documents WHERE consultation=? AND category='dce' ORDER BY relpath", (consultation,)).fetchall()
    docs=[dict(r) for r in rows]
    resultat=analyse_dce.analyser(docs, cache_dir=DATA/'texte')
    ts=timestamp()
    with LOCK, db() as cx:
        cx.execute('INSERT INTO analyses(consultation,created,resultat) VALUES (?,?,?)',
                   (consultation, ts, json.dumps(resultat, ensure_ascii=False)))
        for a in resultat['alertes']:
            cx.execute('INSERT INTO alertes(consultation,cle,categorie,priorite,titre,detail,source,page,lots,created,updated) '
                       'VALUES (?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(consultation,cle) DO UPDATE SET detail=excluded.detail, '
                       'priorite=excluded.priorite, page=excluded.page, lots=excluded.lots, updated=excluded.updated',
                       (consultation, _cle_alerte(a), a.get('categorie'), a.get('priorite'), a['titre'], a.get('detail'),
                        a.get('source'), a.get('page'), json.dumps(a.get('lots') or []), ts, ts))
    # Repérage lexical complémentaire : seulement les pièces écrites lues (jamais les plans), réparti entre elles.
    lus = {e['relpath'] for e in resultat['inventaire'] if e.get('lu')}
    ordre = sorted([d for d in docs if d['relpath'] in lus],
                   key=lambda d: (analyse_dce.TYPES[analyse_dce.classer(d['relpath'])][0], d['relpath']))
    reperage = []
    for d in ordre:
        try:
            with open(d['storepath'],'rb') as f:
                contenu=f.read(35*1024*1024+1)
        except OSError:
            continue
        reperage.extend(scan_one(d['relpath'],contenu)[:15])
        if len(reperage)>=150:
            break
    findings=[{'category':a.get('categorie') or 'Administratif','source':a.get('source') or '','page':a.get('page'),
               'excerpt':(a['titre']+' — '+(a.get('detail') or ''))[:360],'status':'À vérifier','validated':False,
               'priorite':a.get('priorite')} for a in resultat['alertes']]
    findings+=[{'category':'Questions-réponses','source':v['source'],'page':v['page'],
                'excerpt':f"Q/R n°{v['question']} : {v['texte'][:330]}",'status':'À vérifier','validated':False}
               for v in resultat['vigilances_qr'] if v['motifs']]
    findings+=reperage
    syn = resultat['synthese']
    journaliser(consultation, 'analyse_dce', {'documents': syn['documents'], 'lus': syn['documents_lus'],
                                              'champs_extraits': len(syn['champs_extraits']), 'alertes': syn['alertes']})
    return {'consultation':consultation,'documents_scanned':syn['documents_lus'],'findings':findings[:400],
            'analyse':resultat,'fiche_interface':analyse_dce.fiche_pour_interface(resultat),
            'alertes':_alertes(consultation),'notice':resultat['avertissement']}


@app.get('/api/analyse/{consultation}')
def analyse_derniere(consultation: str):
    safe_id(consultation)
    with db() as cx:
        row=cx.execute('SELECT created,resultat FROM analyses WHERE consultation=? ORDER BY id DESC LIMIT 1',(consultation,)).fetchone()
    if not row:
        return {'consultation':consultation,'analyse':None,'alertes':_alertes(consultation)}
    resultat=json.loads(row['resultat'])
    return {'consultation':consultation,'date':row['created'],'analyse':resultat,
            'fiche_interface':analyse_dce.fiche_pour_interface(resultat),'alertes':_alertes(consultation)}


@app.get('/api/alertes/{consultation}')
def alertes_liste(consultation: str):
    safe_id(consultation)
    return {'alertes':_alertes(consultation)}


@app.patch('/api/alertes/{consultation}/{alerte_id}')
async def alertes_maj(consultation: str, alerte_id: int, request: Request):
    safe_id(consultation)
    try:
        body=await request.json()
    except ValueError:
        raise HTTPException(400,'JSON invalide')
    champs={k:str(v)[:2000] for k,v in (body or {}).items() if k in ('statut','responsable','note')}
    if not champs:
        raise HTTPException(400,'Rien à modifier')
    if 'statut' in champs and champs['statut'] not in ('À vérifier','En cours','Traité','Bloquant','Sans objet'):
        raise HTTPException(400,'Statut invalide')
    with LOCK, db() as cx:
        n=cx.execute(f"UPDATE alertes SET {', '.join(k+'=?' for k in champs)}, updated=? WHERE consultation=? AND id=?",
                     (*champs.values(), timestamp(), consultation, alerte_id)).rowcount
    if not n:
        raise HTTPException(404,'Alerte introuvable')
    journaliser(consultation, 'alerte_modifiee', {'id': alerte_id, **champs})
    return {'ok':True}


@app.get('/api/journal/{consultation}')
def journal_liste(consultation: str, limit: int = 200):
    safe_id(consultation)
    with db() as cx:
        rows=cx.execute('SELECT ts,action,detail FROM journal WHERE consultation=? ORDER BY id DESC LIMIT ?',
                        (consultation,max(1,min(limit,2000)))).fetchall()
    return {'journal':[dict(r) for r in rows]}


def workbook_for_case(consultation, snapshot):
    wb=load_workbook(ROOT/'static'/'modele_DPGF_SIE.xlsx')
    sh=wb['DPGF ST']
    current=snapshot.get('state',{})
    contexts=snapshot.get('sieContexts',{})
    payload=contexts.get(consultation,{})
    lines=payload.get('lines') or current.get('lines',[])
    offers=payload.get('offers') or snapshot.get('sieOffers',[])
    selected=payload.get('selected') or snapshot.get('sieSelected',{})
    for i,line in enumerate(lines):
        r=27+i
        if r>1119:break
        sh[f'A{r}']=str(line.get('id',''))
        sh[f'B{r}']=str(line.get('name',''))
        sh[f'C{r}']=str(line.get('unit',''))
        qty=line.get('qty')
        if qty is not None:
            try: sh[f'D{r}']=float(qty)
            except (ValueError,TypeError): pass
        supplier=next((o for o in offers if o.get('id')==selected.get(line.get('id'))),None)
        price=supplier.get('prices',{}).get(line.get('id')) if supplier else line.get('price')
        if price is not None:
            try:sh[f'E{r}']=float(price)
            except (ValueError,TypeError):pass
    track=wb.create_sheet('Suivi fournisseurs')
    track.append(['Code','Désignation','Quantité','Unité','Fournisseur sélectionné','PU achat (€ HT)','Montant achat HT','Statut'])
    for i,line in enumerate(lines):
        supplier=next((o for o in offers if o.get('id')==selected.get(line.get('id'))),None)
        pu=supplier.get('prices',{}).get(line.get('id')) if supplier else line.get('price')
        qty=line.get('qty')
        amount=(float(qty)*float(pu)) if qty is not None and pu is not None else None
        track.append([line.get('id'),line.get('name'),qty,line.get('unit'),supplier.get('supplier') if supplier else 'À vérifier',pu,amount,'Prix à valider' if pu is not None else 'Prix manquant'])
    for cell in track[1]:cell.font=Font(color='FFFFFF',bold=True);cell.fill=PatternFill('solid',fgColor='173757')
    for col,width in {'A':18,'B':55,'C':15,'D':15,'E':33,'F':22,'G':24,'H':24}.items():track.column_dimensions[col].width=width
    track.freeze_panes='A2'
    out=io.BytesIO();wb.save(out)
    return out.getvalue()


@app.get('/api/export/{consultation}/dpgf.xlsx')
def export_dpgf(consultation: str):
    safe_id(consultation)
    payload=workbook_for_case(consultation,get_state() or {})
    return Response(payload,media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',headers={'Content-Disposition':f'attachment; filename="SIE_DPGF_{consultation}_PROVISOIRE.xlsx"'})


@app.get('/api/export/{consultation}/dossier.zip')
def export_case(consultation: str):
    safe_id(consultation)
    snapshot=get_state() or {}
    with db() as cx:
        docs=cx.execute('SELECT * FROM documents WHERE consultation=? ORDER BY created',(consultation,)).fetchall()
    active=(snapshot.get('sieContexts',{}).get(consultation) or {})
    state=snapshot.get('state',{})
    memo=snapshot.get('sieMemoStore',{})
    fic=(snapshot.get('fiches',{}) or {}).get(consultation,{})
    lines=active.get('lines') or state.get('lines') or []
    checks=active.get('docs') or state.get('docs') or []
    missing=[d.get('name','') for d in checks if d.get('required')=='Obligatoire' and not (d.get('received') and d.get('validated'))]
    archive=TEMP / (uuid.uuid4().hex+'.zip')
    with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=5) as z:
        header=f'SIE Tender Intelligence — dossier de travail {consultation}\n'
        header+=f'Exporté le {timestamp()} (UTC)\n\n'
        header+='CE DOSSIER N’EST PAS UNE OFFRE VÉRIFIÉE, SIGNÉE OU DÉPOSÉE.\nTous les éléments doivent être relus et validés par SIE.\n\n'
        header+=('Points de contrôle obligatoires non entièrement validés :\n'+'\n'.join('- '+v for v in missing)) if missing else 'Liste de complétude : contrôler tous les éléments avant tout dépôt.'
        z.writestr('00_A_LIRE_AVANT_DEPOT.txt',header)
        z.writestr('Suivi/fiche_renseignement.json',json.dumps(fic,ensure_ascii=False,indent=2))
        z.writestr('Suivi/controle_pieces.json',json.dumps(checks,ensure_ascii=False,indent=2))
        z.writestr('Suivi/alertes.json',json.dumps(active.get('alerts') or snapshot.get('sieAlerts',[]),ensure_ascii=False,indent=2))
        z.writestr('Suivi/decomptes.json',json.dumps((snapshot.get('metresStore',{}) or {}).get(consultation,[]),ensure_ascii=False,indent=2))
        z.writestr('Suivi/brouillons_memoire.json',json.dumps({k:v for k,v in memo.items() if k.startswith(consultation+'::')},ensure_ascii=False,indent=2))
        csvfile=io.StringIO();writer=csv.writer(csvfile,delimiter=';');writer.writerow(['Code','Désignation','Unité','Quantité','PU HT','Montant HT'])
        for l in lines:
            qty,pu=l.get('qty'),l.get('price')
            writer.writerow([l.get('id',''),l.get('name',''),l.get('unit',''),qty if qty is not None else '',pu if pu is not None else '',round(float(qty)*float(pu),2) if qty is not None and pu is not None else ''])
        z.writestr('Offre/DPGF_postes_travail.csv','\ufeff'+csvfile.getvalue())
        z.writestr('Offre/SIE_DPGF_PROVISOIRE.xlsx',workbook_for_case(consultation,snapshot))
        category_folder={'dce':'DCE_original','reponse':'Offre/Pieces_reponse','devis':'Chiffrage/Devis_fournisseurs','memoire':'Offre/Memoires','metres':'Chiffrage/Metres','autre':'Annexes'}
        for row in docs:
            path=Path(row['storepath'])
            if path.is_file():
                rel=safe_relpath(row['relpath'])
                prefix=category_folder.get(row['category'],'Annexes')
                z.write(path,arcname=prefix+'/'+row['id'][:8]+'_'+rel)
        z.writestr('Suivi/inventaire_documents.json',json.dumps([row_public(d) for d in docs],ensure_ascii=False,indent=2))
    journaliser(consultation, 'export_dossier_zip', {'fichiers': len(docs)})
    return FileResponse(archive,filename=f'SIE_{consultation}_DOSSIER_DE_TRAVAIL.zip',media_type='application/zip',background=BackgroundTask(lambda: archive.unlink(missing_ok=True)))


app.mount('/static',StaticFiles(directory=ROOT/'static'),name='static')

@app.post('/api/spreadsheet/parse')
async def spreadsheet_parse(file: UploadFile=File(...)):
    filename=(file.filename or '').lower()
    if not filename.endswith(('.xlsx','.xlsm','.csv','.xls')):
        raise HTTPException(400,'Importer un fichier Excel ou CSV')
    buf=await file.read(30*1024*1024+1)
    if len(buf)>30*1024*1024:raise HTTPException(413,'Tableau trop volumineux (30 Mo maximum)')
    sheets=[]
    if filename.endswith('.csv'):
        import codecs
        text=buf.decode('utf-8-sig',errors='replace')
        try: dialect=csv.Sniffer().sniff(text[:4096],delimiters=',;\t')
        except csv.Error: dialect=csv.excel
        sheets=[{'name':'CSV','rows':list(csv.reader(io.StringIO(text),dialect))[:5000]}]
    elif filename.endswith('.xls'):
        raise HTTPException(422,'Format .xls ancien non pris en charge en mode local. Convertir en .xlsx ou .csv.')
    else:
        try:
            wb=load_workbook(io.BytesIO(buf),read_only=True,data_only=True)
            for ws in wb.worksheets:
                rows=[]
                for i,row in enumerate(ws.values):
                    if i>=5000:break
                    if not any(v is not None for v in row):continue
                    rows.append(['' if v is None else str(v) for v in row[:80]])
                sheets.append({'name':ws.title,'rows':rows})
            wb.close()
        except Exception as exc:
            raise HTTPException(422,f'Fichier Excel non lisible : {exc}')
    return {'filename':file.filename,'size':len(buf),'sheets':sheets}

@app.post('/api/state/beacon')
async def state_beacon(request: Request):
    return await state_put(request)

@app.get('/api/history/search')
def search_archives(q: str):
    terms=[s.casefold() for s in re.findall(r'[\wÀ-ÿ]{3,}',q) if s.casefold() not in ('avec','dans','pour','chez','tout','tous','plus')]
    if not terms or len(q)>250:
        raise HTTPException(400,'Recherche incorrecte')
    with db() as cx:
        rows=cx.execute("SELECT * FROM documents WHERE category='memoire' ORDER BY created DESC LIMIT 500").fetchall()
    out=[]
    for row in rows:
        try:
            path=Path(row['storepath'])
            if path.stat().st_size>30*1024*1024:continue
            contents=path.read_bytes()
            for page,line in lines_from_document(row['filename'],contents):
                hit=sum(t in line.casefold() for t in terms)
                if hit>0 and len(line)>=15:
                    out.append({'filename':row['filename'],'consultation':row['consultation'],'page':page,
                                'excerpt':line[:480],'score':hit,'document_id':row['id']})
                if len(out)>200:break
        except OSError:
            continue
    out.sort(key=lambda x:-x['score'])
    return {'results':out[:40],'notice':'Recherche lexicale indicative : vérifier toute source avant réutilisation.'}

if __name__=='__main__':
    import uvicorn
    uvicorn.run('server:app', host='127.0.0.1', port=int(os.environ.get('PORT','8000')), reload=False)

