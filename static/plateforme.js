/* SIE-Tender-AI — couche plateforme.
   Navigation par étapes, une seule consultation active, vues reconstruites sans doublons et sans données d'exemple.
   S'appuie sur les composants réels (analyse S1, DPGF S2, contrôle S5, rédaction IA S6) et sur les vues historiques
   encore utiles (DCE, fiche, métrés, demandes de prix, paramètres), nettoyées de leurs bandeaux de maquette. */
'use strict';

// ---------------------------------------------------------------------------------------------- données d'exemple
const PF_DEMO=/^DEMO-/;
const PF_DEMO_LIGNES=new Set(initialLines.map(l=>l.id+'|'+l.name));
const PF_DEMO_DEVIS=new Set(initialQuotes.map(q=>q.family+'|'+q.supplier));
initialLines.length=0; initialQuotes.length=0;          // une nouvelle consultation démarre vide
demoBar=()=>'';
addLine=function(){state.lines.push({id:'P.'+(state.lines.length+1),name:'Nouveau poste',unit:'U',qty:null,price:null});render()};
// Sans aucune consultation, les fonctions historiques ne doivent pas planter (dceCase() vide).
const pfDceCaseOrig=dceCase;dceCase=function(){return pfDceCaseOrig()||{id:'',name:'',client:'',lot:'',deadline:'',amount:0}};
const pfFetchOrig=sieFetchFiles;sieFetchFiles=function(c=sieCurrentId()){return c?pfFetchOrig(c):Promise.resolve()};
const pfSaveCtxOrig=sieSaveContext;sieSaveContext=function(){if((cases.length+state.newCases.length)&&pfToutes()[state.selected])pfSaveCtxOrig()};
let pfPurge=false;
// Si l'état n'a pas pu être lu au démarrage (serveur arrêté), on n'écrit RIEN : sinon un état vierge écraserait le vrai.
const pfLectureKO=()=>/^Serveur indisponible/.test(sieStorageStatus);
const pfPersistOrig=siePersist;
siePersist=async function(){if(pfLectureKO()){sieDirty=false;return}return pfPersistOrig()};
function pfPurger(){
 pfPurge=true;const actif=(pfToutes()[state.selected]||{}).id;let n=0;
 for(const arr of [cases,state.newCases])for(let i=arr.length-1;i>=0;i--)if(PF_DEMO.test(arr[i].id)){
  const id=arr[i].id;arr.splice(i,1);n++;
  for(const store of [sieContexts,state.fiches,metresStore,state.dceImports,sieMemoSettings,sieMemoActiveLot])if(store)delete store[id];
 }
 for(const k of Object.keys(sieMemoStore))if(PF_DEMO.test(k))delete sieMemoStore[k];
 const exemple=v=>v&&v.lines&&v.lines.length&&v.lines.every(l=>PF_DEMO_LIGNES.has(l.id+'|'+l.name));
 for(const v of Object.values(sieContexts)){if(exemple(v))v.lines=[];if(v&&v.quotes&&v.quotes.every(q=>PF_DEMO_DEVIS.has(q.family+'|'+q.supplier)))v.quotes=[]}
 if(exemple({lines:state.lines})){state.lines=[];n++}
 if(state.quotes.length&&state.quotes.every(q=>PF_DEMO_DEVIS.has(q.family+'|'+q.supplier))){state.quotes=[];n++}
 const idx=pfToutes().findIndex(c=>c.id===actif);state.selected=idx>=0?idx:0;
 if(n){const c=pfCas();if(c&&idx<0)sieLoadContext(c.id);sieQueueSave()}
}

// ---------------------------------------------------------------------------------------------- outils
const pfToutes=()=>[...cases,...state.newCases];
const pfCas=()=>pfToutes()[state.selected]||null;
const PF_ETAPES=[['dce','Pièces du DCE'],['analyse','Analyse du DCE'],['fiche','Fiche & GO / NO GO'],['metres','Métrés'],
 ['fournisseurs','Prix fournisseurs'],['dpgf','Chiffrage & DPGF'],['memoire','Mémoire technique'],['final','Dossier & dépôt']];
const PF_TITRES={dashboard:'Tableau de bord',affaires:'Consultations',parametres:'Paramètres',...Object.fromEntries(PF_ETAPES)};
let pfOnglets={dpgf:'acheteur',memoire:'redaction'};
let pfResume={};                     // par consultation : fichiers, alertes, dpgf, contrôle (tableau de bord)

function pfDate(v){
 if(!v)return null;let m=String(v).match(/^(\d{4})-(\d{2})-(\d{2})/);if(m)return new Date(+m[1],m[2]-1,+m[3]);
 m=String(v).match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})/);return m?new Date(+m[3],m[2]-1,+m[1]):null;
}
function pfEcheance(c){
 const d=pfDate(c.deadline||(state.fiches[c.id]||{}).dateLimite);if(!d)return {txt:'À renseigner',j:null};
 const j=Math.ceil((d-new Date(new Date().toDateString()))/864e5);
 return {txt:d.toLocaleDateString('fr-FR'),j};
}
function pfBadgeJ(j){
 if(j==null)return '<span class="badge gray">Date ?</span>';
 if(j<0)return '<span class="badge gray">Remise passée</span>';
 return `<span class="badge ${j<=3?'red':j<=10?'amber':'blue'}">J-${j}</span>`;
}
const pfDecision=id=>(state.fiches[id]||{}).decision||'';

