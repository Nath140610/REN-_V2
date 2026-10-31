import unittest
from unittest.mock import AsyncMock, Mock, patch

import discord
import main


class FakeBot:
    stopping = False

    def __init__(self, responses):
        self.start = AsyncMock(side_effect=responses)
        self.http = Mock()
        self.http.close = AsyncMock()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None


class StartupTest(unittest.IsolatedAsyncioTestCase):
    async def test_discord_429_waits_without_crashing(self):
        limited = discord.HTTPException(Mock(status=429, reason='Too Many Requests'), 'limité')
        client = FakeBot([limited, None])
        with patch.object(main, 'bot', client), patch.object(main, 'DISCORD_TOKEN', 'token-test'), \
             patch.object(main.asyncio, 'sleep', new_callable=AsyncMock) as sleep:
            await main.connect_discord()
        self.assertEqual(client.start.await_count, 2)
        client.http.close.assert_awaited_once()
        self.assertIs(client.http.connector, discord.utils.MISSING)
        sleep.assert_awaited_once_with(900)

    async def test_other_http_errors_are_visible(self):
        failure = discord.HTTPException(Mock(status=403, reason='Forbidden'), 'interdit')
        client = FakeBot([failure])
        with patch.object(main, 'bot', client), patch.object(main, 'DISCORD_TOKEN', 'token-test'), \
             patch.object(main.asyncio, 'sleep', new_callable=AsyncMock) as sleep:
            with self.assertRaises(discord.HTTPException):
                await main.connect_discord()
        sleep.assert_not_awaited()


if __name__ == '__main__':
    unittest.main()
