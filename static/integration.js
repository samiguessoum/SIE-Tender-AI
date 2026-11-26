/* SIE Tender Intelligence : couche fonctionnelle locale, stockage serveur, imports et exports. */
'use strict';
let sieReady=false, sieSaving=false, sieDirty=false, sieSaveTimer=null;
let siePendingFiles=[], sieFileCache={}, sieFindings={}, sieUploadBusy=false;
let sieStorageStatus='Chargement des données locales…';
const sieApi=async(url,opts={})=>{
 const response=await fetch(url,opts);
 if(!response.ok){let detail='';try{const x=await response.json();detail=String(x.detail||'')}catch(e){}throw Error(detail||`Erreur HTTP ${response.status}`)}
 return response;
};
const sieJson=async(url,opts={})=>(await sieApi(url,opts)).json();
const sieDate=()=>new Date().toLocaleString('fr-FR');
const sieCurrentId=()=>dceCase().id;
const sieFiles=()=>sieFileCache[sieCurrentId()]||[];
const sieSafe=(value)=>esc(value);
function sieSnapshot(){
 try {sieSaveContext()}catch(e){console.warn('Contexte non copié',e)}
 const data={
  state:{...state,dcePending:[],dceBusy:false,selected:state.selected},
  baseCases:cases, sieContexts, metresStore, fiches:state.fiches, sieMemoStore, sieMemoSettings,
  sieMemoActiveLot, sieSuppliers, sieRequests, sieRanges, sieOffers:sieOffers.map(o=>({...o,file:null})),sieSelected,
  sieAlerts, sieSettings, sieHistory, sieLocalRagConfig
 };
 return JSON.parse(JSON.stringify(data));
}
function sieApplySnapshot(snapshot){
 if(!snapshot)return;
 if(Array.isArray(snapshot.baseCases))cases.splice(0,cases.length,...snapshot.baseCases);
 if(snapshot.state){Object.assign(state,snapshot.state);state.dcePending=[];state.dceBusy=false;}
 for(const [target,source] of [[sieContexts,snapshot.sieContexts],[metresStore,snapshot.metresStore],[sieMemoStore,snapshot.sieMemoStore],[sieMemoSettings,snapshot.sieMemoSettings],[sieMemoActiveLot,snapshot.sieMemoActiveLot],[sieSettings,snapshot.sieSettings]]){
  if(source&&typeof source==='object'){Object.keys(target).forEach(k=>delete target[k]);Object.assign(target,source)}
 }
 if(snapshot.sieSuppliers)sieSuppliers=snapshot.sieSuppliers;
 if(snapshot.sieRequests)sieRequests=snapshot.sieRequests;
 if(snapshot.sieRanges)sieRanges=snapshot.sieRanges;
 if(snapshot.sieOffers)sieOffers=snapshot.sieOffers.map(o=>({...o,file:null}));
 if(snapshot.sieSelected)sieSelected=snapshot.sieSelected;
 if(snapshot.sieAlerts)sieAlerts=snapshot.sieAlerts;
 if(snapshot.sieHistory)sieHistory=snapshot.sieHistory;
 if(snapshot.sieLocalRagConfig)sieLocalRagConfig=snapshot.sieLocalRagConfig;
 const all=[...cases,...state.newCases];
 if(!all[state.selected])state.selected=0;
 const c=all[state.selected];if(c)sieLoadContext(c.id);
}
async function siePersist(){
 if(!sieReady||sieSaving){sieDirty=true;return}
 sieSaving=true; sieDirty=false;
 try{
  await sieApi('/api/state',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(sieSnapshot())});
  sieStorageStatus='Sauvegardé sur cet ordinateur à '+sieDate();
 }catch(e){console.error('Sauvegarde',e);sieStorageStatus='Échec de sauvegarde : '+e.message;toast(sieStorageStatus)}
 finally{sieSaving=false;sieStorageBadge();if(sieDirty)sieQueueSave()}
}
function sieQueueSave(){if(!sieReady)return;clearTimeout(sieSaveTimer);sieSaveTimer=setTimeout(siePersist,650)}
function sieStorageBadge(){const e=document.getElementById('sie-storage-status');if(e)e.textContent=sieStorageStatus}
async function sieFetchFiles(consultation=sieCurrentId()){
 try{sieFileCache[consultation]=(await sieJson('/api/files/'+encodeURIComponent(consultation))).files||[]}
 catch(e){console.error(e);toast('Inventaire indisponible : '+e.message)}
}
function sieNiceSize(size){return dceSize(size)}
function sieFileRows(category){
 const files=sieFiles().filter(f=>!category||f.category===category);
 return files.length?files.map(f=>`<div class="dce-file" style="gap:12px;margin:4px 0"><span>▤</span><span style="flex:1;min-width:0;overflow-wrap:anywhere"><b>${esc(f.relpath)}</b><br><small>${esc(f.category)} · ${sieNiceSize(f.size)} · ${esc(f.created.slice(0,16).replace('T',' '))}${f.document_type?' · '+esc(f.document_type):''}</small></span><a class="btn sm" href="/api/files/${encodeURIComponent(f.consultation)}/${f.id}/download">↓ Télécharger</a><button class="btn sm" onclick="sieDeleteFile('${f.id}')">Supprimer</button></div>`).join(''):'<p class="small">Aucun fichier enregistré dans cette catégorie pour cette consultation.</p>';
}
async function sieDeleteFile(id){
 if(!confirm('Supprimer définitivement ce fichier du stockage local ?'))return;
 try{await sieApi('/api/files/'+encodeURIComponent(sieCurrentId())+'/'+id,{method:'DELETE'});await sieFetchFiles();render();toast('Document supprimé du stockage local.');sieQueueSave()}
 catch(e){alert(e.message)}
}

// Conserver la charte de la maquette et signaler clairement ce qui est réel.
demoBar=function(){return `<div class="banner"><strong>ⓘ</strong><div><b>Application locale : enregistrement et fichiers réels.</b> Les dossiers <b>DEMO-001 à DEMO-003</b>, leurs montants et leurs devis sont fictifs. Créez une vraie consultation pour travailler. Les décisions, prix et validations restent sous la responsabilité de SIE. Le repérage documentaire ne remplace pas une lecture du DCE.</div></div>`};

const sieOldAffaires=affaires;
affaires=function(){
 const c=dceCase();
 const form=`<section class="card sectiongap"><div class="card-head"><div><h3>Créer une consultation réelle</h3><small>Chaque consultation possède son espace et ses fichiers propres</small></div><span class="badge blue">Nouvelle affaire</span></div><div class="card-body"><form id="sie-create-case" onsubmit="event.preventDefault();sieCreateCase()"><div class="grid two"><label>Référence unique<input class="field" name="id" maxlength="90" placeholder="Ex. MX25-132" required></label><label>Acheteur / client<input class="field" name="client" placeholder="Ex. École polytechnique" required></label><label>Intitulé du marché<input class="field" name="name" placeholder="Rénovation de l'aile 3" required></label><label>Date limite de remise<input class="field" name="deadline" type="date"></label></div><div class="actions" style="margin-top:16px"><button type="submit" class="btn primary">＋ Créer le dossier de travail</button></div></form></div></section>`;
 const detail=c?`<section class="card sectiongap"><div class="card-head"><h3>Informations de la consultation sélectionnée</h3><span class="badge gray">${esc(c.id)}</span></div><div class="card-body"><div class="grid two"><label>Intitulé du marché<input class="field" value="${esc(c.name)}" onchange="sieEditCase('name',this.value)"></label><label>Acheteur<input class="field" value="${esc(c.client)}" onchange="sieEditCase('client',this.value)"></label><label>Date limite (JJ/MM/AAAA)<input class="field" value="${esc(c.deadline||'')}" onchange="sieEditCase('deadline',this.value)"></label><label>Lot / activité (libellé libre)<input class="field" value="${esc(c.lot||'')}" onchange="sieEditCase('lot',this.value)"></label></div></div></section>`:'';
 return sieOldAffaires()+form+detail;
};
function sieCreateCase(){
 const form=document.getElementById('sie-create-case');const data=new FormData(form);
 const id=String(data.get('id')||'').trim(),name=String(data.get('name')||'').trim(),client=String(data.get('client')||'').trim(),rawDate=String(data.get('deadline')||'');
 if(!/^[A-Za-z0-9][\w.-]{0,95}$/.test(id)){alert('Référence invalide : lettres, chiffres, tirets et points uniquement.');return}
 if([...cases,...state.newCases].some(c=>c.id===id)){alert('Cette référence existe déjà.');return}
 if(!name||!client){alert('Saisissez un nom de marché et un acheteur.');return}
 const deadline=rawDate?rawDate.split('-').reverse().join('/'):'';
 sieSaveContext();state.newCases.push({id,name,client,deadline,lot:'À déterminer',amount:0,progress:0,status:'Nouveau dossier'});
 state.selected=cases.length+state.newCases.length-1;
 state.docs=initialDocs.map(d=>({...d,received:false,validated:false,required:'À vérifier',origin:'À vérifier dans le RC'}));
 state.lines=[];state.quotes=[];state.validations={tech:false,finance:false,admin:false};
 sieOffers=[];sieSelected={};sieAlerts=[];sieSaveContext();
 state.view='dce';render();sieQueueSave();toast('Consultation '+id+' créée et enregistrée.');
}
function sieEditCase(field,value){const c=dceCase();if(!c)return;c[field]=value;sieQueueSave();toast('Modification enregistrée')}
createCase=function(){go('affaires');document.querySelector('#sie-create-case input[name="id"]')?.focus();toast('Renseignez la référence et les informations du marché.')};