// État de chaque étape : 'fait', 'encours' ou 'afaire'. Sources : caches réels de la session puis résumé serveur.
function pfEtats(id){
 const r=pfResume[id]||{},actif=pfCas()&&pfCas().id===id;
 const fichiers=(actif&&sieFileCache[id])||r.fichiers||[];
 const nb=cat=>fichiers.filter(f=>cat.includes(f.category)).length;
 const an=(sieAnalyses[id]&&sieAnalyses[id].analyse)?sieAnalyses[id]:r.analyse;
 const ouvertes=an&&an.alertes?an.alertes.filter(a=>!['Traité','Sans objet'].includes(a.statut)).length:0;
 const fiche=state.fiches[id]||{};
 const ctx=actif?{lines:state.lines,offers:sieOffers}:(sieContexts[id]||{});
 const dpgf=(sieDpgfA[id]&&sieDpgfA[id].fichiers)||r.dpgf||[];
 const ctl=(sieControle[id]&&sieControle[id].verdict)?sieControle[id]:r.controle;
 const memos=Object.entries(sieMemoStore).filter(([k])=>k.startsWith(id+'::')).map(([,m])=>m);
 const rediges=memos.reduce((s,m)=>s+Object.values(m.sections||{}).filter(t=>String(t).trim()).length,0);
 return {
  dce:nb(['dce'])?'fait':'afaire',
  analyse:an&&an.analyse?(ouvertes?'encours':'fait'):'afaire',
  fiche:fiche.decision?'fait':(Object.values(fiche).some(v=>typeof v==='string'&&v.trim()&&v!=='verifier'&&v!==id)?'encours':'afaire'),
  metres:(metresStore[id]||[]).length?'fait':'afaire',
  fournisseurs:(ctx.offers||[]).length?'fait':'afaire',
  dpgf:dpgf.some(d=>d.saisies)||(sieDpgfA[id]&&sieDpgfA[id].vue&&sieDpgfA[id].vue.controles.pret)?((sieDpgfA[id]&&sieDpgfA[id].vue&&sieDpgfA[id].vue.controles.pret)?'fait':'encours'):((ctx.lines||[]).some(l=>l.price!=null)?'encours':'afaire'),
  memoire:memos.some(m=>m.status==='Validé par SIE')?'fait':(rediges?'encours':'afaire'),
  final:ctl&&ctl.verdict==='pret'?'fait':(nb(['reponse','memoire','autre'])?'encours':'afaire'),
  _ouvertes:ouvertes,_verdict:ctl&&ctl.verdict,_libelle:ctl&&ctl.libelle,_fichiers:fichiers.length
 };
}
const PF_PICTO={fait:'●',encours:'◐',afaire:'○'};
function pfProchaine(id){const e=pfEtats(id);if(pfDecision(id)==='NO GO')return null;return PF_ETAPES.find(([k])=>e[k]!=='fait')||null}

async function pfChargerResume(id){
 const g=u=>sieJson(u).catch(()=>null);const e=encodeURIComponent(id);
 const [f,a,d,c]=await Promise.all([g('/api/files/'+e),g('/api/analyse/'+e),g('/api/dpgf/'+e),g('/api/controle/'+e)]);
 pfResume[id]={fichiers:(f&&f.files)||[],analyse:a&&a.analyse?a:null,dpgf:(d&&d.fichiers)||[],controle:c&&c.verdict?c:null,charge:true};
}
let pfResumeEnCours=false;
function pfRafraichirResume(){
 if(pfResumeEnCours)return;pfResumeEnCours=true;
 Promise.all(pfToutes().map(c=>pfChargerResume(c.id))).finally(()=>{pfResumeEnCours=false;if(['dashboard','affaires'].includes(state.view))pfAfficher()});
}

function pfOuvrir(i,vue){sieSelectCase(Number(i));const id=sieCurrentId();go(vue||((pfProchaine(id)||['dce'])[0]))}
function pfChoisir(i){sieSelectCase(Number(i))}
function pfOnglet(vue,o){pfOnglets[vue]=o;render()}
function pfTabs(vue,liste){return `<div class="pf-tabs">${liste.map(([k,l])=>`<button class="${pfOnglets[vue]===k?'on':''}" onclick="pfOnglet('${vue}','${k}')">${l}</button>`).join('')}</div>`}
function pfTete(titre,desc,actions=''){return `<div class="pf-head"><div><h1>${titre}</h1>${desc?`<p>${desc}</p>`:''}</div>${actions?`<div class="actions">${actions}</div>`:''}</div>`}

// ---------------------------------------------------------------------------------------------- barre de consultation
function pfBarre(){
 const c=pfCas();if(!c)return '';const e=pfEtats(c.id),ech=pfEcheance(c),dec=pfDecision(c.id);
 return `<section class="pf-bar"><div class="pf-bar-top">
  <select class="field pf-select" onchange="pfChoisir(this.value)" aria-label="Consultation active">${pfToutes().map((x,i)=>`<option value="${i}" ${i===state.selected?'selected':''}>${esc(x.id)} — ${esc(x.name||'')}</option>`).join('')}</select>
  <div class="pf-meta"><span>${esc(c.client||'Acheteur à renseigner')}</span><span>Remise : <b>${esc(ech.txt)}</b> ${pfBadgeJ(ech.j)}</span>${dec?`<span class="badge ${dec==='GO'?'green':'red'}">${esc(dec)}</span>`:''}</div></div>
  <div class="pf-steps">${PF_ETAPES.map(([k,l],i)=>`<button class="pf-step ${e[k]} ${state.view===k?'on':''}" onclick="go('${k}')" title="${esc(l)}"><i>${e[k]==='fait'?'✓':i+1}</i><span>${esc(l)}</span></button>`).join('')}</div></section>`;
}

