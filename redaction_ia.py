"""Rédaction assistée par IA du mémoire technique, avec RAG local et sources citées.

Ce qui reste sur le serveur de SIE
----------------------------------
* L'index de recherche (RAG) : recherche plein texte BM25 en Python, sans service externe, sur
  les anciens mémoires (catégorie « memoire ») et sur les pièces écrites du DCE de la consultation.
* Les pièces sensibles ne sont JAMAIS envoyées : prix, DPGF, devis, bilans, pièces de candidature.

Ce qui est envoyé à l'API (autorisation écrite de SIE pour les écrits)
----------------------------------------------------------------------
* Le libellé du sous-critère à traiter, les consignes du rédacteur et une dizaine d'extraits courts
  (quelques centaines de caractères chacun), numérotés [S1], [S2]...

Garde-fous
----------
* Le modèle doit citer ses sources après chaque phrase factuelle et écrire « [À COMPLÉTER : …] »
  au lieu d'inventer (effectifs, références, certifications, délais, marques, chiffres).
* Après génération, l'outil vérifie : sources citées existantes, paragraphes sans source,
  chiffres absents de toutes les sources. Tout est signalé pour relecture humaine.
* Le texte produit est un BROUILLON : il n'est inséré dans le mémoire que sur action de l'utilisateur.
"""
from __future__ import annotations

import math
import os
import re
import unicodedata
from collections import Counter
from pathlib import Path

import analyse_dce

MODELE_PAR_DEFAUT = 'gpt-6.1-terra'
TYPES_DCE_UTILES = {'CRT', 'CCTP', 'CCTC', 'RC', 'QR', 'CCAP'}

STOP = set('''a au aux avec ce ces dans de des du elle en et eux il ils je la le les leur lui ma mais me meme mes moi mon ne nos
notre nous on ou par pas pour qu que qui sa se ses son sur ta te tes toi ton tu un une vos votre vous c d j l m n s t y
ete etre est sont sera seront etait ont avoir fait faire cette cet comme plus moins tout tous toute toutes ainsi afin lors
selon chaque entre sans sous vers chez dont'''.split())

# --------------------------------------------------------------------------- découpage et index BM25


def _mots(texte: str) -> list[str]:
    t = ''.join(c for c in unicodedata.normalize('NFD', texte.lower()) if unicodedata.category(c) != 'Mn')
    return [m for m in re.findall(r'[a-z0-9]{3,}', t) if m not in STOP]


def decouper(pages: list[str], source: str, origine: str, taille: int = 900) -> list[dict]:
    """Extraits de ~900 caractères, coupés sur les fins de phrase, avec fichier et page."""
    extraits = []
    for num, page in enumerate(pages, 1):
        texte = analyse_dce.norm(page)
        if len(texte) < 80:
            continue
        phrases = []
        for ph in re.split(r'(?<=[.!?;:])\s+(?=[A-ZÉÈÀÂÎÔÛÇ0-9•-])', texte):
            while len(ph) > taille:   # texte sans ponctuation (tableaux, PDF mal balisés) : coupe sur un espace
                coupe = ph.rfind(' ', 0, taille)
                coupe = coupe if coupe > taille // 2 else taille
                phrases.append(ph[:coupe])
                ph = ph[coupe:].lstrip()
            phrases.append(ph)
        bloc = ''
        for ph in phrases:
            if len(bloc) + len(ph) > taille and len(bloc) > 200:
                extraits.append({'texte': bloc.strip(), 'source': source, 'page': num, 'origine': origine})
                bloc = ''
            bloc += ' ' + ph
        if len(bloc.strip()) > 80:
            extraits.append({'texte': bloc.strip(), 'source': source, 'page': num, 'origine': origine})
    return extraits