const sieOldDce=dce;
dce=function(){
 let html=sieOldDce();
 html=html.replaceAll('Inventaire de la sélection conservé dans cette session de démonstration','Fichiers DCE réellement stockés sur votre ordinateur')
  .replaceAll('La sélection a été enregistrée dans la maquette','Les fichiers ont été enregistrés sur le serveur local')
  .replace('Les fichiers originaux ne sont pas envoyés à un serveur et ne sont pas conservés dans ce fichier HTML.','Les fichiers sont conservés dans le dossier local data/files et accessibles dans la liste ci-dessous.')
  .replace('Cette maquette permet de sélectionner et d’inventorier des fichiers de plusieurs gigaoctets sans charger leur contenu en mémoire. Le transfert réel, le stockage sécurisé, la reprise après interruption, la vérification d’intégrité et le suivi d’avancement nécessitent un serveur et un service d’import par blocs. Aucun transfert réel n’est simulé comme accompli.','Le serveur local stocke réellement les fichiers. Les gros fichiers sont envoyés par blocs de 8 Mo. Les données restent sur cet ordinateur ; une instance sur réseau nécessitera une authentification et des sauvegardes.')
  .replace('Aucun envoi au serveur.','Stockage sur le serveur local après confirmation.');
 const total=sieFiles().filter(f=>f.category==='dce').length;
 html+=`<section class="card sectiongap"><div class="card-head"><h3>Fichiers DCE enregistrés</h3><span class="badge green">${total} fichier(s) sur le disque</span></div><div class="card-body">${sieFileRows('dce')}</div></section>`;
 return html;
};
dceChoose=function(files){
 if(!files?.length)return;
 siePendingFiles=Array.from(files);
 state.dcePending=siePendingFiles.map(f=>({path:f.webkitRelativePath||f.name,size:f.size,type:f.type||'inconnu'}));
 render();toast(siePendingFiles.length+' fichier(s) sélectionné(s). Confirmez pour les sauvegarder.');
};
async function sieUpload(file,category='dce',docType='',relative=''){
 const consultation=sieCurrentId();
 const path=relative||file.webkitRelativePath||file.name;
 if(file.size<=8*1024*1024){
  const form=new FormData();form.append('file',file,file.name);form.append('category',category);form.append('relpath',path);form.append('document_type',docType);
  return (await sieJson('/api/files/'+encodeURIComponent(consultation)+'/upload',{method:'POST',body:form})).file;
 }
 const size=8*1024*1024,total=Math.ceil(file.size/size);
 const id=(self.crypto?.randomUUID?.()||'').replaceAll('-','')||Array.from({length:32},()=>Math.floor(Math.random()*16).toString(16)).join('');
 let result=null;
 for(let i=0;i<total;i++){
  const params=new URLSearchParams({upload_id:id,filename:file.name,relpath:path,category,document_type:docType,index:String(i),total:String(total)});
  const req=await sieJson('/api/files/'+encodeURIComponent(consultation)+'/chunk?'+params,{method:'POST',body:file.slice(i*size,Math.min((i+1)*size,file.size))});
  result=req.file||result;
  const t=document.getElementById('sie-upload-progress');if(t)t.textContent=`${file.name} — ${Math.round((i+1)/total*100)} %`;
 }
 return result;
}
dceConfirm=async function(){
 if(!siePendingFiles.length){toast('Aucun fichier sélectionné.');return}
 if(sieUploadBusy)return;sieUploadBusy=true;state.dceBusy=true;
 const files=[...siePendingFiles],consultation=sieCurrentId();let complete=0,failed=[];
 try{
  const status=document.createElement('div');status.id='sie-upload-progress';status.className='callout';status.textContent='Import en cours…';document.getElementById('app')?.prepend(status);
  for(const file of files){
   try{await sieUpload(file,'dce');complete++;
     status.textContent=`Import ${complete}/${files.length} : ${file.name}`;
   }catch(e){failed.push(file.name+' : '+e.message)}
  }
  await sieFetchFiles(consultation);
  const list=sieFileCache[consultation].filter(f=>f.category==='dce');
  state.dceImports[consultation]={consultation,count:list.length,bytes:list.reduce((a,f)=>a+f.size,0),date:sieDate(),files:list.map(f=>({path:f.relpath,size:f.size})),status:'Stocké sur disque local'};
  state.dcePending=[];siePendingFiles=[];sieQueueSave();
  if(failed.length)alert(`${complete} fichier(s) importé(s), ${failed.length} erreur(s) :\n`+failed.join('\n'));
  else toast(complete+' fichier(s) réellement importé(s).');
 }finally{sieUploadBusy=false;state.dceBusy=false;render()}
};

// Parseur Excel local via Python, sans CDN ni transfert à un cloud.
metresFile=async function(input){
 const file=input.files?.[0];if(!file)return;
 if(!/\.(xlsx|xlsm|csv)$/i.test(file.name)){alert('Importer un .xlsx, .xlsm ou .csv. Convertissez les fichiers .xls anciens.');return}
 try{
  const form=new FormData();form.append('file',file,file.name);
  const parsed=await sieJson('/api/spreadsheet/parse',{method:'POST',body:form});
  metresPending={caseId:metresCase().id,fileName:file.name,size:file.size,sheets:parsed.sheets,active:0,headers:0,columns:{designation:0,unite:1,quantite:2,reference:3},lot:'',status:'Prévisualisation depuis le serveur local'};
  render();toast('Tableur ouvert : vérifiez les colonnes et confirmez les métrés.');
 }catch(e){alert('Erreur de lecture Excel : '+e.message)}
};
const sieOldMetres=metres;
metres=function(){
 let html=sieOldMetres();
 html=html.replace('Formats acceptés : .xlsx, .xls, .csv','Formats acceptés : .xlsx, .xlsm, .csv').replace('accept=".xlsx,.xls,.csv"','accept=".xlsx,.xlsm,.csv"');
 html=html.replace('Lecture dans le navigateur, sans envoi vers un serveur. Les fichiers Excel nécessitent le chargement de la bibliothèque de lecture ; en mode hors ligne, utilisez un CSV.','Lecture locale sur le serveur : .xlsx, .xlsm et CSV pris en charge sans connexion Internet.')
  .replace('Maquette : données conservées uniquement pendant cette session du navigateur. Pas de stockage permanent ni de liaison automatique à la DPGF.','Import conservé dans la base locale. Utilisez le bouton ci-dessous pour copier volontairement les quantités vérifiées dans la DPGF.');
 const items=metresStore[sieCurrentId()]||[];
 if(items.length)html+=`<section class="card sectiongap"><div class="card-head"><h3>Transmettre les métrés validés à la DPGF</h3></div><div class="card-body">${items.map((x,i)=>`<div class="dce-file"><span>${esc(x.fileName)} · ${x.rows.length} lignes</span><button class="btn primary" onclick="sieApplyMetres(${i})">Appliquer à la DPGF</button></div>`).join('')}</div></section>`;
 return html;
};
function sieApplyMetres(i){
 const entry=(metresStore[sieCurrentId()]||[])[i];if(!entry)return;
 if(!confirm('Utiliser les quantités de ce fichier dans la DPGF de travail ? Les codes identiques verront leur quantité remplacée. Les prix existants sont conservés.'))return;
 let added=0,updated=0,skipped=0;
 for(const r of entry.rows){
  const code=String(r.reference||'').trim()||'IMP-'+String(i+1)+'-'+String(r.ligne);
  const qty=Number(String(r.quantite||'').replace(/\s/g,'').replace(',','.'));
  if(!Number.isFinite(qty)||qty<0||!String(r.designation||'').trim()){skipped++;continue}
  const exist=state.lines.find(l=>l.id===code);
  if(exist){exist.qty=qty;if(r.unite)exist.unit=r.unite;updated++}
  else{state.lines.push({id:code,name:r.designation,unit:r.unite||'U',qty,price:null});added++}
 }
 sieQueueSave();render();toast(`${added} nouveaux postes, ${updated} quantités actualisées, ${skipped} lignes ignorées.`);
}

