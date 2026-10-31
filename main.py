from __future__ import annotations

import asyncio
import threading
import time

import discord

from rene.core import DISCORD_TOKEN, bot, logger, run_web_server


async def connect_discord() -> None:
    """Laisse la barrière temporaire expirer sans faire redémarrer Render."""
    delay = 15 * 60
    async with bot:
        while not bot.stopping:
            try:
                logger.info("Connexion de René à Discord...")
                await bot.start(DISCORD_TOKEN.strip())
                return
            except discord.HTTPException as error:
                if error.status != 429:
                    raise
                # discord.py crée une session HTTP à chaque login ; fermer la
                # précédente avant de refaire une tentative évite une fuite.
                await bot.http.close()
                bot.http.connector = discord.utils.MISSING
                # Ne pas journaliser l'exception : Cloudflare renvoie une page
                # HTML entière et la répétition de la connexion prolonge le blocage.
                logger.warning(
                    "Discord limite temporairement cette connexion (HTTP 429). "
                    "Nouvelle tentative dans %s minutes ; le site reste accessible.",
                    delay // 60,
                )
                await asyncio.sleep(delay)
                delay = min(delay * 2, 60 * 60)


def run() -> None:
    if not DISCORD_TOKEN:
        raise RuntimeError(
            "La variable d'environnement DISCORD_TOKEN est absente. "
            "Ajoute-la dans Render > Environment."
        )

    logger.info("Démarrage du serveur web Render...")
    web_thread = threading.Thread(
        target=run_web_server,
        name="rene-web-server",
        daemon=True,
    )
    web_thread.start()

    try:
        asyncio.run(connect_discord())
    except Exception:
        logger.exception("René s'est arrêté à cause d'une erreur fatale.")
        raise

    # Sur Render, /stop garde le serveur web actif pour ne pas provoquer
    # un redémarrage automatique immédiat du service.
    if bot.stopping:
        logger.info(
            "René dort volontairement. Redémarre le service Render pour le réveiller."
        )
        while True:
            time.sleep(3600)


if __name__ == "__main__":
    run()
