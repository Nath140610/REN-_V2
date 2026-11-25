# René L'Intérimaire — architecture modulaire

Le comportement est le même qu'avant, mais le projet est maintenant organisé en modules.

## Lancement

Render peut garder exactement l'ancien Start Command :

```bash
python -u rene_interimaire_render_final.py
```

Ou utiliser directement :

```bash
python -u main.py
```

## Fichiers à mettre sur GitHub

Envoie les fichiers Python à la racine (`main.py`, `rene_interimaire_render_final.py`), `requirements.txt`, le dossier **entier** `rene/` (y compris `templates/` et `static/`), les images de René utilisées par le code (`CRY.png`, `READ.png`, `NEW.png`, `C'EST_NOTÉ.png`, `REFLECHIS.png`, `DELIVER.png`, `INSPECT.png`, `HAMMER.png`, `SLEEP.png`, `IDLE.png`, `GIFT.png`) et `ATTENTE.mp3`. `README.md`, les tests et `.gitignore` peuvent aussi être envoyés. Ces fichiers doivent se trouver sur la branche choisie dans Render, avec `requirements.txt` à la racine du dépôt.

Ne publie **pas** les fichiers de données `config.json`, `warnings.json`, `roblox_links.json`, `temporary_bans.json`, `moderation_cases.json`, `departed_members.json` et `questions.json`, ni un fichier `.env` ou un token. Ils peuvent contenir des données de membres ou des codes cadeau. Le `.gitignore` les exclut des commandes Git normales ; vérifie aussi ta sélection si tu utilises le bouton d'envoi de fichiers du site GitHub. René recrée les fichiers absents et recharge sa sauvegarde chiffrée depuis Discord lorsque le salon de sauvegarde est accessible.

## Panel web Render

Le même service Render héberge maintenant le bot **et** le panel à la racine de son URL `https://votre-service.onrender.com/`. Le Start Command reste `python -u rene_interimaire_render_final.py`. `/health` reste disponible pour la surveillance et `/status` renvoie le statut JSON de René.

### Démarrage immédiat sur Windows si la sortie Render est limitée

Dans PowerShell, dans le dossier du projet, lance `powershell -NoProfile -ExecutionPolicy Bypass -File .\run-local.ps1`. Le script demande en privé le `DISCORD_TOKEN` du bot René et les valeurs `STATE_SECRET` / `STATE_SECRET_PREVIOUS` actuellement configurées sur Render. Laisse la fenêtre ouverte. Pour arrêter René, appuie sur `Ctrl+C`. Aucune valeur n'est écrite dans le dépôt. Le bot doit pouvoir accéder à Discord depuis la connexion Internet du PC ; une réponse HTTP 200 sur `/gateway` ne garantit pas à elle seule que l'authentification du bot réussira.

Ce démarrage local exécute uniquement le bot Discord. Le panel hébergé sur Render ne peut pas afficher les données du processus Windows ; il restera indisponible pour les statistiques et actions Discord tant que le bot Render est déconnecté. Avant que Render ne reconnecte automatiquement son bot, arrête l'instance locale pour éviter deux instances avec le même token.

Si les logs montrent `HTTP 429` dès « Connexion de René à Discord », Discord limite la connexion sortante du service. René garde le site web actif et attend 15, puis 30, puis 60 minutes au minimum entre les tentatives (plus si Discord indique `Retry-After`). `/health` affiche `rate_limited`, l'heure de la prochaine tentative et, s'il est fourni, le `CF-Ray`. Ne redémarre pas le service en boucle : cela multiplie les tentatives. Vérifie qu'une seule instance utilise le token Discord. Si le blocage persiste, contacte le support développeur Discord avec le `CF-Ray`, l'heure UTC et les plages IP sortantes visibles dans **Render → service → Connect → Outbound**. Render partage normalement ces adresses entre services d'une région ; changer le token ou le code du bot ne débloque pas une adresse IP limitée. Une autre sortie réseau stable (par exemple un proxy HTTP(S) autorisé ou une IP dédiée Render) peut être configurée, mais elle doit être disponible séparément et ne garantit pas que Discord l'accepte. Les variables NathGPT et Supabase ne corrigent pas cette erreur.

Dans **Render → Environment**, ajoute :