// Joindre réellement les fichiers de réponse et garder la validation humaine.
const sieOldDocuments=documents;
documents=function(){
 let html=sieOldDocuments();
 const options=state.docs.map(d=>`<option value="${esc(d.id)}">${esc(d.name)}</option>`).join('');
 const files=sieFiles().filter(f=>f.category!=='dce');
 html+=`<section class="card sectiongap"><div class="card-head"><h3>Fichiers réels de la candidature et de l’offre</h3><span class="badge blue">${files.length} fichier(s) enregistrés</span></div><div class="card-body"><p>Associez une pièce à une exigence de la checklist. L’import indique sa présence, mais <b>ne la valide pas automatiquement</b>.</p><div class="grid two"><label>Pièce associée<select id="sie-doc-type" class="field" style="width:100%"><option value="">Pièce libre / autre</option>${options}</select></label><label>Catégorie<select id="sie-doc-category" class="field" style="width:100%"><option value="reponse">Pièce de réponse</option><option value="devis">Devis fournisseur</option><option value="memoire">Mémoire technique</option><option value="metres">Métrés</option><option value="autre">Autre annexe</option></select></label></div><p style="margin-top:15px"><input type="file" id="sie-doc-uploads" multiple class="field" style="max-width:100%"></p><button class="btn primary" onclick="sieUploadResponse()">⇧ Enregistrer ces pièces sur le disque</button><div style="margin-top:16px">${sieFileRows(null).replaceAll('Aucun fichier enregistré dans cette catégorie','Aucun fichier enregistré pour cette consultation')}</div></div></section>`;
 return html;
};
async function sieUploadResponse(){
 const input=document.getElementById('sie-doc-uploads'),docs=[...(input?.files||[])];if(!docs.length){alert('Sélectionnez au moins un fichier.');return}
 const docId=document.getElementById('sie-doc-type').value, category=document.getElementById('sie-doc-category').value;
 try{
  for(const f of docs)await sieUpload(f,category,docId);
  if(docId){const d=state.docs.find(d=>d.id===docId);if(d){d.received=true;d.validated=false}}
  await sieFetchFiles();sieQueueSave();render();toast(docs.length+' pièce(s) conservée(s) sur le disque local.');
 }catch(e){alert('Erreur pendant la copie : '+e.message)}
}

// Extraction PDF côté serveur local, même si pdf-lib/pdf.js ne sont pas installés.
sieCctpLoad=async function(input){
 const f=input.files?.[0];if(!f)return;
 if(!/\.pdf$/i.test(f.name)){alert('Sélectionnez un PDF.');return}
 try{const form=new FormData();form.append('file',f,f.name);
  const info=await sieJson('/api/pdf/info',{method:'POST',body:form});
  sieCctpFile=f;sieCctpName=f.name;sieCctpPages=info.pages;sieCctpBuffer=await f.arrayBuffer();render();toast(`CCTP ouvert : ${info.pages} page(s).`);
 }catch(e){alert('PDF non lisible : '+e.message)}
};
sieExtractPdf=async function(i){
 const r=sieRequests[i];if(!r||!r.ranges?.length){alert('Aucune plage de pages enregistrée.');return}
 if(!sieCctpFile||r.cctp!==sieCctpName){alert('Rechargez le CCTP associé à cette demande.');return}
 try{const form=new FormData();form.append('file',sieCctpFile,sieCctpName);form.append('ranges',JSON.stringify(r.ranges));
  const result=await sieApi('/api/pdf/extract',{method:'POST',body:form});const blob=await result.blob();const url=URL.createObjectURL(blob);
  const a=document.createElement('a');a.href=url;a.download=`SIE_CCTP_extraits_${sieCurrentId()}.pdf`;a.click();setTimeout(()=>URL.revokeObjectURL(url),12000);toast('Extraits PDF créés localement.');
 }catch(e){alert('Extraction PDF : '+e.message)}
};
const sieOldOfferAdd=sieOfferAdd;
sieOfferAdd=function(){
 const f=document.getElementById('sie-off-file')?.files[0];const caseId=sieCurrentId();
 const before=sieOffers.length;sieOldOfferAdd();
 if(sieOffers.length>before&&f){
  const current=sieOffers[sieOffers.length-1];current.file=null;
  sieUpload(f,'devis').then(res=>{current.fileId=res.id;return sieFetchFiles(caseId)}).then(()=>{render();sieQueueSave()}).catch(e=>alert('Devis enregistré dans la liste, mais fichier non sauvegardé : '+e.message));
 }
};
sieOfferExport=function(){
 sieQueueSave();siePersist().then(()=>{location.href='/api/export/'+encodeURIComponent(sieCurrentId())+'/dpgf.xlsx'});
};

// Registre de repérage documentaire avec sources et contrôle humain.
const sieOldAnalyse=analyse;
analyse=function(){
 let html=(/^DEMO-/.test(sieCurrentId())?sieOldAnalyse():shell('Analyse du DCE','Repérage des exigences et contrôle des points de vigilance à partir des pièces réellement importées.')+demoBar()+sieAlertPanel());const findings=sieFindings[sieCurrentId()]||[];
 html+=`<section class="card sectiongap"><div class="card-head"><div><h3>Repérer les exigences dans les fichiers du DCE</h3><small>Recherche locale de passages et expressions clés, avec document et page</small></div><button class="btn primary" onclick="sieScanDce()">⌕ Lancer le repérage documentaire</button></div><div class="card-body"><p class="small">Cette fonction repère des passages potentiellement pertinents. Elle ne garantit pas l’exhaustivité, ne réalise pas d’OCR et ne remplace pas la vérification du RC, du CCTP et du CCAP.</p><div id="sie-findings">${findings.length?`<p><b>${findings.length} passage(s) à vérifier</b></p>`+findings.map((f,i)=>`<div style="padding:13px 0;border-bottom:1px solid #dde4eb"><span class="badge amber">${esc(f.category)}</span> <small>${esc(f.source)}${f.page?' · page '+f.page:''}</small><div style="white-space:pre-wrap;margin:7px 0">${esc(f.excerpt)}</div><button class="btn sm" onclick="sieAddFinding(${i})">＋ Ajouter aux vigilances</button></div>`).join(''): '<p>Aucun résultat disponible. Importez un DCE puis lancez le repérage.</p>'}</div></div></section>`;
 return html;
};
async function sieScanDce(){
 const caseId=sieCurrentId();const area=document.getElementById('sie-findings');if(area)area.textContent='Lecture des documents en cours sur le serveur local…';
 try{const data=await sieJson('/api/analyse/'+encodeURIComponent(caseId),{method:'POST'});
  sieFindings[caseId]=data.findings;
  render();toast(`${data.documents_scanned} document(s) parcouru(s), ${data.findings.length} extrait(s) repéré(s).`);
 }catch(e){alert('Analyse impossible : '+e.message);render()}
}
function sieAddFinding(i){
 const f=(sieFindings[sieCurrentId()]||[])[i];if(!f)return;
 if(sieAlerts.some(a=>a.source===f.source&&a.page===String(f.page||'')&&a.title===f.excerpt.slice(0,100))){toast('Ce passage figure déjà au registre.');return}
 const id=Math.max(0,...sieAlerts.map(x=>Number(x.id)||0))+1;
 sieAlerts.push({id,category:f.category,title:f.excerpt.slice(0,100),source:f.source,page:f.page?String(f.page):'',action:'Relire le passage source, déterminer l’obligation et la réponse SIE.',destination:'Mémoire technique',status:'À vérifier',note:f.excerpt,memo:true});
 sieQueueSave();render();toast('Extrait ajouté au registre de vigilance.');
}