// ---------------------------------------------------------------------------------------------- navigation latérale
renderNav=function(){
 const nav=document.getElementById('nav');if(!nav)return;const c=pfCas(),e=c?pfEtats(c.id):{};
 const b=(v,ic,l,extra='')=>`<button class="${state.view===v?'active':''}" onclick="go('${v}')"><span class="ico">${ic}</span><span style="flex:1">${l}</span>${extra}</button>`;
 nav.innerHTML=b('dashboard','▦','Tableau de bord')+b('affaires','▤','Consultations',`<span class="pf-count">${pfToutes().length}</span>`)
  +(c?`<div class="navtitle pf-navcase" title="${esc(c.name||'')}">${esc(c.id)}</div>`+PF_ETAPES.map(([k,l],i)=>b(k,String(i+1),l,`<span class="pf-dot ${e[k]}">${PF_PICTO[e[k]]}</span>`)).join(''):'')
  +`<div class="navtitle">Administration</div>`+b('parametres','⚙','Paramètres');
 const crumb=document.getElementById('crumb');if(crumb)crumb.textContent=(PF_TITRES[state.view]||'')+(c&&!['dashboard','affaires','parametres'].includes(state.view)?' · '+c.id:'');
};
function pfStatut(){
 const pill=document.querySelector('.top-right .pill');if(pill){pill.textContent=/Échec|indisponible/.test(sieStorageStatus)?'● Non enregistré':'● Enregistré';pill.title=sieStorageStatus;pill.classList.toggle('pf-err',/Échec|indisponible/.test(sieStorageStatus))}
 const foot=document.querySelector('.side-foot');if(foot)foot.innerHTML=`<span class="user-dot"></span> Serveur SIE<br/>${pfToutes().length} consultation(s)<br/>Rédaction IA : ${sieIA.statut?(sieIA.statut.configure?'active':'non configurée'):'…'}`;
 const t=document.querySelector('.side .navtitle');if(t)t.textContent='PILOTAGE';
}
const pfBadgeOrig=sieStorageBadge;sieStorageBadge=function(){pfBadgeOrig();pfStatut()};

// ---------------------------------------------------------------------------------------------- tableau de bord
function pfDashboard(){
 const all=pfToutes();
 if(!all.length)return pfTete('Bienvenue','Préparez vos réponses aux appels d’offres de la réception du DCE jusqu’au dépôt.')+pfAccueil();
 if(all.some(c=>!pfResume[c.id]))pfRafraichirResume();
 const lignes=all.map((c,i)=>({c,i,e:pfEtats(c.id),ech:pfEcheance(c),dec:pfDecision(c.id)}));
 const actives=lignes.filter(x=>x.dec!=='NO GO'&&(x.ech.j==null||x.ech.j>=0));
 const urgentes=actives.filter(x=>x.ech.j!=null&&x.ech.j<=7).length;
 const alertes=actives.reduce((s,x)=>s+x.e._ouvertes,0);
 const prets=actives.filter(x=>x.e._verdict==='pret').length;
 actives.sort((a,b)=>(a.ech.j??999)-(b.ech.j??999));
 const avance=e=>PF_ETAPES.filter(([k])=>e[k]==='fait').length;
 const table=`<div class="table-wrap"><table><thead><tr><th>Consultation</th><th>Remise</th><th>Avancement</th><th></th></tr></thead><tbody>${[...actives,...lignes.filter(x=>!actives.includes(x))].map(x=>{
  const p=pfProchaine(x.c.id);return `<tr class="clickrow" onclick="pfOuvrir(${x.i})"><td><b class="linklike">${esc(x.c.id)}</b> ${x.dec?`<span class="badge ${x.dec==='GO'?'green':'red'}">${esc(x.dec)}</span>`:''}<div class="small">${esc(x.c.name||'')}</div><div class="small">${esc(x.c.client||'')}</div></td>
  <td class="mono">${esc(x.ech.txt)}<div>${pfBadgeJ(x.ech.j)}</div></td>
  <td><div class="pf-mini">${PF_ETAPES.map(([k,l])=>`<i class="${x.e[k]}" title="${esc(l)}"></i>`).join('')}</div><div class="small">${avance(x.e)}/8 étapes${x.e._ouvertes?` · <b style="color:var(--amber)">${x.e._ouvertes} alerte(s)</b>`:''}</div></td>
  <td>${p?`<button class="btn sm" onclick="event.stopPropagation();pfOuvrir(${x.i},'${p[0]}')">${esc(p[1])} →</button>`:'<span class="small">—</span>'}</td></tr>`}).join('')}</tbody></table></div>`;
 return pfTete('Tableau de bord','Vos consultations, leurs échéances et la prochaine étape de chacune.',`<button class="btn primary" onclick="go('affaires')">＋ Nouvelle consultation</button>`)
 +`<div class="stats"><div class="stat"><span class="stat-icon">▤</span><p>Consultations en cours</p><strong>${actives.length}</strong><span class="note">${all.length} au total</span></div>
 <div class="stat"><span class="stat-icon">◷</span><p>Remises sous 7 jours</p><strong>${urgentes}</strong><span class="note">Hors NO GO</span></div>
 <div class="stat"><span class="stat-icon">⚠</span><p>Alertes DCE à traiter</p><strong>${alertes}</strong><span class="note">Issues de l’analyse des DCE</span></div>
 <div class="stat"><span class="stat-icon">✓</span><p>Dossiers conformes</p><strong>${prets}</strong><span class="note">Contrôle final sans réserve</span></div></div>
 <section class="card sectiongap"><div class="card-head"><div><h3>Consultations</h3><small>Triées par date de remise. Cliquez pour ouvrir à la prochaine étape.</small></div></div>${table}</section>`;
}
function pfAccueil(){
 return `<section class="card"><div class="card-body pf-empty"><h3>Commencez par créer une consultation</h3><p>Une consultation par appel d’offres. Elle regroupe le DCE, l’analyse, la décision GO / NO GO, le chiffrage, le mémoire technique et le dossier de réponse.</p>
 <ol class="pf-ol">${PF_ETAPES.map(([,l])=>`<li>${esc(l)}</li>`).join('')}</ol><button class="btn primary" onclick="go('affaires')">＋ Créer une consultation</button></div></section>`;
}
function pfAucuneConsultation(){return pfTete(PF_TITRES[state.view]||'','')+pfAccueil()}