class IndexBM25:
    def __init__(self, extraits: list[dict], k1: float = 1.5, b: float = 0.75):
        self.extraits = extraits
        self.docs = [Counter(_mots(e['texte'])) for e in extraits]
        self.long = [sum(d.values()) for d in self.docs]
        self.moy = (sum(self.long) / len(self.long)) if self.long else 0
        df = Counter()
        for d in self.docs:
            df.update(d.keys())
        n = len(self.docs)
        self.idf = {m: math.log(1 + (n - f + 0.5) / (f + 0.5)) for m, f in df.items()}
        self.k1, self.b = k1, b

    def chercher(self, requete: str, k: int = 6, filtre=None) -> list[dict]:
        q = set(_mots(requete))
        scores = []
        for i, d in enumerate(self.docs):
            if filtre and not filtre(self.extraits[i]):
                continue
            s = 0.0
            for m in q:
                f = d.get(m)
                if f:
                    s += self.idf[m] * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * self.long[i] / (self.moy or 1)))
            if s > 0:
                scores.append((s, i))
        scores.sort(reverse=True)
        out, vus = [], set()
        for s, i in scores:
            e = self.extraits[i]
            cle = (e['source'], e['page'], e['texte'][:60])
            if cle in vus:
                continue
            vus.add(cle)
            out.append({**e, 'score': round(s, 2)})
            if len(out) >= k:
                break
        return out

# --------------------------------------------------------------------------- fournisseurs de modèle


class FournisseurOpenAI:
    """Appel HTTP direct à l'API OpenAI (Chat Completions). Clé lue dans l'environnement, jamais stockée."""
    nom = 'openai'

    def __init__(self, cle: str, modele: str | None = None, base_url: str | None = None, delai: float = 180):
        self.cle = cle
        self.modele = modele or MODELE_PAR_DEFAUT
        self.base_url = (base_url or 'https://api.openai.com/v1').rstrip('/')
        self.delai = delai

    def generer(self, systeme: str, utilisateur: str) -> dict:
        import httpx
        r = httpx.post(f'{self.base_url}/chat/completions', timeout=self.delai,
                       headers={'Authorization': f'Bearer {self.cle}', 'Content-Type': 'application/json'},
                       json={'model': self.modele, 'messages': [{'role': 'system', 'content': systeme},
                                                                {'role': 'user', 'content': utilisateur}]})
        if r.status_code != 200:
            try:
                msg = r.json().get('error', {}).get('message', '')
            except ValueError:
                msg = r.text[:300]
            raise RuntimeError(f'API OpenAI : erreur {r.status_code} {msg}'.strip())
        data = r.json()
        return {'texte': data['choices'][0]['message']['content'], 'modele': data.get('model', self.modele),
                'usage': data.get('usage', {})}


class FournisseurSimule:
    """Sans réseau : assemble un brouillon à partir des extraits. Sert aux tests et aux démonstrations."""
    nom = 'simule'
    modele = 'simulation-locale'

    def generer(self, systeme: str, utilisateur: str) -> dict:
        sources = re.findall(r'^\[(S\d+)\][^\n]*\n(.+)$', utilisateur, re.M)
        lignes = ['(Brouillon simulé sans IA : configurer une clé API pour une vraie rédaction.)', '']
        for sid, texte in sources[:4]:
            lignes.append(f'{texte.strip()[:220]} [{sid}]')
        lignes.append('')
        lignes.append("[À COMPLÉTER : moyens humains et matériels affectés au chantier]")
        return {'texte': '\n'.join(lignes), 'modele': self.modele, 'usage': {}}


def fournisseur_depuis_environnement():
    if os.environ.get('SIE_IA_FOURNISSEUR', '').lower() == 'simule':
        return FournisseurSimule()
    cle = os.environ.get('OPENAI_API_KEY', '').strip()
    if not cle:
        return None
    return FournisseurOpenAI(cle, os.environ.get('OPENAI_MODEL') or None, os.environ.get('OPENAI_BASE_URL') or None)

# --------------------------------------------------------------------------- consignes et contrôle du résultat