| Variable | Usage |
| --- | --- |
| `DISCORD_TOKEN` | Token du bot, déjà utilisé par René. |
| `DISCORD_PROXY_URL` | Facultatif : URL d'un proxy HTTP(S) pour les connexions Discord, par exemple `http://proxy.example:8080`. Laisser vide sans proxy. |
| `DISCORD_PROXY_USER` / `DISCORD_PROXY_PASSWORD` | Facultatifs : identifiants du proxy si nécessaire. À renseigner uniquement dans Render, jamais dans GitHub. |
| `PANEL_PASSWORD` | Mot de passe fort pour accéder au panel. |
| `PANEL_SECRET` | Chaîne aléatoire d'au moins 32 caractères pour signer les sessions (par exemple `python -c "import secrets; print(secrets.token_urlsafe(48))"`). |
| `NATHGPT_API_KEY` | Ta clé `ngt_...` pour NathGPT. La variable `token` de ton exemple fonctionne aussi. Ne la mets jamais dans le code ni dans le navigateur. |
| `PANEL_GUILD_ID` | Facultatif : identifiant du seul serveur Discord affiché dans le panel. Recommandé si le bot est présent sur plusieurs serveurs. |
| `ENABLE_PRESENCE_INTENT` | Facultatif : mets `1` après avoir activé **Presence Intent** dans le portail développeur Discord. Le classement indiquera alors les dernières connexions observées. Sans cette variable, il classe la dernière activité par message ou vocal. |
| `STATE_SECRET` | Recommandé : clé stable pour la sauvegarde chiffrée dans Discord. Si tu l'ajoutes après une première sauvegarde, René sait relire l'ancienne avec `DISCORD_TOKEN`. |
| `STATE_SECRET_PREVIOUS` | Seulement pendant une rotation de clé : ancienne valeur de `STATE_SECRET`, utilisée pour lire la sauvegarde avant de la réécrire avec la nouvelle clé. |

L'URL du panel est protégée par mot de passe, cookie de session signé, jeton CSRF et limitation des tentatives de connexion. Utilise **HTTPS** (fourni par Render). Le mot de passe donne accès à tous les serveurs visibles par le bot, sauf si `PANEL_GUILD_ID` limite cet accès. Ne partage donc pas ce mot de passe. La session expire après huit heures. Pour bannir un membre, le bot doit avoir la permission **Bannir des membres** et un rôle plus haut que celui du membre. Active **Server Members Intent** et **Message Content Intent** dans le portail Discord.

Le tableau affiche les membres actuels, les arrivées, départs, messages, temps en vocal, membres actifs, graphiques et journal des actions du panel. Les compteurs d'activité commencent au premier démarrage après déploiement : aucun historique de messages n'est importé. Ils conservent les 90 derniers jours via la sauvegarde chiffrée existante de René. Le temps vocal est compté à partir des événements du bot et sauvegardé toutes les minutes. Le panel peut chercher un membre, le bannir après confirmation, générer et envoyer un code cadeau unique en MP, et consulter le registre des codes distribués. **René ne sait pas vérifier si un code a été utilisé sur Roblox**, car aucun système d'activation Roblox n'est connecté ; le registre affiche la livraison du MP.

Pour changer `STATE_SECRET` sans perdre la sauvegarde : déploie d'abord cette version du code, mets la nouvelle clé dans `STATE_SECRET` et l'ancienne dans `STATE_SECRET_PREVIOUS` uniquement sur Render. Quand le bot est reconnecté, attends les logs « État persistant rechargé depuis Discord » puis « Sauvegarde chiffrée avec le nouveau STATE_SECRET ». Retire ensuite `STATE_SECRET_PREVIOUS`. Si la sauvegarde est illisible, René refuse maintenant de l'écraser ; corrige les variables avant de poursuivre.

La section **René IA** et la commande Discord `/reneia` (réservée au staff) envoient une question et des statistiques agrégées à `https://nathgpt.onrender.com/v1/chat/completions`, avec le modèle `nathgpt`. La clé reste côté serveur. Le délai maximum de réponse est de 600 secondes. Aucun texte des messages Discord ni code cadeau n'est transmis à NathGPT.

### Nouvelles actions du panel