const sieOldFinal=final;
final=function(){
 let html=sieOldFinal();
 const n=sieFiles().length, required=state.docs.filter(d=>d.required==='Obligatoire'&&!d.validated);
 html+=`<section class="card sectiongap"><div class="card-head"><h3>Export réel du dossier de travail</h3><span class="badge amber">À valider avant dépôt</span></div><div class="card-body"><p><b>${n} fichier(s)</b> stockés pour cette consultation. L’archive inclut les pièces importées, la fiche, les contrôles, les métrés, les mémoires brouillons et une DPGF Excel provisoire reprenant le modèle SIE.</p><p class="small">${required.length?`${required.length} élément(s) obligatoires non validé(s). L’export est autorisé pour permettre la relecture, mais le dossier n’est pas déclaré prêt au dépôt.`:'Contrôlez toutes les exigences du RC et faites valider le dossier par les responsables autorisés.'}</p><button class="btn primary" onclick="sieExportZip()">↓ Télécharger le dossier ZIP complet</button> <button class="btn" onclick="sieDownloadExcel()">↓ DPGF Excel provisoire</button></div></section>`;
 return html;
};
async function sieDownloadExcel(){await siePersist();location.href='/api/export/'+encodeURIComponent(sieCurrentId())+'/dpgf.xlsx'}
async function sieExportZip(){try{await siePersist();location.href='/api/export/'+encodeURIComponent(sieCurrentId())+'/dossier.zip';toast('Export du dossier de travail demandé au serveur local.')}catch(e){alert(e.message)}}

// Ajouter un statut clair, un sélecteur de consultation sûr et un indicateur de persistance.
const sieRenderPreIntegration=render;
render=function(){
 sieRenderPreIntegration();
 const el=document.getElementById('app');if(!el)return;
 const header=document.createElement('div');header.style.cssText='display:flex;justify-content:flex-end;align-items:center;margin-bottom:10px;gap:8px';
 header.innerHTML=`<span id="sie-storage-status" class="small" style="font-size:12px">${esc(sieStorageStatus)}</span><button class="btn sm" onclick="siePersist()" title="Enregistrer immédiatement">Enregistrer</button>`;
 el.prepend(header);
};

// Certaines listes de sélection du HTML historique remplaçaient l’index sans charger le contexte.
document.addEventListener('change',e=>{
 const t=e.target;if(t?.id==='dce-case'||(t?.tagName==='SELECT'&&t?.outerHTML.includes('state.selected=Number(this.value)'))){
  e.stopImmediatePropagation();const idx=Number(t.value);state.dcePending=[];metresPending=null;siePendingFiles=[];sieSelectCase(idx);sieFetchFiles().then(render);sieQueueSave();
 }
},true);
document.addEventListener('click',()=>{sieQueueSave()},true);
document.addEventListener('input',()=>{sieQueueSave()},true);
document.addEventListener('change',()=>{sieQueueSave()},false);
window.addEventListener('beforeunload',()=>{if(sieReady&&!sieSaving){const payload=JSON.stringify(sieSnapshot());navigator.sendBeacon?.('/api/state/beacon',new Blob([payload],{type:'application/json'}));}});

(async function sieStartup(){
 try{
  const saved=await sieJson('/api/state');
  if(saved.data){sieApplySnapshot(saved.data);sieStorageStatus='Données restaurées depuis le serveur local';}
  else sieStorageStatus='Nouvel espace de travail local';
  await sieFetchFiles();
 }catch(e){sieStorageStatus='Serveur indisponible : '+e.message;console.error(e)}
 finally{sieReady=true;render();}
})();

// Recharger également l’inventaire réel lors d’un changement de consultation.
const sieOriginalCaseSelectLive=sieSelectCase;
sieSelectCase=function(index){
 sieOriginalCaseSelectLive(index);
 const active=sieCurrentId();sieFetchFiles(active).then(()=>{if(sieCurrentId()===active)render()});
 sieQueueSave();
};

// Recherche lexicale locale sur les documents historiques enregistrés, sans IA externe.
let sieArchiveResults=[];
const sieMemoOriginalLocal=memoire;
memoire=function(){
 let html=sieMemoOriginalLocal();
 html+=`<section class="card sectiongap"><div class="card-head"><div><h3>Recherche dans les mémoires archivés</h3><small>Recherche textuelle locale dans les PDF et Word importés dans la catégorie « Mémoire technique »</small></div></div><div class="card-body"><p>Les documents restent sur ce serveur local. Les passages retrouvés sont accompagnés de leur source ; ils doivent être <b>adaptés et vérifiés</b> avant d’être réutilisés.</p><div style="display:flex;gap:9px;flex-wrap:wrap"><input id="sie-archive-query" class="field" style="flex:1;min-width:200px" placeholder="Ex. phasage chantier en site occupé"><button class="btn primary" onclick="sieSearchArchives()">⌕ Chercher des passages</button></div><div id="sie-archive-results" style="margin-top:14px">${sieArchiveMarkup()}</div><p class="small">Pour ajouter des archives, ouvrez l’onglet Documents et importez des fichiers PDF ou DOCX dans la catégorie « Mémoire technique ». Cette recherche textuelle n’est pas une génération IA ni un RAG vectoriel.</p></div></section>`;
 return html;
};
function sieArchiveMarkup(){
 if(!sieArchiveResults.length)return '<p class="small">Aucun résultat. Importez des mémoires ou modifiez votre recherche.</p>';
 return sieArchiveResults.map((r,i)=>`<div style="padding:12px 0;border-bottom:1px solid #e1e7ef"><b>${esc(r.filename)}</b> <small>• ${esc(r.consultation)} ${r.page?'• page '+r.page:''}</small><p style="white-space:pre-wrap">${esc(r.excerpt)}</p><button class="btn sm" onclick="sieReuseArchive(${i})">＋ Insérer comme extrait à vérifier</button></div>`).join('');
}
async function sieSearchArchives(){
 const q=document.getElementById('sie-archive-query')?.value.trim();if(!q||q.length<3){alert('Saisissez au moins trois caractères.');return}
 const output=document.getElementById('sie-archive-results');if(output)output.textContent='Recherche locale en cours…';
 try{const response=await sieJson('/api/history/search?q='+encodeURIComponent(q));sieArchiveResults=response.results;output.innerHTML=sieArchiveMarkup();toast(response.results.length+' extrait(s) retrouvé(s).')}
 catch(e){if(output)output.textContent='Erreur : '+e.message}
}
function sieReuseArchive(i){
 const r=sieArchiveResults[i];if(!r)return;
 const config=sieMemoConfig();if(!config.mode){alert('Choisissez d’abord le type de mémoire technique avant d’insérer un extrait.');return}
 const {lot}=sieMemoCurrent(),memo=sieMemoGet(lot),section='methodologie';
 memo.sections[section]=(memo.sections[section]||'')+'\n\n[EXTRAIT HISTORIQUE À ADAPTER ET À VALIDER — '+r.filename+(r.page?', p. '+r.page:'')+']\n'+r.excerpt;
 sieQueueSave();render();toast('Extrait de travail ajouté à « Méthodologie » avec sa source.');
}

// Remplacer les anciens libellés fictifs là où une vraie consultation est affichée.
const sieDashboardOriginal=dashboard;
dashboard=function(){return sieDashboardOriginal()
 .replaceAll('Nouvelle affaire démo','Nouvelle consultation')
 .replace('Affaires dans la démo','Consultations enregistrées')
 .replace('Échéances de la simulation','Consultations suivies')
 .replace('Simulation sur quatre demandes','Suivi sur le dossier actif')
 .replace('Dates de simulation','Dates issues des dossiers');};
