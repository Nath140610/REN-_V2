from __future__ import annotations

import importlib
import pkgutil
from collections.abc import Iterable

from discord.ext import commands

from rene.core import logger

EXTENSION_PACKAGES: tuple[str, ...] = (
    "rene.commands",
    "rene.events",
)


def discover_extensions() -> list[str]:
    """Retourne tous les modules chargeables, sans liste à maintenir à la main."""
    importlib.invalidate_caches()
    discovered: list[str] = []

    for package_name in EXTENSION_PACKAGES:
        package = importlib.import_module(package_name)
        package_paths = getattr(package, "__path__", None)
        if package_paths is None:
            continue

        for module in pkgutil.walk_packages(
            package_paths,
            prefix=f"{package_name}.",
        ):
            leaf = module.name.rsplit(".", 1)[-1]
            if leaf.startswith("_"):
                continue
            discovered.append(module.name)

    return sorted(set(discovered))


async def load_all_extensions(bot: commands.Bot) -> list[str]:
    loaded: list[str] = []
    for extension in discover_extensions():
        if extension in bot.extensions:
            continue
        try:
            await bot.load_extension(extension)
            loaded.append(extension)
            logger.info("MODULE : chargé %s", extension)
        except Exception:
            logger.exception("MODULE : impossible de charger %s", extension)
            raise
    return loaded


async def reload_all_extensions(
    bot: commands.Bot,
) -> tuple[list[str], list[str], list[str]]:
    """
    Recharge tous les modules connus et charge les nouveaux fichiers.

    Retour : (rechargés, nouveaux, erreurs)
    """
    discovered = discover_extensions()
    reloaded: list[str] = []
    loaded: list[str] = []
    errors: list[str] = []

    # On recharge les extensions déjà présentes. Le module de /reloadmodules
    # est gardé pour la fin afin de ne pas supprimer sa propre callback en plein appel.
    reload_module = "rene.commands.reloadmodules"
    for extension in discovered:
        if extension == reload_module:
            continue
        try:
            if extension in bot.extensions:
                await bot.reload_extension(extension)
                reloaded.append(extension)
            else:
                await bot.load_extension(extension)
                loaded.append(extension)
        except Exception as exc:
            logger.exception("MODULE : échec du rechargement %s", extension)
            errors.append(f"{extension}: {type(exc).__name__}: {exc}")

    # Les extensions supprimées du disque sont déchargées.
    prefixes = tuple(f"{p}." for p in EXTENSION_PACKAGES)
    for extension in list(bot.extensions):
        if extension.startswith(prefixes) and extension not in discovered:
            try:
                await bot.unload_extension(extension)
                reloaded.append(f"{extension} (déchargé)")
            except Exception as exc:
                errors.append(f"{extension}: {type(exc).__name__}: {exc}")

    return reloaded, loaded, errors