// ---------------------------------------------------------------------------------------------- consultations
function pfAffaires(){
 const all=pfToutes(),c=pfCas();
 if(all.some(x=>!pfResume[x.id]))pfRafraichirResume();
 const form=`<section class="card"><div class="card-head"><div><h3>Nouvelle consultation</h3><small>La référence de l’acheteur sert d’identifiant (lettres, chiffres, points, tirets).</small></div></div><div class="card-body"><form id="sie-create-case" onsubmit="event.preventDefault();sieCreateCase()">
  <div class="grid two"><label>Référence<input class="field" name="id" required placeholder="ex. MX25-132"></label><label>Date limite de remise<input class="field" type="date" name="deadline"></label>
  <label>Intitulé du marché<input class="field" name="name" required></label><label>Acheteur<input class="field" name="client" required></label></div>
  <button class="btn primary" style="margin-top:12px">Créer et importer le DCE →</button></form></div></section>`;
 const liste=all.length?`<section class="card sectiongap"><div class="card-head"><h3>Toutes les consultations (${all.length})</h3></div><div class="table-wrap"><table><thead><tr><th>Consultation</th><th>Remise</th><th>Décision</th><th>Étapes</th></tr></thead><tbody>${all.map((x,i)=>{const e=pfEtats(x.id),ech=pfEcheance(x),d=pfDecision(x.id);
  return `<tr class="clickrow${i===state.selected?' pf-sel':''}" onclick="pfOuvrir(${i})"><td><b class="linklike">${esc(x.id)}</b><div class="small">${esc(x.name||'')} · ${esc(x.client||'')}</div></td><td class="mono">${esc(ech.txt)} ${pfBadgeJ(ech.j)}</td><td>${d?`<span class="badge ${d==='GO'?'green':'red'}">${esc(d)}</span>`:'<span class="small">En attente</span>'}</td><td><div class="pf-mini">${PF_ETAPES.map(([k,l])=>`<i class="${e[k]}" title="${esc(l)}"></i>`).join('')}</div></td></tr>`}).join('')}</tbody></table></div></section>`:'';
 const detail=c?`<section class="card sectiongap"><div class="card-head"><h3>Informations de ${esc(c.id)}</h3><button class="btn sm" onclick="go('dce')">Ouvrir le dossier →</button></div><div class="card-body"><div class="grid two">
  <label>Intitulé<input class="field" value="${esc(c.name||'')}" onchange="sieEditCase('name',this.value);render()"></label><label>Acheteur<input class="field" value="${esc(c.client||'')}" onchange="sieEditCase('client',this.value);render()"></label>
  <label>Date limite de remise<input class="field" type="date" value="${esc((pfDate(c.deadline)||'')&&pfDate(c.deadline).toLocaleDateString('sv-SE'))}" onchange="sieEditCase('deadline',this.value);render()"></label>
  <label>Montant estimé HT (facultatif)<input class="field" type="number" min="0" value="${c.amount||''}" onchange="sieEditCase('amount',Number(this.value)||0)"></label></div></div></section>`:'';
 return pfTete('Consultations','Une consultation par appel d’offres : pièces, analyse, chiffrage, mémoire et dossier de réponse sont rangés à part.')+(all.length?liste+detail+'<div class="sectiongap"></div>'+form:form);
}


// ---------------------------------------------------------------------------------------------- pièces du DCE
function pfDce(){
 const id=sieCurrentId(),fichiers=sieFiles().filter(f=>f.category==='dce'),pend=state.dcePending||[];
 const an=sieAnalyses[id]&&sieAnalyses[id].analyse;
 if(!sieAnalyses[id]&&fichiers.length){sieAnalyses[id]={chargement:true};sieLoadAnalyse(id).then(()=>{if(state.view==='dce'&&sieCurrentId()===id)render()})}
 const types={};((an&&an.inventaire)||[]).forEach(x=>types[x.relpath]=x);
 const groupes={};
 for(const f of fichiers){const t=types[f.relpath];const g=t?t.type_libelle:(f.relpath.includes('/')?f.relpath.split('/').slice(-2,-1)[0]:'Racine');(groupes[g]=groupes[g]||[]).push({f,t})}
 const ordre=Object.entries(groupes).sort((a,b)=>b[1].length-a[1].length);
 const total=fichiers.reduce((s,f)=>s+f.size,0);
 const liste=ordre.map(([g,arr])=>`<details class="pf-section"><summary>${esc(g)} <span class="badge gray">${arr.length}</span></summary>${arr.map(({f,t})=>`<div class="dce-file" style="gap:10px;margin:3px 12px"><span style="flex:1;min-width:0;overflow-wrap:anywhere">${esc(f.relpath.split('/').pop())}${t&&t.lot?` <span class="badge blue">Lot ${esc(t.lot)}</span>`:''}<br><small>${sieNiceSize(f.size)}${t&&t.lu?' · lu par l’analyse':''}</small></span><a class="btn sm" href="/api/files/${encodeURIComponent(id)}/${f.id}/download">Ouvrir</a><button class="btn sm" title="Supprimer" onclick="sieDeleteFile(${f.id})">✕</button></div>`).join('')}</details>`).join('');
 return pfTete('Pièces du DCE','Importez le dossier de consultation tel que reçu (dossier complet, sous-dossiers compris). Les fichiers restent sur le serveur SIE.',fichiers.length?`<button class="btn primary" onclick="go('analyse')">Analyser le DCE →</button>`:'')
 +`<section class="card"><div class="card-head"><div><h3>Importer</h3><small>Formats lus par l’analyse : PDF, Word, Excel. Les plans et archives sont conservés sans être lus.</small></div></div><div class="card-body">
  <div class="pf-inline"><label class="btn primary" style="cursor:pointer">⇧ Choisir un dossier complet<input type="file" webkitdirectory multiple style="display:none" onchange="dceChoose(this.files)"></label><label class="btn" style="cursor:pointer">⇧ Choisir des fichiers<input type="file" multiple style="display:none" onchange="dceChoose(this.files)"></label></div>
  ${pend.length?`<div class="callout" style="margin-top:12px"><b>${pend.length} fichier(s) sélectionné(s)</b> · ${sieNiceSize(pend.reduce((s,f)=>s+f.size,0))}<div class="two-btns" style="margin-top:8px"><button class="btn primary" ${state.dceBusy?'disabled':''} onclick="dceConfirm()">${state.dceBusy?'Import en cours…':'Importer sur le serveur'}</button><button class="btn" onclick="state.dcePending=[];siePendingFiles=[];render()">Annuler</button></div></div>`:''}
 </div></section>
 <section class="card sectiongap"><div class="card-head"><div><h3>DCE de la consultation</h3><small>${fichiers.length} fichier(s) · ${sieNiceSize(total)}${an?' · classés par type de pièce':' · lancez l’analyse pour classer les pièces'}</small></div></div><div class="card-body">${liste||'<p class="small">Aucune pièce importée.</p>'}</div></section>`;
}