const sieAffairesActual=affaires;
affaires=function(){
 let html=sieAffairesActual();const c=dceCase();
 const decision=(state.fiches[c.id]?.decision||'En attente de décision');
 return html.replaceAll('Nouvelle affaire démo','Nouvelle consultation')
 .replace('Les affaires fictives servent à visualiser un portefeuille en cours.','Les trois consultations DEMO sont fictives. Les dossiers ajoutés sont conservés localement.')
 .replace('Simulation : GO',esc(decision))
 .replace('Montant indicatif HT','Montant indicatif HT (à confirmer)');
};
const sieDpgfActual=dpgf;
dpgf=function(){
 let html=sieDpgfActual(),c=dceCase();
 if(!/^DEMO-/.test(c.id)){
  html=html.replace('↓ Exporter le CSV démo','↓ Exporter le CSV')
   .replace('Montant estimatif fictif de l\'offre','Montant de référence (non calculé)')
   .replace('Valeur de scénario, non déduite des lignes ci-dessous','À renseigner par SIE et à distinguer des prix d’achat')
   .replace('Sous-total de l\'extrait simulé','Sous-total des lignes renseignées')
   .replace('Postes du lot E01','Postes de la consultation')
   .replace('Extrait fictif de démonstration','Tableau de travail')
   .replace('Les valeurs de cet extrait servent exclusivement à tester l\'interface.','Les lignes de cette consultation sont saisies ou issues des métrés confirmés.')
   .replace('Simulation</span>','Contrôle indicatif</span>')
   .replace('<strong>'+e0(cases[0]?.amount||0)+'</strong>','<strong>'+(c.amount?e0(c.amount):'À renseigner')+'</strong>');
 }
 return html;
};
const sieDocumentsActual=documents;
documents=function(){let html=sieDocumentsActual();if(!/^DEMO-/.test(sieCurrentId()))html=html.replace('Ces états sont fictifs et modifiables pour la démonstration.','États de préparation à saisir et confirmer par les responsables SIE.');return html;};
report=function(){
 const c=dceCase();return {mode:'DOSSIER_DE_TRAVAIL_LOCAL',consultation:c.id,objet:c.name,acheteur:c.client,
  date_limite:c.deadline||'À vérifier',montant_indicatif_ht:c.amount||null,
  sous_total_postes_ht:lineTotal(),postes_sans_prix:priceMissing(),pieces:state.docs,
  validations:state.validations,devis:state.quotes,alertes:sieAlerts,
  fichiers_stockes:sieFiles().map(f=>({nom:f.relpath,categorie:f.category,taille_octets:f.size,sha256:f.sha256})),
  date_export:new Date().toISOString(),avertissement:'Rapport provisoire. Vérifier chaque obligation du DCE avant validation ou dépôt.'};
};
const sieFinalActual=final;
final=function(){let html=sieFinalActual(),c=dceCase();if(!/^DEMO-/.test(c.id)){
 html=html.replace('Préparation du dossier pilote','Préparation de la consultation '+esc(c.id))
  .replace('DEMO-001_Dossier_Offre/',esc(c.id)+'_Dossier_Offre/')
  .replace('DPGF_Lot_E01.xlsx','SIE_DPGF_PROVISOIRE.xlsx')
  .replace('Télécharger le manifeste démo','Télécharger le rapport JSON')
  .replace('Le fichier généré est un manifeste JSON, pas un vrai ZIP contractuel. Cette version n\'assemble ni ne signe les pièces originales.','Le manifeste JSON est un rapport de contrôle. Utilisez le bouton ZIP ci-dessous pour récupérer les pièces réellement importées. Aucun document n’est signé ni transmis automatiquement.')
  .replaceAll('Statut modifiable dans cette simulation','Déclaration manuelle du responsable SIE')
  .replace('Le score est uniquement une démonstration visuelle.','Le score est un indicateur visuel non contractuel.');
 }
 return html;
};

// ============================================================================
// Sprint S1 — Analyse structurée du DCE : champs sourcés, alertes suivies, pré-remplissage de la fiche.
// ============================================================================
let sieAnalyses={};
const SIE_CHAMPS=[['reference','Référence'],['objet','Objet'],['procedure','Procédure'],['date_limite','Date limite de remise'],
 ['date_limite_questions','Date limite des questions'],['visite','Visite du site'],['validite_offres','Validité des offres'],
 ['delai_execution','Délai d’exécution'],['forme_prix','Forme des prix'],['variantes','Variantes'],['acheteur','Acheteur'],
 ['contact','Contact acheteur'],['lieu','Lieu d’exécution'],['moa','Maître d’ouvrage'],['moe','Maître d’œuvre'],['architecte','Architecte'],
 ['sps','Coordonnateur SPS'],['ssi','Coordinateur SSI'],['controleur_technique','Contrôleur technique'],['opc','OPC'],['trame_memoire','Trame du mémoire']];
