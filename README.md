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

Si les logs montrent `discord.errors.HTTPException: 429` avec **Cloudflare 1015** pendant `GET /users/@me`, Discord bloque temporairement la connexion sortante du service. René garde alors le site web actif et attend 15, puis 30, puis 60 minutes entre les tentatives de connexion. Ne redémarre pas le service en boucle : cela multiplie les tentatives. Vérifie aussi qu'une seule instance utilise le token Discord. Si le blocage persiste, contacte le support Discord avec le **Ray ID** affiché dans l'erreur et l'adresse IP sortante du service Render. Les variables NathGPT et Supabase ne corrigent pas cette erreur de connexion Discord.

Dans **Render → Environment**, ajoute :

| Variable | Usage |
| --- | --- |
| `DISCORD_TOKEN` | Token du bot, déjà utilisé par René. |
| `PANEL_PASSWORD` | Mot de passe fort pour accéder au panel. |
| `PANEL_SECRET` | Chaîne aléatoire d'au moins 32 caractères pour signer les sessions (par exemple `python -c "import secrets; print(secrets.token_urlsafe(48))"`). |
| `NATHGPT_API_KEY` | Ta clé `ngt_...` pour NathGPT. La variable `token` de ton exemple fonctionne aussi. Ne la mets jamais dans le code ni dans le navigateur. |
| `PANEL_GUILD_ID` | Facultatif : identifiant du seul serveur Discord affiché dans le panel. Recommandé si le bot est présent sur plusieurs serveurs. |
| `STATE_SECRET` | Recommandé : clé stable pour la sauvegarde chiffrée dans Discord. Si tu l'ajoutes après une première sauvegarde, René sait relire l'ancienne avec `DISCORD_TOKEN`. |

L'URL du panel est protégée par mot de passe, cookie de session signé, jeton CSRF et limitation des tentatives de connexion. Utilise **HTTPS** (fourni par Render). Le mot de passe donne accès à tous les serveurs visibles par le bot, sauf si `PANEL_GUILD_ID` limite cet accès. Ne partage donc pas ce mot de passe. La session expire après huit heures. Pour bannir un membre, le bot doit avoir la permission **Bannir des membres** et un rôle plus haut que celui du membre. Active **Server Members Intent** et **Message Content Intent** dans le portail Discord.

Le tableau affiche les membres actuels, les arrivées, départs, messages, temps en vocal, membres actifs, graphiques et journal des actions du panel. Les compteurs d'activité commencent au premier démarrage après déploiement : aucun historique de messages n'est importé. Ils conservent les 90 derniers jours via la sauvegarde chiffrée existante de René. Le temps vocal est compté à partir des événements du bot et sauvegardé toutes les minutes. Le panel peut chercher un membre, le bannir après confirmation, générer et envoyer un code cadeau unique en MP, et consulter le registre des codes distribués. **René ne sait pas vérifier si un code a été utilisé sur Roblox**, car aucun système d'activation Roblox n'est connecté ; le registre affiche la livraison du MP.

La section **René IA** et la commande Discord `/reneia` (réservée au staff) envoient une question et des statistiques agrégées à `https://nathgpt.onrender.com/v1/chat/completions`, avec le modèle `nathgpt`. La clé reste côté serveur. Le délai maximum de réponse est de 600 secondes. Aucun texte des messages Discord ni code cadeau n'est transmis à NathGPT.

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