// ---------------------------------------------------------------------------------------------- analyse du DCE
function pfAnalyse(){
 const id=sieCurrentId();
 if(!sieAnalyses[id]){sieAnalyses[id]={chargement:true};sieLoadAnalyse(id).then(()=>{if(state.view==='analyse'&&sieCurrentId()===id)render()})}
 const nbDce=sieFiles().filter(f=>f.category==='dce').length;
 return pfTete('Analyse du DCE','Lecture des pièces du DCE par priorité (Q/R, RC, CCAP, cadre de réponse, CCTP) : informations clés avec leur source, critères, pièces exigées et alertes à traiter.')
  +(nbDce?'':`<div class="callout">Aucune pièce du DCE importée pour cette consultation. <button class="btn sm" onclick="go('dce')">Importer le DCE →</button></div>`)
  +sieAnalysePanel();
}

// ---------------------------------------------------------------------------------------------- chiffrage & DPGF
function pfChiffrageInterne(){
 const sum=lineTotal(),p=priceMissing();
 return `<section class="card"><div class="card-head"><div><h3>Chiffrage interne</h3><small>Postes de travail : quantités issues des métrés, prix issus des devis retenus ou saisis. Sert de source pour remplir la DPGF de l’acheteur.</small></div><div class="two-btns"><button class="btn sm" onclick="downloadCSV()">↓ CSV</button><button class="btn sm" onclick="sieDownloadExcel()">↓ Excel (modèle SIE)</button><button class="btn sm primary" onclick="addLine()">＋ Poste</button></div></div>
 <div class="card-body"><div class="grid3"><div class="mini"><small>Sous-total des postes chiffrés</small><strong id="subtotal">${e0(sum)}</strong></div><div class="mini"><small>Postes sans prix</small><strong id="nbmissing">${p}</strong></div><div class="mini"><small>Postes</small><strong>${state.lines.length}</strong></div></div></div>
 ${state.lines.length?`<div class="table-wrap"><table><thead><tr><th>Code</th><th>Désignation</th><th>U</th><th>Qté</th><th>PU HT (€)</th><th style="text-align:right">Total HT</th><th>État</th></tr></thead><tbody>${state.lines.map((x,i)=>`<tr><td>${esc(x.id)}</td><td><input class="field" style="width:100%;min-width:180px" value="${esc(x.name)}" onchange="state.lines[${i}].name=this.value"></td><td>${esc(x.unit)}</td><td><input class="field qty" type="number" min="0" step="any" value="${x.qty??''}" oninput="editLine(${i},'qty',this.value)"></td><td><input class="field price" type="number" min="0" step="any" placeholder="À compléter" value="${x.price??''}" oninput="editLine(${i},'price',this.value)"></td><td class="money" id="rowtotal-${i}">${x.price==null||x.qty==null?'—':euro(x.qty*x.price)}</td><td id="rowstatus-${i}"><span class="badge ${x.price==null||x.qty==null?'amber':'green'}">${x.price==null||x.qty==null?'À compléter':'Renseigné'}</span></td></tr>`).join('')}</tbody><tfoot><tr class="totalfoot"><td colspan="5">Sous-total</td><td class="money" id="sumfoot">${euro(sum)}</td><td></td></tr></tfoot></table></div>`
 :`<div class="card-body"><p class="small">Aucun poste. Importez les métrés (étape 4) puis transférez-les ici, ou ajoutez des postes manuellement.</p></div>`}
 <div class="card-body" id="pricealerts">${state.lines.length?alertsHTML():''}</div></section>`;
}
function pfDpgf(){
 return pfTete('Chiffrage & DPGF','Le chiffrage interne alimente la DPGF de l’acheteur, seul fichier de prix remis avec l’offre.')
  +pfTabs('dpgf',[['acheteur','DPGF de l’acheteur (à remettre)'],['interne','Chiffrage interne']])
  +(pfOnglets.dpgf==='interne'?pfChiffrageInterne():sieDpgfSection().replace('class="card sectiongap"','class="card"'));
}