const SIE_STATUTS=['À vérifier','En cours','Traité','Bloquant','Sans objet'];
async function sieLoadAnalyse(id){
 try{const r=await sieJson('/api/analyse/'+encodeURIComponent(id));sieAnalyses[id]=r}
 catch(e){sieAnalyses[id]={erreur:e.message}}
}
function sieSrc(c){
 if(!c||!c.source)return '<span class="badge amber">À vérifier</span>';
 return `<span class="sourcechip" title="${esc(c.extrait||'')}">${esc(String(c.source).split('/').pop())}${c.page?' · p. '+c.page:''}</span>`;
}
function sieAnalysePanel(){
 const id=sieCurrentId(),a=sieAnalyses[id];
 const head=(btn)=>`<div class="card-head"><div><h3>Synthèse automatique du DCE</h3><small>Pièces classées par type et lues par priorité : questions-réponses, RC, CCAP, cadre de réponse, CCTP. Chaque valeur indique sa source.</small></div>${btn}</div>`;
 if(!a||a.chargement)return `<section class="card sectiongap">${head('')}<div class="card-body"><p class="small">Chargement de la dernière analyse…</p></div></section>`;
 if(!a.analyse)return `<section class="card sectiongap">${head('<button class="btn primary" onclick="sieScanDce()">⌕ Analyser le DCE</button>')}<div class="card-body"><p>Aucune analyse pour cette consultation. Importez le DCE puis lancez l’analyse.</p>${a.erreur?`<p class="small">${esc(a.erreur)}</p>`:''}</div></section>`;
 const an=a.analyse,f=an.fiche,s=an.synthese;
 const lignes=SIE_CHAMPS.map(([k,l])=>{const c=f[k]||{};let v=c.valeur;
  if(k==='visite'&&c.statut==='extrait')v=(v==='oui'?'Obligatoire':'Non obligatoire')+(c.creneaux&&c.creneaux.length?' — '+c.creneaux.join(' ; '):'')+(c.rendez_vous?' — '+c.rendez_vous:'')+(c.contacts&&c.contacts.length?' — '+c.contacts.join(', '):'');
  const hist=c.historique&&c.historique.length?`<div class="small">Remplace : ${c.historique.map(x=>esc(x.valeur)+' ('+esc(String(x.source).split('/').pop())+')').join(', ')}</div>`:'';
  return `<tr><td class="strong" style="white-space:nowrap">${l}</td><td>${c.statut==='extrait'?esc(v):'<span class="badge amber">À vérifier</span>'}${hist}</td><td>${sieSrc(c)}</td></tr>`}).join('');
 const lots=(f.lots&&f.lots.valeur||[]).map(l=>`<tr><td class="strong">${esc(l.numero)}</td><td>${l.sous_lots&&l.sous_lots.length?l.sous_lots.map(x=>esc(x.numero+' '+x.intitule)).join('<br>'):esc(l.intitule)}</td></tr>`).join('');
 const crit=(f.criteres&&f.criteres.valeur||[]).map(c=>`<li><b>${esc(c.code)}. ${esc(c.libelle)}</b> — ${c.poids} ${esc(c.unite)}${c.sous_criteres.length?'<ul>'+c.sous_criteres.map(x=>`<li>${esc(x.code)} ${esc(x.libelle)} — ${x.poids}</li>`).join('')+'</ul>':''}</li>`).join('');
 const pieces=(f.pieces_exigees&&f.pieces_exigees.valeur||[]).map(p=>`<li>${esc(p.piece)} <small>(${p.groupe})</small> ${p.eliminatoire?'<span class="badge red">Éliminatoire</span>':''}${p.obligatoire?'':' <span class="badge gray">Facultatif</span>'} ${sieSrc(p)}</li>`).join('');
 const heures=(f.heures_insertion&&f.heures_insertion.valeur||[]).map(h=>`${esc(h.element)} : <b>${h.heures} h</b>`).join(' · ');
 const alertes=(a.alertes||[]).map((x,i)=>`<div style="padding:11px 0;border-bottom:1px solid #e6ebf0"><span class="badge ${x.priorite==='haute'?'red':'amber'}">${esc(x.priorite||'')}</span> <b>${esc(x.titre)}</b> ${sieSrc(x)}<div class="small" style="margin:5px 0">${esc(x.detail||'')}</div><div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center"><select class="field" onchange="sieAlerteStatut(${x.id},this.value)">${SIE_STATUTS.map(t=>`<option${t===x.statut?' selected':''}>${t}</option>`).join('')}</select><button class="btn sm" onclick="sieAlerteVersRegistre(${i})">＋ Ajouter au registre de vigilance</button>${x.responsable?`<small>Responsable : ${esc(x.responsable)}</small>`:''}</div></div>`).join('');
 const retenus=new Set(((state.fiches[id]||{}).lots||[]).filter(l=>l.retenu).map(l=>String(l.numero).replace(/^Lot\s*/,'').replace(/^Macro-lot\s*/,'ML')));
 const qr=(an.vigilances_qr||[]).filter(v=>v.motifs.length).map(v=>{const cible=v.lots.some(l=>retenus.has(l));return `<div style="padding:8px 0;border-bottom:1px solid #eef1f4${cible?';background:#fffaf2':''}"><b>Q/R n°${v.question}</b> ${v.motifs.map(m=>`<span class="badge gray">${esc(m)}</span>`).join(' ')} ${v.lots.length?`<span class="badge ${cible?'amber':'blue'}">lots ${esc(v.lots.join(', '))}</span>`:''} ${sieSrc(v)}<div class="small">${esc(v.texte)}</div></div>`}).join('');
 const types=Object.entries(s.par_type||{}).sort((x,y)=>y[1]-x[1]).map(([t,n])=>`${esc(t)} ${n}`).join(' · ');
 return `<section class="card sectiongap">${head(`<div class="two-btns"><button class="btn" onclick="sieScanDce()">↻ Relancer l’analyse</button><button class="btn primary" onclick="siePrefillFiche()">▧ Pré-remplir la fiche de renseignement</button></div>`)}
 <div class="card-body"><div class="callout"><b>${s.documents_lus} pièces lues sur ${s.documents}</b> (plans, archives et diagnostics non lus pour la fiche) · ${s.champs_extraits.length} champs trouvés · ${s.champs_a_verifier.length} à vérifier · ${s.questions_reponses} questions-réponses · ${s.doublons} doublons détectés${a.date?` · analyse du ${esc(a.date.slice(0,16).replace('T',' '))} (UTC)`:''}<div class="small" style="margin-top:6px">${types}</div><div class="small" style="margin-top:6px">${esc(an.avertissement)}</div></div>
 <h4 class="dochead">Informations de la consultation</h4><div class="table-wrap"><table><thead><tr><th>Champ</th><th>Valeur extraite</th><th>Source</th></tr></thead><tbody>${lignes}</tbody></table></div>
 <h4 class="dochead">Lots (${(f.lots&&f.lots.valeur||[]).length}) ${sieSrc(f.lots)}</h4><div class="table-wrap"><table><tbody>${lots||'<tr><td>À vérifier</td></tr>'}</tbody></table></div>
 <div class="grid two" style="margin-top:6px"><div><h4 class="dochead">Critères de jugement ${sieSrc(f.criteres)}</h4><ul>${crit||'<li>À vérifier</li>'}</ul></div><div><h4 class="dochead">Pièces exigées par le RC</h4><ul>${pieces||'<li>À vérifier</li>'}</ul>${heures?`<p class="small"><b>Heures d’insertion :</b> ${heures}</p>`:''}</div></div>
 <h4 class="dochead">Alertes à traiter (${(a.alertes||[]).length})</h4>${alertes||'<p class="small">Aucune alerte.</p>'}
 <details style="margin-top:14px"><summary class="strong">Questions-réponses porteuses d’exigences (${(an.vigilances_qr||[]).filter(v=>v.motifs.length).length}) — surlignées si elles citent un lot coché dans la fiche</summary>${qr}</details>
 </div></section>`;
}
const sieAnalyseAvantS1=analyse;
analyse=function(){
 let html=sieAnalyseAvantS1();const id=sieCurrentId();
 if(!sieAnalyses[id]){sieAnalyses[id]={chargement:true};sieLoadAnalyse(id).then(()=>{if(state.view==='analyse'&&sieCurrentId()===id)render()})}
 const k=html.indexOf('<h3>Repérer les exigences');const at=k>0?html.lastIndexOf('<section',k):-1;
 return at>0?html.slice(0,at)+sieAnalysePanel()+html.slice(at):html+sieAnalysePanel();
};
sieScanDce=async function(){
 const caseId=sieCurrentId();const area=document.getElementById('sie-findings');if(area)area.textContent='Analyse du DCE en cours sur le serveur local…';
 toast('Analyse du DCE en cours…');
 try{const data=await sieJson('/api/analyse/'+encodeURIComponent(caseId),{method:'POST'});
  sieFindings[caseId]=data.findings;sieAnalyses[caseId]={analyse:data.analyse,fiche_interface:data.fiche_interface,alertes:data.alertes,date:new Date().toISOString()};
  render();const s=data.analyse.synthese;toast(`${s.documents_lus} pièce(s) lue(s), ${s.champs_extraits.length} champ(s) trouvé(s), ${s.alertes} alerte(s).`);
 }catch(e){alert('Analyse impossible : '+e.message);render()}
};
function siePrefillFiche(){
 const id=sieCurrentId(),a=sieAnalyses[id];if(!a||!a.fiche_interface){alert('Lancez d’abord l’analyse du DCE.');return}
 const f=ficheData(),src=a.fiche_interface,c=dceCase();let n=0;
 for(const [k,v] of Object.entries(src)){
  if(k==='lots'||k==='sources'||v===''||v==null)continue;
  const cur=f[k];const vide=cur===undefined||cur===''||cur==='verifier'||(k==='objet'&&cur===c.name)||(k==='reference'&&cur===id);
  if(vide&&cur!==v){f[k]=v;n++}
 }
 if(src.lots&&src.lots.length&&(!f.lots.length||confirm('Remplacer les '+f.lots.length+' lot(s) de la fiche par les '+src.lots.length+' lots trouvés dans le DCE ? Les cases « retenu » seront à recocher.'))){f.lots=src.lots.map(l=>({...l}));n++}
 f.sourcesAuto='Pré-remplissage automatique du '+sieDate()+' — à vérifier dans les pièces :\n'+src.sources;
 if(!f.sources)f.sources=f.sourcesAuto;
 if(!c.deadline&&src.dateLimite)c.deadline=src.dateLimite.slice(0,10);
 sieQueueSave();go('fiche');toast(n+' champ(s) pré-rempli(s) depuis le DCE. Les champs déjà saisis n’ont pas été modifiés.');
}
async function sieAlerteStatut(aid,statut){
 try{await sieApi('/api/alertes/'+encodeURIComponent(sieCurrentId())+'/'+aid,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({statut})});
  const a=sieAnalyses[sieCurrentId()];const x=a&&a.alertes&&a.alertes.find(y=>y.id===aid);if(x)x.statut=statut;toast('Statut enregistré dans le registre local.')}
 catch(e){alert(e.message)}
}
function sieAlerteVersRegistre(i){
 const a=((sieAnalyses[sieCurrentId()]||{}).alertes||[])[i];if(!a)return;
 const title=a.titre.slice(0,100);if(sieAlerts.some(x=>x.title===title&&x.source===(a.source||''))){toast('Cette alerte figure déjà au registre.');return}
 const nid=Math.max(0,...sieAlerts.map(x=>Number(x.id)||0))+1;
 sieAlerts.push({id:nid,category:a.categorie||'Administratif',title,source:a.source||'',page:a.page?String(a.page):'',action:'Vérifier dans la pièce source, puis traiter.',destination:(a.categorie==='Administratif'||a.categorie==='Complétude DCE')?'Pièces administratives':'Mémoire technique',status:'À vérifier',note:a.detail||'',memo:true});
 sieQueueSave();render();toast('Alerte ajoutée au registre de vigilance.');
}
const sieSelectAvantS1=sieSelectCase;
sieSelectCase=function(i){sieSelectAvantS1(i);const id=sieCurrentId();if(sieAnalyses[id]&&!sieAnalyses[id].analyse)delete sieAnalyses[id]};
const sieFicheAvantS1=fiche;
fiche=function(){
 return sieFicheAvantS1().replace('<b>Maquette :</b> aucun document n’est analysé automatiquement. Complétez ou corrigez les informations à partir des pièces du DCE.',
  '<b>Pré-remplissage :</b> dans « Analyse du DCE », le bouton « Pré-remplir la fiche » reprend les informations trouvées dans le DCE, avec leur source. Vérifiez et corrigez chaque champ.');
};