SYSTEME = """Tu es rédacteur de mémoires techniques pour SIE, entreprise d'électricité (courants forts, courants faibles, sécurité incendie) qui répond à des marchés publics de travaux.

Règles impératives :
1. Rédige en français professionnel, clair et concret, à la première personne du pluriel (« nous »), au présent ou au futur.
2. Utilise UNIQUEMENT les informations des sources fournies, numérotées [S1], [S2]… Après chaque phrase qui contient un fait, cite la ou les sources entre crochets, par exemple [S2] ou [S1][S4].
3. N'invente JAMAIS : effectifs, noms de personnes, références de chantiers, certifications, qualifications, marques et modèles de matériel, délais, chiffres, pourcentages. Si une information utile manque, écris à la place « [À COMPLÉTER : ce qu'il faut préciser] ».
4. Les sources « DCE » décrivent les exigences de l'acheteur ; les sources « Archive SIE » décrivent comment SIE a répondu par le passé. Réponds aux exigences du DCE en t'appuyant sur le savoir-faire des archives, sans recopier mot pour mot.
5. Structure la réponse avec des intertitres courts qui suivent le sous-critère. Pas d'introduction générique ni de conclusion commerciale.
6. Ne promets rien que les sources ne permettent pas d'affirmer."""


def construire_demande(critere: dict, consignes: str, lot: str | None, extraits: list[dict], longueur: int) -> str:
    lignes = [f"Consultation : marché de travaux{(' — lot ' + lot) if lot else ''}.",
              f"Sous-critère à traiter : {critere.get('code', '')} {critere.get('libelle', '')}"
              + (f" (pondération : {critere['poids']} {critere.get('unite', '')})" if critere.get('poids') else ''),
              f"Longueur visée : environ {longueur} mots."]
    if consignes:
        lignes.append(f'Consignes du rédacteur SIE : {consignes}')
    lignes.append('\nSources disponibles :')
    for i, e in enumerate(extraits, 1):
        ori = 'DCE' if e['origine'] == 'dce' else 'Archive SIE'
        lignes.append(f"[S{i}] {ori} — {Path(e['source']).name}{(' p. ' + str(e['page'])) if e.get('page') else ''}\n{e['texte']}")
    lignes.append('\nRédige maintenant la réponse à ce sous-critère en respectant toutes les règles.')
    return '\n'.join(lignes)


def verifier(texte: str, extraits: list[dict], consignes: str = '') -> dict:
    """Contrôles automatiques du brouillon. Ne corrige rien : signale pour relecture."""
    cites = sorted({int(x) for x in re.findall(r'\[S(\d+)\]', texte)})
    inconnues = [f'S{n}' for n in cites if n < 1 or n > len(extraits)]
    paragraphes = [p.strip() for p in re.split(r'\n\s*\n|\n(?=[-•*] )', texte) if p.strip()]
    sans_source = [p[:140] for p in paragraphes
                   if len(p) > 120 and not re.search(r'\[S\d+\]', p) and 'À COMPLÉTER' not in p]
    corpus = ' '.join(e['texte'] for e in extraits) + ' ' + (consignes or '')
    nombres_sources = {re.sub(r'\s', '', n).replace(',', '.') for n in re.findall(r'\d[\d\s,.]*\d|\d', corpus)}
    chiffres = []
    unite = r'(?:\s?%|\s?(?:h|heures?|jours?|mois|ans?|années?|semaines?|m²|m2|ml|kVA|kW|A|V|personnes?|compagnons?|techniciens?|flux|équipes?)\b)'
    for m in re.finditer(r'(?<![\w\[])(\d{1,3}(?:[ \u202f]\d{3})+|\d+(?:[,.]\d+)?)(' + unite + ')?', texte):
        brut = re.sub(r'[\s\u202f]', '', m.group(1)).replace(',', '.')
        if texte[max(0, m.start() - 2):m.start()].endswith('[S') or brut in nombres_sources:
            continue
        debut_ligne = texte.rfind('\n', 0, m.start()) + 1
        if re.fullmatch(r'[\s#*•-]*', texte[debut_ligne:m.start()]) and re.match(r'[.)]', texte[m.end():m.end() + 1]):
            continue   # numérotation de liste ou d'intertitre (« 1. », « 2) »)
        if len(brut) == 1 and not m.group(2):
            continue   # chiffre isolé sans unité : trop ambigu pour être signalé
        contexte = texte[max(0, m.start() - 40):m.end() + 20].replace('\n', ' ')
        chiffres.append({'valeur': m.group(0).strip(), 'contexte': contexte})
    return {'sources_citees': [f'S{n}' for n in cites], 'sources_inconnues': inconnues,
            'paragraphes_sans_source': sans_source, 'chiffres_non_sources': chiffres[:20],
            'a_completer': len(re.findall(r'À COMPLÉTER', texte))}