// ---------------------------------------------------------------------------------------------- mémoire technique
const PF_ARCHIVES='ARCHIVES-SIE';
let pfArchives=null;
async function pfChargerArchives(){try{pfArchives=(await sieJson('/api/files/'+PF_ARCHIVES)).files.filter(f=>f.category==='memoire')}catch(e){pfArchives=[]}if(state.view==='memoire')render()}
async function pfEnvoyerVers(consultation,file,category){
 const path=file.webkitRelativePath||file.name;
 if(file.size<=8*1024*1024){const form=new FormData();form.append('file',file,file.name);form.append('category',category);form.append('relpath',path);
  return (await sieJson('/api/files/'+encodeURIComponent(consultation)+'/upload',{method:'POST',body:form})).file}
 const size=8*1024*1024,total=Math.ceil(file.size/size),id=Array.from({length:32},()=>Math.floor(Math.random()*16).toString(16)).join('');let res=null;
 for(let i=0;i<total;i++){const q=new URLSearchParams({upload_id:id,filename:file.name,relpath:path,category,document_type:'',index:String(i),total:String(total)});
  res=(await sieJson('/api/files/'+encodeURIComponent(consultation)+'/chunk?'+q,{method:'POST',body:file.slice(i*size,Math.min((i+1)*size,file.size))})).file||res}
 return res;
}
async function pfImporterArchives(input){
 const files=[...(input.files||[])].filter(f=>/\.(pdf|docx|txt|md)$/i.test(f.name));if(!files.length){alert('Formats acceptés : PDF, Word (.docx), texte.');return}
 toast('Import de '+files.length+' mémoire(s)…');
 try{for(const f of files)await pfEnvoyerVers(PF_ARCHIVES,f,'memoire');toast(files.length+' mémoire(s) ajouté(s) à la bibliothèque SIE.');sieIA.statut=null}
 catch(e){alert('Import interrompu : '+e.message)}
 pfChargerArchives();
}
async function pfSupprimerArchive(id){
 if(!confirm('Retirer définitivement ce mémoire de la bibliothèque ?'))return;
 try{await sieApi('/api/files/'+PF_ARCHIVES+'/'+id,{method:'DELETE'});sieIA.statut=null;pfChargerArchives()}catch(e){alert(e.message)}
}
function pfVigilances(){
 const a=sieAnalyses[sieCurrentId()];
 return ((a&&a.alertes)||[]).filter(x=>!['Administratif','Complétude DCE'].includes(x.categorie));
}
function pfSyncVigilances(){   // l'impression du mémoire reprend les alertes de l'analyse
 sieAlerts=pfVigilances().map((x,i)=>({id:i+1,category:x.categorie,title:x.titre,source:x.source||'',page:x.page?String(x.page):'',action:'',destination:'Mémoire technique',status:x.statut||'À vérifier',note:x.detail||'',memo:true}));
}
function pfMemoire(){
 const id=sieCurrentId();
 if(!sieAnalyses[id]){sieAnalyses[id]={chargement:true};sieLoadAnalyse(id).then(()=>{if(state.view==='memoire')render()})}
 else pfSyncVigilances();
 const cfg=sieMemoConfig(),lots=sieMemoLots();
 if(!cfg.mode&&lots.length<=1)cfg.mode='parlot';
 const vig=pfVigilances();
 let entete=`<section class="card"><div class="card-body pf-memo-head"><div class="pf-seg"><button class="${cfg.mode==='parlot'?'on':''}" onclick="sieMemoMode('parlot')">Un mémoire par lot</button><button class="${cfg.mode==='unique'?'on':''}" onclick="sieMemoMode('unique')">Un mémoire commun</button></div>`;
 if(cfg.mode==='parlot'&&lots.length)entete+=`<label class="pf-inline">Lot <select class="field" onchange="sieMemoSelectLot(this.value)">${lots.map((l,i)=>`<option value="${i}" ${(sieMemoActiveLot[id]||0)===i?'selected':''}>${/^lot/i.test(l.numero)?'':'Lot '}${esc(l.numero)} — ${esc(l.intitule)}</option>`).join('')}</select></label>`;
 if(cfg.mode==='unique')entete+=`<div class="pf-inline">${lots.map(l=>`<label><input type="checkbox" ${cfg.selected.includes(String(l.numero))?'checked':''} onchange="sieMemoToggleLot('${esc(String(l.numero))}',this.checked)"> ${/^lot/i.test(l.numero)?'':'Lot '}${esc(l.numero)}</label>`).join(' ')}</div>`;
 entete+=`</div>${lots.length===1&&lots[0].numero==='À définir'?`<div class="card-body" style="padding-top:0"><p class="small">Cochez les lots retenus dans la <a href="#" onclick="go('fiche');return false">fiche GO / NO GO</a> pour rédiger un mémoire par lot.</p></div>`:''}</section>`;
 let corps='';
 if(!cfg.mode)corps='<p class="small">Choisissez le type de mémoire ci-dessus.</p>';
 else if(pfOnglets.memoire==='ia')corps=sieIAPanel().replace('class="card sectiongap"','class="card"');
 else if(pfOnglets.memoire==='archives'){
  if(pfArchives===null)pfChargerArchives();
  corps=`<section class="card"><div class="card-head"><div><h3>Bibliothèque des mémoires SIE</h3><small>Anciens mémoires validés : ils servent de base à l’assistant IA et à la recherche. Stockés sur le serveur SIE, jamais envoyés en entier.</small></div><label class="btn primary sm" style="cursor:pointer">＋ Ajouter des mémoires<input type="file" multiple accept=".pdf,.docx,.txt,.md" style="display:none" onchange="pfImporterArchives(this)"></label></div>
  <div class="card-body">${pfArchives===null?'<p class="small">Chargement…</p>':pfArchives.length?pfArchives.map(f=>`<div class="dce-file" style="gap:10px;margin:4px 0"><span>▤</span><span style="flex:1;min-width:0;overflow-wrap:anywhere"><b>${esc(f.relpath)}</b><br><small>${sieNiceSize(f.size)} · ajouté le ${esc(f.created.slice(0,10))}</small></span><a class="btn sm" href="/api/files/${PF_ARCHIVES}/${f.id}/download">Ouvrir</a><button class="btn sm" onclick="pfSupprimerArchive(${f.id})">Retirer</button></div>`).join(''):'<p>Aucun mémoire dans la bibliothèque. Ajoutez 2 ou 3 mémoires validés de chantiers comparables (PDF ou Word).</p>'}</div>
  <div class="card-body" style="border-top:1px solid var(--line)"><b>Rechercher un passage</b><div style="display:flex;gap:8px;margin-top:8px"><input id="sie-archive-query" class="field" style="flex:1" placeholder="ex. gestion des déchets, site occupé, SSI…" onkeydown="if(event.key==='Enter')sieSearchArchives()"><button class="btn" onclick="sieSearchArchives()">Rechercher</button></div><div id="sie-archive-results" style="margin-top:10px">${sieArchiveResults.length?sieArchiveMarkup():''}</div></div></section>`;
 }else if(pfOnglets.memoire==='vigilances'){
  corps=`<section class="card"><div class="card-head"><div><h3>Exigences à traiter dans le mémoire</h3><small>Alertes techniques de l’analyse du DCE. Chaque point doit être traité explicitement dans la rédaction.</small></div><button class="btn sm" onclick="go('analyse')">Gérer dans l’analyse →</button></div><div class="card-body">${vig.length?vig.map(x=>`<div style="padding:9px 0;border-bottom:1px solid var(--line)"><span class="badge ${x.statut==='Traité'?'green':x.priorite==='haute'?'red':'amber'}">${esc(x.statut||'À vérifier')}</span> <b>${esc(x.titre)}</b> ${sieSrc(x)}<div class="small">${esc(x.detail||'')}</div></div>`).join(''):'<p class="small">Aucune alerte technique (ou analyse du DCE non lancée).</p>'}</div></section>`;
 }else if(cfg.mode==='unique'&&!sieMemoCurrent().lots.length)corps='<p class="small">Cochez au moins un lot pour le mémoire commun.</p>';
 else{
  const {lot}=sieMemoCurrent(),m=sieMemoGet(lot),key=sieMemoKey(lot);
  const faites=sieMemoSections.filter(([k])=>String(m.sections[k]||'').trim()).length;
  corps=`<section class="card"><div class="card-head"><div><h3>${cfg.mode==='unique'?'Mémoire commun':(/^lot/i.test(lot.numero)?'':'Lot ')+esc(lot.numero)+' — '+esc(lot.intitule)}</h3><small>${faites}/${sieMemoSections.length} sections rédigées</small></div></div>
  <div class="card-body"><div class="grid3"><label>Responsable<input class="field" value="${esc(m.owner)}" oninput="sieMemoField('${esc(key)}','owner',this.value)"></label><label>Statut<select class="field" onchange="sieMemoField('${esc(key)}','status',this.value);render()">${['Brouillon','À compléter','En relecture','Validé par SIE'].map(x=>`<option ${m.status===x?'selected':''}>${x}</option>`).join('')}</select></label><label>Date de validation<input class="field" type="date" value="${esc(m.date)}" onchange="sieMemoField('${esc(key)}','date',this.value)"></label></div>
  ${sieMemoSections.map(([k,t],i)=>`<details class="pf-section" ${String(m.sections[k]||'').trim()||i===0?'open':''}><summary><span class="pf-dot ${String(m.sections[k]||'').trim()?'fait':'afaire'}">${String(m.sections[k]||'').trim()?'●':'○'}</span> ${esc(t)}</summary><textarea class="field" rows="7" oninput="sieMemoEdit('${esc(key)}','${k}',this.value)" placeholder="Réponse de SIE pour cette section. Utilisez l’assistant IA pour un premier brouillon sourcé.">${esc(m.sections[k]||'')}</textarea></details>`).join('')}</div></section>`;
 }
 return pfTete('Mémoire technique','Rédaction par section, assistant IA sourcé, bibliothèque des anciens mémoires et exigences du DCE.',`<button class="btn" onclick="sieMemoExport()">↓ Données</button><button class="btn primary" onclick="pfSyncVigilances();sieMemoPrint()">📄 PDF / Imprimer</button>`)
  +entete+pfTabs('memoire',[['redaction','Rédaction'],['ia','✦ Assistant IA'],['archives','Bibliothèque SIE'],['vigilances',`Exigences du DCE (${vig.length})`]])+corps;
}

