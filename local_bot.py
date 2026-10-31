"""Démarre René sur le PC sans ouvrir un second panel web."""

from __future__ import annotations

import asyncio

from main import connect_discord
from rene.core import DISCORD_TOKEN


if __name__ == "__main__":
    if not DISCORD_TOKEN or not DISCORD_TOKEN.strip():
        raise SystemExit("DISCORD_TOKEN est absent. Lance run-local.ps1 pour le saisir.")
    asyncio.run(connect_discord())