# --------------------------------------------------------------------------- orchestration


def preparer_extraits(documents_dce: list[dict], documents_archives: list[dict], cache_dir: Path | None,
                      lot: str | None) -> tuple[IndexBM25, dict]:
    """Construit l'index local. documents_* : lignes de la table documents (avec storepath)."""
    lecteur = analyse_dce.Lecteur(cache_dir)
    extraits, stats = [], {'dce': 0, 'archives': 0, 'pieces_dce': 0, 'pieces_archives': 0}
    for d in documents_dce:
        t = analyse_dce.classer(d['relpath'])
        if t not in TYPES_DCE_UTILES:
            continue
        if t == 'CCTP' and lot and analyse_dce.detecter_lot(d['relpath']) not in (None, lot):
            continue   # CCTP d'un autre lot : inutile et source de confusion
        if Path(d['filename']).suffix.lower() not in analyse_dce.TEXTE_LISIBLE:
            continue
        ex = decouper(lecteur.pages(d), d['relpath'], 'dce')
        extraits += ex
        stats['dce'] += len(ex)
        stats['pieces_dce'] += 1
    for d in documents_archives:
        if Path(d['filename']).suffix.lower() not in ('.pdf', '.docx', '.txt', '.md'):
            continue
        ex = decouper(lecteur.pages(d), d['relpath'], 'archive')
        extraits += ex
        stats['archives'] += len(ex)
        stats['pieces_archives'] += 1
    return IndexBM25(extraits), stats


def rediger(fournisseur, index: IndexBM25, critere: dict, consignes: str = '', lot: str | None = None,
            nb_dce: int = 5, nb_archives: int = 6, longueur: int = 450) -> dict:
    requete = f"{critere.get('libelle', '')} {consignes}"
    dce = index.chercher(requete, k=nb_dce, filtre=lambda e: e['origine'] == 'dce')
    archives = index.chercher(requete, k=nb_archives, filtre=lambda e: e['origine'] == 'archive')
    extraits = dce + archives
    for e in extraits:
        e['texte'] = e['texte'][:1100]
    demande = construire_demande(critere, consignes, lot, extraits, longueur)
    reponse = fournisseur.generer(SYSTEME, demande)
    controle = verifier(reponse['texte'], extraits, consignes)
    sources = [{'id': f'S{i}', 'origine': e['origine'], 'fichier': e['source'], 'page': e.get('page'),
                'extrait': e['texte'][:400], 'score': e.get('score')} for i, e in enumerate(extraits, 1)]
    return {'texte': reponse['texte'], 'sources': sources, 'controle': controle, 'modele': reponse['modele'],
            'fournisseur': fournisseur.nom, 'usage': reponse.get('usage', {}), 'critere': critere,
            'consignes': consignes, 'lot': lot, 'caracteres_envoyes': len(SYSTEME) + len(demande),
            'archives_disponibles': any(e['origine'] == 'archive' for e in index.extraits)}