// ---------------------------------------------------------------------------------------------- dossier de réponse & dépôt
async function pfDeposer(input){
 const files=[...(input.files||[])];if(!files.length)return;const cat=document.getElementById('pf-cat')?.value||'reponse';
 const status=document.getElementById('pf-depot-statut');let n=0,erreurs=[];
 for(const f of files){try{if(status)status.textContent=`Import ${n+1}/${files.length} : ${f.name}`;await sieUpload(f,cat);n++}catch(e){erreurs.push(f.name+' : '+e.message)}}
 await sieFetchFiles();delete sieControle[sieCurrentId()];render();
 if(erreurs.length)alert(n+' pièce(s) importée(s), '+erreurs.length+' erreur(s) :\n'+erreurs.join('\n'));else toast(n+' pièce(s) ajoutée(s) au dossier de réponse.');
}
function pfDossier(){
 const groupes=[['reponse','Pièces de candidature et d’offre'],['memoire','Mémoire technique final'],['autre','Autres annexes']];
 const fichiers=sieFiles();
 const listes=groupes.map(([cat,l])=>{const n=fichiers.filter(f=>f.category===cat).length;return n?`<details class="pf-section"><summary>${esc(l)} <span class="badge gray">${n}</span></summary>${sieFileRows(cat)}</details>`:''}).join('');
 const v=state.validations;
 return pfTete('Dossier de réponse & dépôt','Rassemblez les pièces à déposer, vérifiez-les contre les exigences du RC, faites valider puis exportez.',`<button class="btn primary" onclick="sieExportZip()">↓ Exporter le dossier (ZIP)</button>`)
 +`<section class="card"><div class="card-head"><div><h3>Pièces du dossier de réponse</h3><small>${fichiers.filter(f=>['reponse','memoire','autre'].includes(f.category)).length} pièce(s). Nommez les fichiers clairement (AE, DC1, DC2, attestation de visite, Kbis…) : le contrôle s’appuie sur les noms.</small></div></div>
  <div class="card-body"><div class="pf-inline" style="margin-bottom:10px"><label>Type <select id="pf-cat" class="field">${groupes.map(([k,l])=>`<option value="${k}">${l}</option>`).join('')}</select></label>
  <label class="btn primary sm" style="cursor:pointer">⇧ Ajouter des fichiers<input type="file" multiple style="display:none" onchange="pfDeposer(this)"></label>
  <label class="btn sm" style="cursor:pointer">⇧ Ajouter un dossier<input type="file" webkitdirectory multiple style="display:none" onchange="pfDeposer(this)"></label></div><div id="pf-depot-statut" class="small"></div>${listes||'<p class="small">Aucune pièce de réponse importée.</p>'}</div></section>`
 +sieControleSection()
 +`<section class="card sectiongap"><div class="card-head"><div><h3>Validations avant dépôt</h3><small>Engagement des responsables SIE, joint à l’export.</small></div></div><div class="card-body">${[['tech','Contenu technique et mémoire validés'],['finance','Chiffrage et DPGF validés'],['admin','Pièces administratives et signatures validées']].map(([k,l])=>`<label class="pf-check"><input type="checkbox" class="check" ${v[k]?'checked':''} onchange="state.validations['${k}']=this.checked;sieQueueSave();render()"> ${l}</label>`).join('')}
 <p class="small" style="margin-top:10px">Le dépôt sur la plateforme de l’acheteur reste une action humaine. L’export ZIP contient les pièces, la DPGF de travail, la fiche, le rapport de contrôle et les dérogations.</p></div></section>`;
}