// ============================================================================
// Sprint S2 — DPGF de l'acheteur : saisie des quantités et PU, contrôles, génération du classeur à remettre.
// ============================================================================
let sieDpgfA={};            // par consultation : {fichiers, docId, vue, propositions, chargement}
let sieDpgfTimer=null, sieDpgfFile={};
const sieNb=(v,d=2)=>v==null||v===''?'':Number(v).toLocaleString('fr-FR',{minimumFractionDigits:d,maximumFractionDigits:d});
function sieDA(){const id=sieCurrentId();return sieDpgfA[id]||(sieDpgfA[id]={})}
async function sieDpgfCharger(docId){
 const id=sieCurrentId(),st=sieDA();st.chargement=true;
 try{
  if(!st.fichiers)st.fichiers=(await sieJson('/api/dpgf/'+encodeURIComponent(id))).fichiers;
  const cible=docId||st.docId||(st.fichiers.find(f=>f.lot==='3')||st.fichiers[0]||{}).id;
  if(cible){st.docId=cible;st.vue=await sieJson('/api/dpgf/'+encodeURIComponent(id)+'/'+cible);st.propositions=null}
 }catch(e){st.erreur=e.message}
 st.chargement=false;if(state.view==='dpgf'&&sieCurrentId()===id)render();
}
function sieDpgfSaisir(ligne,champ,valeur){
 const st=sieDA();const v=String(valeur).trim()===''?null:Number(String(valeur).replace(/\s/g,'').replace(',','.'));
 if(v!==null&&(!Number.isFinite(v)||v<0)){alert('Valeur invalide : nombre positif attendu.');return}
 sieDpgfFile[ligne]=Object.assign(sieDpgfFile[ligne]||{ligne},{[champ]:v,['origine_'+champ]:'Saisie manuelle'});
 clearTimeout(sieDpgfTimer);sieDpgfTimer=setTimeout(()=>sieDpgfEnvoyer(),700);
}
async function sieDpgfEnvoyer(items){
 const st=sieDA(),id=sieCurrentId();const lot=items||Object.values(sieDpgfFile);sieDpgfFile={};if(!lot.length||!st.docId)return;
 try{st.vue=await sieJson('/api/dpgf/'+encodeURIComponent(id)+'/'+st.docId+'/saisies',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({saisies:lot})});
  const y=window.scrollY;render();window.scrollTo(0,y);toast(lot.length+' ligne(s) enregistrée(s) dans la DPGF.')}
 catch(e){alert('Enregistrement impossible : '+e.message)}
}
function sieDpgfSources(type){
 const id=sieCurrentId();
 if(type==='metres')return (metresStore[id]||[]).flatMap(m=>(m.rows||[]).map(r=>({reference:r.reference,designation:r.designation,unite:r.unite,
  quantite:Number(String(r.quantite||'').replace(/\s/g,'').replace(',','.')),origine:'Métré : '+m.fileName+' l.'+r.ligne}))).filter(s=>s.designation&&Number.isFinite(s.quantite));
 return (state.lines||[]).map(l=>({reference:l.id,designation:l.name,unite:l.unit,quantite:l.qty,pu:l.price,origine:'Chiffrage interne : '+l.id}));
}
async function sieDpgfRapprocher(type){
 const st=sieDA(),id=sieCurrentId(),src=sieDpgfSources(type);
 if(!src.length){alert(type==='metres'?'Aucun métré importé pour cette consultation (rubrique « Décomptes & métrés »).':'Aucune ligne dans le chiffrage interne.');return}
 try{const r=await sieJson('/api/dpgf/'+encodeURIComponent(id)+'/'+st.docId+'/rapprocher',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({lignes:src})});
  st.propositions={type,liste:r.propositions.map(p=>({...p,coche:p.score>=0.95&&!p.unite_differente}))};render();
  toast(r.propositions.length+' correspondance(s) proposée(s) sur '+r.postes+' postes : vérifiez avant d’appliquer.')}
 catch(e){alert(e.message)}
}
function sieDpgfAppliquer(){
 const st=sieDA();if(!st.propositions)return;const t=st.propositions.type;
 const items=st.propositions.liste.filter(p=>p.coche).map(p=>{const s=p.source,it={ligne:p.row};
  if(t==='metres'||s.quantite!=null){it.qte=Number(s.quantite);it.origine_qte=s.origine}
  if(t==='prix'&&s.pu!=null){it.pu=Number(s.pu);it.origine_pu=s.origine}return it}).filter(it=>it.qte!=null||it.pu!=null);
 if(!items.length){alert('Aucune proposition cochée.');return}
 if(!confirm(items.length+' poste(s) vont être mis à jour dans la DPGF. Les valeurs existantes de ces postes seront remplacées. Continuer ?'))return;
 st.propositions=null;sieDpgfEnvoyer(items);
}
function sieDpgfExporter(){
 const st=sieDA(),c=st.vue&&st.vue.controles;if(!c)return;
 if(!c.pret&&!confirm(`DPGF incomplète : ${c.sans_quantite.length} poste(s) sans quantité, ${c.sans_prix.length} sans prix.\nGénérer quand même un fichier de travail ?`))return;
 location.href='/api/dpgf/'+encodeURIComponent(sieCurrentId())+'/'+st.docId+'/export';toast('Génération du classeur de l’acheteur rempli…');
}
function sieDpgfSection(){
 const st=sieDA();
 if(!st.fichiers&&!st.chargement){sieDpgfCharger();}
 const head=`<div class="card-head"><div><h3>DPGF de l’acheteur — fichier à remettre</h3><small>Classeur fourni dans le DCE : quantités et PU saisis ici, formules et totaux écrits par l’outil. Macros, logos et autres feuilles sont conservés à l’identique.</small></div>${st.fichiers&&st.fichiers.length?`<select class="field" onchange="sieDpgfCharger(this.value)">${st.fichiers.map(f=>`<option value="${f.id}"${f.id===st.docId?' selected':''}>${esc(f.lot?('Lot '+f.lot.replace('ML','macro-lot ')):'')} — ${esc(f.filename)}${f.saisies?' ('+f.saisies+' saisies)':''}</option>`).join('')}</select>`:''}</div>`;
 if(st.chargement||!st.fichiers)return `<section class="card sectiongap">${head}<div class="card-body"><p class="small">Chargement…</p></div></section>`;
 if(!st.fichiers.length)return `<section class="card sectiongap">${head}<div class="card-body"><p>Aucune DPGF (.xlsx / .xlsm) trouvée dans le DCE de cette consultation.</p>${st.erreur?`<p class="small">${esc(st.erreur)}</p>`:''}</div></section>`;
 const v=st.vue;if(!v)return `<section class="card sectiongap">${head}<div class="card-body"><p class="small">${esc(st.erreur||'Chargement…')}</p></div></section>`;
 const c=v.controles,sz=v.saisies,lignes=v.structure.lignes;
 const props=st.propositions?`<div class="callout" style="margin:12px 0"><b>${st.propositions.liste.length} correspondance(s) proposée(s)</b> — ${st.propositions.type==='metres'?'quantités issues des métrés':'prix et quantités du chiffrage interne'}. Rien n’est appliqué sans votre validation.
  <div style="max-height:300px;overflow:auto;margin-top:8px"><table><thead><tr><th></th><th>Poste DPGF</th><th>Source proposée</th><th>Valeur</th><th>Score</th></tr></thead><tbody>${st.propositions.liste.map((p,i)=>`<tr><td><input type="checkbox" class="check" ${p.coche?'checked':''} onchange="sieDA().propositions.liste[${i}].coche=this.checked"></td><td><b>${esc(p.numero)}</b> ${esc(p.designation.slice(0,70))} <small>(${esc(p.unite)})</small></td><td>${esc((p.source.designation||'').slice(0,70))}<br><small>${esc(p.source.origine||'')} · ${esc(p.mode)}</small>${p.unite_differente?' <span class="badge red">unité différente</span>':''}</td><td class="money">${p.source.quantite!=null?'Q '+sieNb(p.source.quantite,0):''}${p.source.pu!=null?'<br>PU '+sieNb(p.source.pu):''}</td><td>${Math.round(p.score*100)} %</td></tr>`).join('')}</tbody></table></div>
  <div class="two-btns" style="margin-top:8px"><button class="btn primary" onclick="sieDpgfAppliquer()">Appliquer la sélection</button><button class="btn" onclick="sieDA().propositions=null;render()">Annuler</button></div></div>`:'';
 const corps=lignes.map(l=>{const r=l.row,s=sz[r]||{};
  if(l.type==='titre')return `<tr style="background:#f7fafc"><td class="strong">${esc(l.numero)}</td><td colspan="5" class="strong" style="padding-left:${8+((l.niveau||1)-1)*14}px">${esc(l.designation)}</td></tr>`;
  if(l.type==='texte')return `<tr><td></td><td colspan="5" class="small">${esc(l.designation)}</td></tr>`;
  if(['sous_total','rappel','total'].includes(l.type))return `<tr class="totalfoot"><td></td><td colspan="4" ${l.type==='total'?'class="strong"':''}>${esc(l.designation)}</td><td class="money strong">${sieNb(c.totaux[r])} €</td></tr>`;
  const manque=l.type==='poste'&&(s.qte==null||s.pu==null);
  return `<tr${manque?' style="background:#fffaf2"':''}><td>${esc(l.numero)}</td><td>${esc(l.designation)}${l.type==='mention'?` <span class="badge gray">${esc(l.unite)}</span>`:''}${s.origine_qte&&s.origine_qte!=='Saisie manuelle'?`<br><small>Q : ${esc(s.origine_qte)}</small>`:''}${s.origine_pu&&s.origine_pu!=='Saisie manuelle'?`<br><small>PU : ${esc(s.origine_pu)}</small>`:''}</td><td>${esc(l.type==='mention'?'':l.unite)}</td>
   <td><input class="field qty" value="${s.qte??''}" onchange="sieDpgfSaisir(${r},'qte',this.value)" ${l.type==='mention'?'placeholder="—"':''}></td>
   <td><input class="field price" value="${s.pu??''}" onchange="sieDpgfSaisir(${r},'pu',this.value)" ${l.type==='mention'?'placeholder="—"':''}></td>
   <td class="money">${c.montants[r]!=null?sieNb(c.montants[r])+' €':''}</td></tr>`}).join('');
 const etat=c.pret?'<span class="badge green">Tous les postes sont chiffrés</span>':`<span class="badge amber">${c.postes-c.postes_complets} poste(s) incomplet(s)</span>`;
 return `<section class="card sectiongap">${head}<div class="card-body">
  <div class="grid3"><div class="mini"><small>Total HT calculé</small><strong>${sieNb(c.total_general)} €</strong></div><div class="mini"><small>Postes chiffrés</small><strong>${c.postes_complets} / ${c.postes}</strong></div><div class="mini"><small>Contrôles</small><div>${etat}</div><div class="small" style="margin-top:6px">${c.sans_quantite.length} sans quantité · ${c.sans_prix.length} sans prix${c.mentions_chiffrees.length?' · '+c.mentions_chiffrees.length+' ligne(s) SO/PM chiffrée(s)':''}</div></div></div>
  <div class="two-btns" style="margin:14px 0"><button class="btn" onclick="sieDpgfRapprocher('metres')">⇄ Reprendre les quantités des métrés</button><button class="btn" onclick="sieDpgfRapprocher('prix')">⇄ Reprendre les prix du chiffrage interne</button><button class="btn primary" onclick="sieDpgfExporter()">↓ Générer la DPGF remplie (${esc((v.document.filename.split('.').pop()||'').toUpperCase())})</button></div>
  <p class="small">Feuille « ${esc(v.structure.feuille)} » · ${lignes.length} lignes lues · Prix total = Qté × PU ; sous-totaux en SOUS.TOTAL (sans double compte) ; total du lot = SOMMEPROD. Le classeur original du DCE n’est jamais modifié : un nouveau fichier est généré à chaque export. Les prix de vente restent à valider par SIE.</p>
  ${props}
  <div class="table-wrap" style="max-height:640px;overflow:auto"><table><thead><tr><th>N°</th><th>Désignation</th><th>U</th><th class="numcol">Qté</th><th class="numcol">PU HT</th><th class="numcol">Total HT</th></tr></thead><tbody>${corps}</tbody></table></div>
 </div></section>`;
}
const sieDpgfAvantS2=dpgf;
dpgf=function(){return sieDpgfAvantS2()+sieDpgfSection()};
const sieSelectAvantS2=sieSelectCase;
sieSelectCase=function(i){sieSelectAvantS2(i);delete sieDpgfA[sieCurrentId()]};