- **Cadeaux** : cherche le destinataire par nom dans tous les membres du serveur. Quand tu appuies sur **Envoyer**, René envoie un QR en MP au compte Discord `1362876245381091471`. Scanne le QR avec la tablette ou importe son image. Le code cadeau est créé et envoyé seulement après cette vérification. Le QR expire après cinq minutes et ne fonctionne qu'une fois. Le MP de René vers ce compte doit être autorisé.
- **Présence** : le classement indique les membres vus aujourd'hui, puis il y a 1, 2, 3 jours, etc. Il ne peut connaître les connexions Discord qu'à partir de l'activation de **Presence Intent** dans **Discord Developer Portal → Bot → Privileged Gateway Intents**, puis de `ENABLE_PRESENCE_INTENT=1` sur Render. Sans cette option, le panel affiche clairement la dernière activité observée par message ou vocal. Le bot doit rester connecté pour enregistrer la présence.
- **Rendez-vous** : choisis un membre et une date sur la tablette. René envoie une demande en MP avec les boutons de réponse existants et programme son rappel. La date doit être entre 10 minutes et 90 jours dans le futur.
- **Messages privés** : cherche un membre et écris le message. René l'envoie en MP après confirmation. Les mentions sont désactivées.
- **Cartes cadeau à gratter** : chaque code (panel ou `/sendgiftcode`) part en MP sous forme de lien unique `https://<service>/cadeau/<jeton>`. Le membre fait tourner la carte 3D, la retourne et gratte la zone argentée. Le code n'est envoyé par le serveur qu'au premier grattage ; il est ensuite valable **24 h** (décompte affiché), puis la page ne le montre plus. Le panel indique pour chaque carte : pas ouverte, ouverte (avec le nombre de visites), grattée (temps restant) ou expirée, avec **Renvoyer** (le MP précédent est supprimé). Le bouton **Remplacer** envoie une carte avec un nouveau code à chaque ancien gagnant, désactive l'ancien code et supprime l'ancien MP qui l'affichait en clair (seulement si le nouveau MP est bien livré). Render fournit l'adresse du service via `RENDER_EXTERNAL_URL` ; sinon, renseigne `PUBLIC_URL`.
- **Suivi d'un code** : dans **Cadeaux**, cherche un code, un membre ou une raison, filtre (pas ouverts, ouverts, grattés, utilisés, expirés) et touche un code pour voir sa chronologie : lien envoyé, ouvert (nombre de visites), gratté, utilisé dans Roblox (joueur, place). **Marquer utilisé** / **Annuler l'utilisation** corrigent à la main.
- **API Roblox** : dans **Réglages → Roblox**, crée une clé et copie le script Luau (`roblox/ReneGiftCodes.lua`, à mettre dans un ModuleScript de ServerScriptService ; exemple d'utilisation dans `roblox/ExempleRedeem.server.lua`). Active **Allow HTTP Requests** dans l'expérience. Mets la clé dans un secret `rene_api_key` (Creator Hub → Secrets, ou Experience Settings → Security → Local Secrets pour Studio) ou dans `FALLBACK_KEY`. Le jeu appelle `GET /api/roblox/code/<code>` (statut `inactive`, `available`, `used`, `expired`, `replaced` ou `unknown`) puis `POST /api/roblox/redeem` pour consommer le code une seule fois, même si deux serveurs essaient en même temps. En-tête obligatoire : `X-Rene-Key`. Une variable `ROBLOX_API_KEY` sur Render remplace la clé du panel.
- **Mots interdits** : dans **Sanctions**, ajoute ou retire des mots et expressions, cherche dans la liste et teste une phrase avant de l'appliquer. La liste est propre à chaque serveur et sauvegardée avec René ; tant qu'elle n'a pas été modifiée, René utilise sa liste d'origine (**Rétablir la liste par défaut** y revient). Les accents et majuscules sont ignorés.
- **Sondages** : choisis un salon, une question, 2 à 10 réponses, une durée (1 h à 7 jours) et le choix multiple. René publie un sondage Discord natif ; les membres votent dans Discord et le panel affiche les résultats en direct (mise à jour toutes les 5 secondes), avec **Terminer** pour le clôturer plus tôt. René a besoin de la permission **Créer des sondages** dans le salon.
- **Statistiques** : sur 7, 30 ou 90 jours, comparées à la période précédente : membres, arrivées, départs, solde, messages, membres actifs, vocal, record, jour le plus actif, membres les plus bavards et les plus présents en vocal, avertissements par motif, bannissements, tickets et temps de réponse, parcours des cartes cadeau (envoyées, ouvertes, grattées, utilisées dans Roblox), sondages, rendez-vous et absences. Les compteurs ne couvrent que la période suivie par René (90 jours maximum).
- **MP à tous les membres** : dans **Parler en René**, choisis tous les membres ou un rôle et écris le message. René l'envoie en arrière-plan, un MP toutes les 1,5 s pour éviter les blocages Discord, avec une barre de progression, le nombre de MP fermés et **Arrêter l'envoi**. Un seul envoi à la fois ; un redémarrage de René interrompt l'envoi en cours.
- **Assistance** : un second panel à l'adresse `/assistance`, avec son propre mot de passe (**Réglages → Assistance**, ou la variable `ASSISTANCE_PASSWORD` sur Render). L'assistant n'a accès qu'à ce formulaire. Il doit toujours choisir le membre Discord dans la liste, saisir le code, la raison, la date et l'heure du problème et sa signature. Un code absent de la base est ajouté pour ce membre et activé 24 h (Roblox le voit `available`) ; un code déjà présent, utilisé ou non, est refusé et l'assistant le voit. Toutes les demandes (activées ou refusées) apparaissent dans **Assistance** du panel principal, avec un badge pour les nouvelles. 30 demandes maximum par heure et par session d'assistant.
- **Jeux et gains** : chaque code est lié à un jeu et à un gain (catalogue dans `rene/rewards.py`).
  - **PointNemo** : 1 gamepass au hasard, une extension de radeau, un emplacement de serveur en plus.
  - **ChristmasRun** : X glings, X cadeaux, X glings et X cadeaux, 1 gamepass au hasard.
  Le gain est obligatoire pour envoyer une carte depuis le panel ou avec `/sendgiftcode` (options `gain`, `glings`, `cadeaux`). Pour les codes déjà distribués, **Cadeaux → Compléter** (ou le filtre **Sans gain**) ouvre chaque code l'un après l'autre : le gain est seulement enregistré, le membre n'est pas prévenu. L'assistance choisit aussi le gain, sans possibilité de gamepass (bloqué côté serveur). L'API Roblox renvoie `reward` (jeu, type, `glings`, `gifts`, `gamepass`) ; un code sans gain répond `no_reward` et un code d'un autre jeu `wrong_game`, et aucun des deux ne peut être utilisé. Dans le script Luau, règle `GAME = "pointnemo"` ou `"christmasrun"` selon le jeu.
- **Animations et vibrations** (`rene/static/panel-motion.js`, `motion.css`) : HELLO au démarrage, transitions entre les pages, listes qui entrent en cascade, chiffres qui comptent jusqu'à leur valeur, courbes qui se dessinent, barres qui poussent, pastille des choix qui glisse, fiches qui montent et descendent, éclat du halo aux moments forts (cadeau envoyé, sondage publié, envoi à tous, gain enregistré). Chaque action a sa vibration (sélection, interrupteur, ouverture, danger, succès, erreur, nouveau ticket ou demande d'assistance, nouveaux votes). **Réglages → Système** : activer, intensité Léger / Normal / Fort, **Tester les vibrations**. Appui long sur un membre pour ouvrir sa fiche. Les vibrations dépendent du navigateur (Chrome et Samsung Internet sur Android) ; l'option « réduire les animations » de la tablette est respectée.
- **Île dynamique** (`rene/static/island.js`, `island.css`) : une pastille noire en haut du panel. Au repos, elle montre René et son état (point vert, orange s'il se reconnecte) et une roue pendant les chargements. Elle s'étire pour les activités en cours (MP à tous avec sa progression, René IA qui réfléchit, vérification QR, reconnexion) et pour les messages, qui remplacent les anciennes notifications. Les nouveaux tickets et demandes d'assistance y apparaissent ; un toucher ouvre la page concernée. Toucher l'île au repos la déploie : état de René, activités avec leurs actions (Voir, Arrêter l'envoi) et dernières notifications.
- **Tablette à la verticale** (`rene/static/portrait.js`, `portrait.css`) : le menu latéral devient une barre d'onglets en bas (Accueil, Membres, Tickets, Cadeaux, Plus) ; **Plus** ouvre une feuille avec les autres sections et la déconnexion. Le contenu passe en pleine largeur, les cartes s'empilent et les fiches montent du bas de l'écran. Les badges suivent ceux du menu. En repassant à l'horizontale, l'interface habituelle revient sans recharger.
- **Salons de tickets** : **Tickets → Salons** liste les salons de la catégorie des tickets (ID `1368244636082245783` par défaut, modifiable dans **Réglages → Tickets**) ; chaque salon porte le nom d'un membre, retrouvé par sa permission sur le salon ou par le nom. La conversation se lit en direct (mise à jour toutes les 5 secondes, point bleu sur les tickets non lus) et René peut répondre : texte, mention du membre (lui seul est notifié), image jointe (8 Mo maximum), et embed construit dans le panel (auteur, titre, description, couleur, champs, image, miniature, pied de page, date) avec aperçu en direct. René doit pouvoir voir les salons, lire l'historique et écrire dans la catégorie. L'ancien système de questions reste dans **Tickets → Questions**.
- **Fiche membre** : dans **Membres**, touche une personne pour l'avertir (même compteur que `/warn`, ban 24 h à 10/10), modifier ses rôles, la bannir temporairement (1 h à 30 jours, levée automatique) ou définitivement, lancer un rendez-vous express, lui écrire ou lui offrir un code. Pour gérer les rôles, René a besoin de **Gérer les rôles** et d'un rôle placé au-dessus des rôles concernés.
- **Tickets** : les questions reçues dans le salon questions. Réponds **en tant que René** (MP signé René) ou clos le ticket. Le staff est prévenu sous la notification d'origine.
- **Rendez-vous** : le bouton **Pas venu** marque l'absence et annule le rappel. Les rendez-vous express lancés depuis la tablette apparaissent dans le même agenda ; les réponses arrivent en MP au compte du propriétaire.
- **Sanctions** : liste des bannissements temporaires en cours, avec **Lever**.
- **Parler en René** : publie un message dans un salon au nom de René (mentions désactivées).
- **Réglages** : choisis le statut et l'activité de René, ou reviens au mode automatique. Le bouton de redémarrage sauvegarde les données puis relance le processus du service Render. Les vibrations du panel peuvent être désactivées ; elles dépendent du navigateur et de la tablette.

Les questions à NathGPT sont limitées à 600 caractères. René résume les chiffres dans un seul message utilisateur de moins de 1 800 caractères, au format `/v1/chat/completions` indiqué dans la documentation NathGPT, pour éviter son erreur `HTTP 400 discord_payload_too_long`.

### Accès depuis une tablette Samsung

Le site affiche un message d'indisponibilité sur Windows, iPhone, iPad et les autres appareils détectés. Sur une **Samsung Galaxy Tab**, il affiche d'abord un tutoriel et un bouton **Partager**. Dans **Samsung Internet**, utilise le menu **☰ → Ajouter la page à → Écran d'accueil → Ajouter**. Dans **Chrome**, utilise **⋮ → Installer l'application** ou **Installer et créer un raccourci → Installer**. Tu peux ensuite ouvrir René depuis l'icône de l'écran d'accueil. Le tutoriel reste accessible depuis l'écran de connexion.

La détection de l'appareil repose sur les informations transmises par le navigateur. Le mode « version pour ordinateur » peut masquer le modèle ; désactive-le si ta Galaxy Tab affiche le mauvais écran. Cette détection peut être imitée et ne remplace pas le mot de passe du panel.

## Ajouter une commande

1. Crée un nouveau fichier `.py` dans `rene/commands/`.
2. Mets ta commande dedans avec une fonction `async def setup(client)`.
3. Redéploie/redémarre René.
4. `rene.loader` découvre automatiquement le fichier, le charge et synchronise la commande Discord.

**Tu ne modifies jamais `main.py`, `rene_interimaire_render_final.py` ou une liste de commandes.**

Le fichier `NOUVELLE_COMMANDE_MODELE.py.txt` est un modèle prêt à copier.

Une commande `/reloadmodules` est aussi incluse pour recharger les extensions déjà présentes et synchroniser le CommandTree. Sur Render, un nouveau fichier venant de GitHub nécessite de toute façon le nouveau déploiement pour exister sur le serveur.

## Organisation

```text
rene_modulaire/
├── main.py
├── rene_interimaire_render_final.py   # compatibilité Render
├── requirements.txt
├── NOUVELLE_COMMANDE_MODELE.py.txt
└── rene/
    ├── core.py                        # moteur/services existants
    ├── loader.py                      # détection automatique
    ├── commands/                      # 1 commande = 1 fichier
    │   ├── config.py
    │   ├── moddefinir.py
    │   ├── salonquestions.py
    │   ├── vocalattente.py
    │   ├── diagnosticvocal.py
    │   ├── anciennete.py
    │   ├── dossier.py
    │   ├── lieroblox.py
    │   ├── warn.py
    │   ├── warnings.py
    │   ├── resetwarnings.py
    │   ├── stop.py
    │   └── reloadmodules.py
    └── events/
        ├── ready.py
        ├── members.py
        ├── messages.py
        └── voice.py
```

## Assets

Les images et `ATTENTE.mp3` restent à la racine, comme avant. `core.py` cherche ses assets depuis la racine du projet.

## Architecture discord.py

Le système utilise les **extensions** natives de discord.py. Chaque module possède un point d'entrée `setup(client)` et le loader appelle automatiquement `Bot.load_extension()` sur tous les fichiers trouvés.
