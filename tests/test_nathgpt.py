import asyncio
import json
import unittest
from unittest.mock import patch

from aiohttp import web
from aiohttp.test_utils import TestServer

from rene import nathgpt

TOKEN = 'secret-test'


class FakeNathGPT:
    def __init__(self):
        self.busy = 0
        self.answer = 'Bonjour !'
        self.prompts = []
        self.active = self.max_active = 0

    def app(self):
        app = web.Application()
        app.router.add_get('/health', self.health)
        app.router.add_post('/v1/ask', self.ask)
        app.router.add_post('/v1/images/generations', self.image)
        return app

    async def health(self, request):
        return web.json_response({'ok': True})

    def authorized(self, request):
        return request.headers.get('Authorization') == f'Bearer {TOKEN}'

    async def ask(self, request):
        if not self.authorized(request):
            return web.json_response({'error': 'unauthorized'}, status=401)
        if self.busy:
            self.busy -= 1
            return web.json_response({'error': 'busy'}, status=429)
        body = await request.json()
        self.prompts.append(body)
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        await asyncio.sleep(0.02)
        self.active -= 1
        if not body.get('stream'):
            return web.json_response({'ok': True, 'type': 'text', 'text': self.answer, 'answer': self.answer,
                                      'images': [], 'conversation_id': body.get('conversation_id')})
        response = web.StreamResponse(headers={'Content-Type': 'text/event-stream'})
        await response.prepare(request)
        for event, data in [('start', {}), ('delta', {'text': 'Bon'}), (None, None), ('delta', {'text': 'jour'}),
                            ('replace', {'text': 'Bonjour'}), ('done', {'answer': 'Bonjour !', 'images': []})]:
            chunk = ': keep-alive\n\n' if event is None else f'event: {event}\ndata: {json.dumps(data)}\n\n'
            await response.write(chunk.encode())
        return response

    async def image(self, request):
        return web.json_response({'data': [{'b64_json': 'aW1n'}]})


class NathGPTClientTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.fake = FakeNathGPT()
        self.server = TestServer(self.fake.app())
        await self.server.start_server()
        self.url = str(self.server.make_url('')).rstrip('/')
        self.client = nathgpt.NathGPTClient(self.url, TOKEN)
        self.delay = patch.object(nathgpt, 'BUSY_DELAY', 0)
        self.delay.start()

    async def asyncTearDown(self):
        self.delay.stop()
        await self.server.close()

    async def test_health_then_ping(self):
        self.fake.answer = 'PONG'
        result = await self.client.test()
        self.assertEqual(result['answer'], 'PONG')
        self.assertEqual(self.fake.prompts[0]['conversation_id'], 'rene_ping')

    async def test_busy_is_retried(self):
        self.fake.busy = 2
        self.assertEqual((await self.client.ask('Salut', 'user_1'))['text'], 'Bonjour !')

    async def test_bad_token_and_interface_text(self):
        with self.assertRaises(nathgpt.NathGPTError) as caught:
            await nathgpt.NathGPTClient(self.url, 'mauvais').ask('Salut')
        self.assertEqual(caught.exception.status, 401)
        for junk in ('Thinking', 'ChatGPT said:', 'Edit', '  '):
            self.fake.answer = junk
            with self.assertRaises(nathgpt.NathGPTError, msg=junk):
                await self.client.ask('Salut')

    async def test_stream_uses_done_as_final_text(self):
        shown = []

        async def on_text(text):
            shown.append(text)
        result = await self.client.ask_stream('Salut', 'user_1', on_text)
        self.assertEqual(result['text'], 'Bonjour !')
        self.assertEqual(shown, ['Bon', 'Bonjour', 'Bonjour'])

    async def test_image_and_unreachable_server(self):
        self.assertEqual(await self.client.generate_image('un chat'), [b'img'])
        with self.assertRaises(nathgpt.NathGPTError):
            await nathgpt.NathGPTClient('https://127.0.0.1:1', TOKEN).health()

    async def test_one_generation_at_a_time(self):
        await asyncio.gather(*(self.client.ask(f'Question {i}') for i in range(3)))
        self.assertEqual(len(self.fake.prompts), 3)
        self.assertEqual(self.fake.max_active, 1)

    def test_config_and_url_check(self):
        with patch.dict('os.environ', {'NATHGPT_API_URL': 'https://a.trycloudflare.com/', 'NATHGPT_API_TOKEN': 'x'}), \
                patch.object(nathgpt, 'stored_url', return_value=''):
            self.assertEqual(nathgpt.api_url(), 'https://a.trycloudflare.com')
            self.assertTrue(nathgpt.configured())
        with self.assertRaises(ValueError):
            nathgpt.clean_url('http://pas-https.com')


if __name__ == '__main__':
    unittest.main()
