# État des lieux du prototype — test réel MX25-132 (26/11/2026)

Test : consultation MX25-132 créée dans l'interface, DCE réel importé (151 fichiers, 402 Mo).

| Brique | Résultat | Verdict |
|---|---|---|
| Lancement macOS (`LANCER_MAC.command`) | venv + dépendances + 5/5 tests + serveur | OK |
| Création de consultation | OK, persistée | OK |
| Import DCE (dossier complet, gros fichiers par blocs) | 151/151 fichiers, SHA-256 identiques | OK |
| Analyse / repérage (F2) | 12 documents lus sur 151, plafond de 180 extraits atteint ; 177 « Technique » issus des cartouches de plans ; RC, CCTP lot 3 et Q/R jamais lus | KO |
| Points de référence (date 12/10, visite obligatoire, qualification amiante) | 0 / 3 trouvés | KO |
| Lecture DPGF acheteur `.xlsm` | 4 feuilles, 228 lignes, < 1 s | OK (lecture brute) |
| Export ZIP du dossier | 381 Mo, OK | OK |

## Causes du KO de l'analyse
1. Ordre de lecture par nom de fichier (`03_...`, `10_...` passent avant `MX25-132 RC.pdf`) et arrêt à 180 extraits.
2. Aucune priorité par type de pièce (RC > Q/R > CCAP > CCTP du lot > plans).
3. Mots-clés trop larges (CFO, SSI, interfaces) qui déclenchent sur les cartouches de plans.
4. Pas de lecture de structure : la date limite, la visite, les lots sont des champs, pas des mots-clés.

## Constats sur la DPGF acheteur
- Structure hiérarchique (5 / 5.2 / 5.2.1), sous-totaux, lignes « SO » / « PM » / « Voir 5.16 ».
- Les quantités sont vides : en DPGF forfaitaire, c'est l'entreprise qui les porte. Le lien métrés → DPGF acheteur est donc central.
