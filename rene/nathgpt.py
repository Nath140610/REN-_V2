"""Client NathGPT : l'API ChatGPT personnelle de Nath, appelée seulement côté serveur.

Configuration (jamais en dur dans le code) :
  NATHGPT_API_URL   : adresse du serveur (elle change à chaque redémarrage du tunnel). L'adresse
                      enregistrée dans le panel (Réglages > NathGPT) passe avant la variable Render.
  NATHGPT_API_TOKEN : token Bearer (NATHGPT_API_KEY, NATHGPT_TOKEN et token restent acceptés).

Le serveur ne fait qu'une génération à la fois : toutes les demandes de René passent par un verrou
et un HTTP 429 « busy » est réessayé après quelques secondes.

Test en ligne de commande :  python -m rene.nathgpt
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import re
from collections.abc import AsyncIterator, Awaitable, Callable

import aiohttp

URL_STORE = '_nathgpt_url'
CONVERSATION_ID = re.compile(r'^[A-Za-z0-9._-]{1,80}$')
# Texte de l'interface de ChatGPT, jamais une vraie réponse.
INTERFACE_TEXT = re.compile(r'^\s*(think(ing)?|edit|chatgpt said:?|chatgpt a dit\s*:?)\s*[.…]*\s*$', re.IGNORECASE)
BUSY_RETRIES = 8
BUSY_DELAY = 5
ANSWER_TIMEOUT = 300
IMAGE_TIMEOUT = 600


class NathGPTError(Exception):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


def stored_url() -> str:
    try:
        from rene import core
        return str(core.bot.config_data.get(URL_STORE) or '').strip()
    except Exception:
        return ''


def api_url() -> str:
    return (stored_url() or os.getenv('NATHGPT_API_URL', '')).strip().rstrip('/')


def api_token() -> str:
    for name in ('NATHGPT_API_TOKEN', 'NATHGPT_API_KEY', 'NATHGPT_TOKEN', 'token'):
        value = os.getenv(name, '').strip()
        if value:
            return value
    return ''


def configured() -> bool:
    return bool(api_url() and api_token())


def clean_url(raw: str) -> str:
    url = str(raw or '').strip().rstrip('/')
    if url and not re.fullmatch(r'https://[A-Za-z0-9.-]+(:\d+)?(/[A-Za-z0-9._~/-]*)?', url):
        raise ValueError('L’adresse NathGPT doit commencer par https:// (ex. https://xxxx.trycloudflare.com).')
    return url


def is_interface_text(text: str) -> bool:
    return not text.strip() or bool(INTERFACE_TEXT.match(text))


def error_for(status: int, detail: str = '') -> NathGPTError:
    messages = {
        401: 'Token NathGPT refusé : vérifie NATHGPT_API_TOKEN sur Render.',
        403: 'Token NathGPT refusé : vérifie NATHGPT_API_TOKEN sur Render.',
        404: 'Adresse NathGPT introuvable : l’adresse a peut-être changé (Réglages > NathGPT).',
        429: 'NathGPT est occupé par une autre génération. Réessaie dans un instant.',
        502: 'ChatGPT a échoué de son côté. Réessaie.',
        504: 'ChatGPT a mis trop de temps à répondre. Réessaie.',
    }
    text = messages.get(status, f'NathGPT a répondu une erreur (HTTP {status}).')
    if detail and status not in (401, 403):
        text = f'{text} ({detail[:160]})'
    return NathGPTError(text, status)


def detail_of(data) -> str:
    if isinstance(data, dict):
        error = data.get('error')
        if isinstance(error, dict):
            return str(error.get('message') or error.get('code') or '')
        return str(error or data.get('detail') or data.get('message') or '')
    return ''


class NathGPTClient:
    """Petite couche réutilisable. Une seule génération à la fois par boucle asyncio."""

    _locks: dict[int, asyncio.Lock] = {}
    _waiting: dict[int, int] = {}

    def __init__(self, url: str | None = None, token: str | None = None, max_queue: int = 6):
        self.url = (url or api_url()).rstrip('/')
        self.token = token or api_token()
        self.max_queue = max_queue

    # ---------- outils ----------

    def check_config(self) -> None:
        if not self.url:
            raise NathGPTError('Adresse NathGPT absente : ajoute NATHGPT_API_URL sur Render ou dans Réglages > NathGPT.')
        if not self.token:
            raise NathGPTError('Token NathGPT absent : ajoute NATHGPT_API_TOKEN dans les variables Render.')

    def headers(self) -> dict[str, str]:
        return {'Authorization': f'Bearer {self.token}', 'Content-Type': 'application/json'}

    def lock(self) -> asyncio.Lock:
        loop_id = id(asyncio.get_running_loop())
        if loop_id not in self._locks:
            self._locks[loop_id] = asyncio.Lock()
        return self._locks[loop_id]

    async def _exclusive(self, call: Callable[[], Awaitable]):
        """File d'attente : une génération à la fois, 429 réessayé quelques fois."""
        loop_id = id(asyncio.get_running_loop())
        if self._waiting.get(loop_id, 0) >= self.max_queue:
            raise NathGPTError('Trop de demandes en attente pour NathGPT. Réessaie dans une minute.', 429)
        self._waiting[loop_id] = self._waiting.get(loop_id, 0) + 1
        try:
            async with self.lock():
                for attempt in range(BUSY_RETRIES):
                    try:
                        return await call()
                    except NathGPTError as error:
                        if error.status != 429 or attempt == BUSY_RETRIES - 1:
                            raise
                        await asyncio.sleep(BUSY_DELAY)
        finally:
            self._waiting[loop_id] -= 1

    async def _post(self, path: str, body: dict, timeout: float) -> dict:
        self.check_config()
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout, sock_connect=20)) as session:
                async with session.post(self.url + path, headers=self.headers(), json=body) as response:
                    try:
                        data = await response.json(content_type=None)
                    except (aiohttp.ContentTypeError, ValueError):
                        data = None
                    if response.status != 200:
                        raise error_for(response.status, detail_of(data))
                    if not isinstance(data, dict):
                        raise NathGPTError('Réponse de NathGPT illisible.')
                    return data
        except asyncio.TimeoutError:
            raise NathGPTError('NathGPT n’a pas répondu à temps.', 504) from None
        except aiohttp.ClientError:
            raise NathGPTError('NathGPT est injoignable : le serveur est éteint ou son adresse a changé.') from None

    @staticmethod
    def body(prompt: str, conversation_id: str | None, response_type: str, files, stream: bool) -> dict:
        prompt = str(prompt or '').strip()
        if not prompt:
            raise NathGPTError('Message vide.')
        body: dict = {'prompt': prompt, 'stream': stream, 'response_type': response_type}
        if conversation_id:
            if not CONVERSATION_ID.match(conversation_id):
                raise NathGPTError('Identifiant de conversation invalide.')
            body['conversation_id'] = conversation_id
        if files:
            body['files'] = [{'filename': f['filename'], 'mime_type': f['mime_type'],
                              'base64': f['base64']} for f in files[:5]]
        return body

    @staticmethod
    def final_text(answer, images) -> str:
        text = str(answer or '').strip()
        if not images and is_interface_text(text):
            raise NathGPTError('NathGPT a renvoyé du texte d’interface au lieu d’une réponse. Réessaie.', 502)
        return text

    # ---------- API ----------

    async def health(self) -> dict:
        if not self.url:
            raise NathGPTError('Adresse NathGPT absente.')
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
                async with session.get(self.url + '/health') as response:
                    try:
                        data = await response.json(content_type=None)
                    except (aiohttp.ContentTypeError, ValueError):
                        data = {}
                    if response.status != 200:
                        raise error_for(response.status, detail_of(data))
                    return data if isinstance(data, dict) else {}
        except (aiohttp.ClientError, asyncio.TimeoutError):
            raise NathGPTError('NathGPT est injoignable : le serveur est éteint ou son adresse a changé.') from None

    async def ask(self, prompt: str, conversation_id: str | None = None, response_type: str = 'text',
                  files: list[dict] | None = None, timeout: float = ANSWER_TIMEOUT) -> dict:
        """Réponse complète : {'text', 'type', 'images', 'conversation_id'}."""
        body = self.body(prompt, conversation_id, response_type, files, False)

        async def call():
            data = await self._post('/v1/ask', body, timeout)
            if data.get('ok') is False:
                raise NathGPTError(detail_of(data) or 'NathGPT a refusé la demande.', 502)
            images = data.get('images') or []
            text = self.final_text(data.get('answer') if data.get('answer') is not None else data.get('text'), images)
            return {'text': text, 'type': data.get('type') or 'text', 'images': images,
                    'conversation_id': data.get('conversation_id') or conversation_id}
        return await self._exclusive(call)

    async def ask_stream(self, prompt: str, conversation_id: str | None = None,
                         on_text: Callable[[str], Awaitable[None]] | None = None,
                         timeout: float = ANSWER_TIMEOUT) -> dict:
        """Diffusion SSE : on_text reçoit le texte affiché au fil de l'eau ; le résultat vient de `done`."""
        body = self.body(prompt, conversation_id, 'text', None, True)

        async def call():
            self.check_config()
            shown, final = '', None
            try:
                timeout_cfg = aiohttp.ClientTimeout(total=max(timeout, 240), sock_connect=20, sock_read=max(timeout, 240))
                async with aiohttp.ClientSession(timeout=timeout_cfg) as session:
                    async with session.post(self.url + '/v1/ask', headers=self.headers(), json=body) as response:
                        if response.status != 200:
                            try:
                                data = await response.json(content_type=None)
                            except (aiohttp.ContentTypeError, ValueError):
                                data = None
                            raise error_for(response.status, detail_of(data))
                        async for event, data in sse_events(response.content):
                            if event == 'delta':
                                shown += str(data.get('text') or '')
                            elif event == 'replace':
                                shown = str(data.get('text') or '')
                            elif event == 'done':
                                final = data
                                break
                            elif event == 'error':
                                raise NathGPTError(detail_of(data) or 'NathGPT a signalé une erreur.', 502)
                            else:
                                continue
                            if on_text:
                                await on_text(shown)
            except asyncio.TimeoutError:
                raise NathGPTError('NathGPT n’a pas répondu à temps.', 504) from None
            except aiohttp.ClientError:
                raise NathGPTError('La connexion à NathGPT a été coupée pendant la réponse.') from None
            if final is None:
                raise NathGPTError('La connexion à NathGPT a été coupée avant la fin de la réponse.', 502)
            images = final.get('images') or []
            return {'text': self.final_text(final.get('answer'), images), 'images': images,
                    'conversation_id': conversation_id}
        return await self._exclusive(call)

    async def generate_image(self, prompt: str, timeout: float = IMAGE_TIMEOUT) -> list[bytes]:
        prompt = str(prompt or '').strip()
        if not prompt:
            raise NathGPTError('Décris l’image à créer.')

        async def call():
            data = await self._post('/v1/images/generations', {'prompt': prompt}, timeout)
            images = [base64.b64decode(item['b64_json']) for item in data.get('data') or []
                      if isinstance(item, dict) and item.get('b64_json')]
            if not images:
                raise NathGPTError('NathGPT n’a renvoyé aucune image.', 502)
            return images
        return await self._exclusive(call)

    async def cancel(self) -> dict:
        return await self._post('/v1/cancel', {}, 20)

    async def test(self) -> dict:
        """Test de connexion : /health puis un prompt « PING »."""
        health = await self.health()
        answer = await self.ask('Réponds seulement : PONG', conversation_id='rene_ping')
        return {'ok': True, 'health': health, 'answer': answer['text'][:200]}


async def sse_events(stream: aiohttp.StreamReader) -> AsyncIterator[tuple[str, dict]]:
    """Lit un flux text/event-stream : (événement, données JSON). Les lignes « : keep-alive » sont ignorées."""
    event, lines = 'message', []
    async for raw in stream:
        line = raw.decode('utf-8', errors='replace').rstrip('\r\n')
        if not line:
            if lines:
                text = '\n'.join(lines)
                try:
                    data = json.loads(text)
                except ValueError:
                    data = {'text': text}
                yield event, data if isinstance(data, dict) else {'text': data}
            event, lines = 'message', []
        elif line.startswith(':'):
            continue
        elif line.startswith('event:'):
            event = line[6:].strip()
        elif line.startswith('data:'):
            lines.append(line[5:].lstrip())
    if lines:
        try:
            yield event, json.loads('\n'.join(lines))
        except ValueError:
            pass


def client() -> NathGPTClient:
    return NathGPTClient()


if __name__ == '__main__':
    async def main():
        result = await client().test()
        print('NathGPT OK :', result['health'], '->', result['answer'])
    try:
        asyncio.run(main())
    except NathGPTError as error:
        raise SystemExit(f'NathGPT : {error}')