// ---------------------------------------------------------------------------------------------- nettoyage des vues historiques
function pfNettoyer(app){
 app.querySelectorAll('.banner').forEach(x=>x.remove());
 const sel=app.querySelector('#sie-case-select');if(sel)sel.closest('section')?.remove();
 app.querySelector('#sie-storage-status')?.parentElement?.remove();
 app.querySelectorAll('select').forEach(s=>{if(/state\.selected=Number|sieSelectCase/.test(s.getAttribute('onchange')||'')||s.id==='dce-case'){(s.closest('label')||s.parentElement)?.remove()}});
 app.querySelectorAll('[onclick^="sieAlerteVersRegistre"],[onclick^="ficheModelLots"]').forEach(x=>x.remove());
 app.querySelectorAll('h3').forEach(h=>{if(/^Consultation concernée/.test(h.textContent.trim()))(h.closest('section')||h.closest('.card'))?.remove()});
 const w=document.createTreeWalker(app,NodeFilter.SHOW_TEXT);const rem=[[/proviennent du tableau de démonstration/g,'proviennent du chiffrage interne'],[/Référentiels de démonstration/g,'Référentiels SIE'],[/dans cette session/g,'pour cette consultation']];
 for(let n=w.nextNode();n;n=w.nextNode())for(const [a,b] of rem)if(a.test(n.nodeValue))n.nodeValue=n.nodeValue.replace(a,b);
 app.querySelectorAll('.hero').forEach(h=>{h.classList.add('pf-head');h.querySelector('.kicker')?.remove()});
}
function pfAfficher(){render()}

const pfRenderHistorique=render;
const PF_VUES={dce:pfDce,dashboard:pfDashboard,affaires:pfAffaires,analyse:pfAnalyse,dpgf:pfDpgf,memoire:pfMemoire,final:pfDossier};
render=function(){
 if(state.view==='documents')state.view='final';
 if(state.view==='fournisseurs'&&typeof suppliers!=='function')state.view='dashboard';
 if(sieReady&&pfLectureKO()){sieSaving=true;const app=document.getElementById('app');
  if(app)app.innerHTML=pfTete('Serveur injoignable','Le serveur SIE ne répond pas. Rien n’est enregistré tant que la page n’a pas été rechargée avec le serveur lancé.')+`<div class="err">${esc(sieStorageStatus)}</div><p>Lancez <b>LANCER_MAC.command</b>, puis rechargez cette page.</p><button class="btn primary" onclick="location.reload()">Recharger</button>`;
  renderNav();return}
 if(sieReady&&!pfPurge)pfPurger();
 if(!sieIA.statut&&typeof sieIAStatut==='function'&&sieReady){sieIA.statut={configure:false,chargement:true};sieIAStatut().then(()=>pfStatut())}
 const app=document.getElementById('app');if(!app)return;
 const besoinCas=!['dashboard','affaires','parametres'].includes(state.view);
 try{
  if(besoinCas&&!pfCas())app.innerHTML=pfAucuneConsultation();
  else if(PF_VUES[state.view])app.innerHTML=(besoinCas?pfBarre():'')+PF_VUES[state.view]();
  else{
   pfRenderHistorique();pfNettoyer(app);
   if(state.view==='fournisseurs')app.insertAdjacentHTML('beforeend',sieOffersWorkspace());
   if(besoinCas)app.insertAdjacentHTML('afterbegin',pfBarre());
  }
 }catch(err){console.error('Affichage',state.view,err);app.innerHTML=pfTete('Affichage impossible','')+`<div class="err">${esc(err.message)}</div><button class="btn" onclick="go('dashboard')">Tableau de bord</button>`}
 renderNav();pfStatut();
};
const pfGoOrig=go;go=function(v){if(v==='dashboard'||v==='affaires')pfResume={};pfGoOrig(v)};
render();