// ============================================================================
// Sprint S5 — Contrôle final : pièces exigées vs pièces déposées, visite, délai, alertes, DPGF, dérogations.
// ============================================================================
let sieControle={};
async function sieControleCharger(){
 const id=sieCurrentId();sieControle[id]={chargement:true};
 try{sieControle[id]=await sieJson('/api/controle/'+encodeURIComponent(id))}catch(e){sieControle[id]={erreur:e.message}}
 if(state.view==='final'&&sieCurrentId()===id)render();
}
async function sieDeroger(code,titre){
 const justification=prompt('Dérogation pour « '+titre+' »\n\nJustification (obligatoire, tracée au journal et jointe au dossier) :');if(!justification)return;
 const auteur=prompt('Nom et fonction de la personne qui autorise la dérogation :')||'';
 try{sieControle[sieCurrentId()]=await sieJson('/api/controle/'+encodeURIComponent(sieCurrentId())+'/derogations',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({code,justification,auteur})});render();toast('Dérogation enregistrée et tracée.')}
 catch(e){alert(e.message)}
}
async function sieAnnulerDerogation(code){
 if(!confirm('Annuler cette dérogation ? Le point redeviendra actif.'))return;
 try{sieControle[sieCurrentId()]=await sieJson('/api/controle/'+encodeURIComponent(sieCurrentId())+'/derogations?code='+encodeURIComponent(code),{method:'DELETE'});render()}catch(e){alert(e.message)}
}
function sieControleSection(){
 const id=sieCurrentId(),c=sieControle[id];
 if(!c){sieControleCharger();}
 const head=`<div class="card-head"><div><h3>Contrôle de conformité du dossier de réponse</h3><small>Pièces exigées par le RC (analyse du DCE) comparées aux pièces importées dans « Documents », visite, délai, alertes et DPGF des lots retenus.</small></div><button class="btn" onclick="sieControleCharger()">↻ Relancer le contrôle</button></div>`;
 if(!c||c.chargement)return `<section class="card sectiongap">${head}<div class="card-body"><p class="small">Contrôle en cours…</p></div></section>`;
 if(c.erreur)return `<section class="card sectiongap">${head}<div class="card-body"><p>${esc(c.erreur)}</p></div></section>`;
 const couleur={pret:'green',a_verifier:'amber',bloque:'red',vide:'gray'}[c.verdict]||'gray';
 const badge={bloquant:'red',majeur:'amber',info:'gray'};
 const lignes=c.points.map(p=>`<tr${p.niveau==='bloquant'?' style="background:#fdf3f2"':''}><td>${p.statut==='ok'?'<span class="badge green">OK</span>':`<span class="badge ${badge[p.niveau]}">${p.niveau==='bloquant'?'Bloquant':p.niveau==='majeur'?'À vérifier':'Info'}</span>`}</td>
  <td><b>${esc(p.titre)}</b><div class="small">${esc(p.detail||'')}</div>${p.preuves&&p.preuves.length?`<div class="small">↳ ${p.preuves.map(x=>esc(String(x).split('/').pop())).join(' · ')}</div>`:''}${p.derogation?`<div class="small" style="color:#956115">Dérogation : ${esc(p.derogation.justification)} — ${esc(p.derogation.auteur||'auteur non renseigné')} (${esc(String(p.derogation.created).slice(0,10))}) <a href="#" onclick="event.preventDefault();sieAnnulerDerogation('${esc(p.code)}')">annuler</a></div>`:''}</td>
  <td>${p.source&&p.source.fichier?`<span class="sourcechip">${esc(String(p.source.fichier).split('/').pop())}${p.source.page?' · p. '+p.source.page:''}</span>`:''}</td>
  <td>${p.statut!=='ok'&&!p.derogation&&p.niveau!=='info'?`<button class="btn sm" onclick="sieDeroger('${esc(p.code)}','${esc(p.titre).replace(/'/g,'’')}')">Déroger…</button>`:''}</td></tr>`).join('');
 const k=c.compteurs;
 return `<section class="card sectiongap">${head}<div class="card-body">
  <div class="callout" style="display:flex;gap:14px;align-items:center;flex-wrap:wrap"><span class="badge ${couleur}" style="font-size:12px;padding:7px 11px">${esc(c.libelle)}</span><span class="small">${k.bloquants} bloquant(s) · ${k.a_verifier} à vérifier · ${k.ok} conforme(s) · ${k.derogations} dérogation(s) · ${c.pieces_deposees} pièce(s) déposée(s) (${sieNiceSize(c.volume_octets)})${c.lots_retenus.length?' · lots retenus : '+esc(c.lots_retenus.join(', ')):''}</span></div>
  <div class="table-wrap" style="margin-top:12px"><table><thead><tr><th>État</th><th>Point de contrôle</th><th>Source DCE</th><th></th></tr></thead><tbody>${lignes}</tbody></table></div>
  <p class="small" style="margin-top:10px">${esc(c.avertissement)} Le rapport complet et les dérogations sont joints à l’archive ZIP (Suivi/controle_final.json).</p>
 </div></section>`;
}
const sieFinalAvantS5=final;
final=function(){
 const html=sieFinalAvantS5();const k=html.indexOf('<h3>Export réel du dossier de travail');const at=k>0?html.lastIndexOf('<section',k):-1;
 return at>0?html.slice(0,at)+sieControleSection()+html.slice(at):html+sieControleSection();
};
const sieSelectAvantS5=sieSelectCase;
sieSelectCase=function(i){sieSelectAvantS5(i);delete sieControle[sieCurrentId()]};
