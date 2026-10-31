import asyncio
from rene import analytics, core

voice_sessions = {}
worker = None


async def on_message(message):
    if message.guild and not message.author.bot and core.bot.remote_state_loaded:
        analytics.record(message.guild.id, 'messages', message.author.id)


async def on_member_join(member):
    if not member.bot and core.bot.remote_state_loaded:
        analytics.record(member.guild.id, 'joins')


async def on_member_remove(member):
    if not member.bot and core.bot.remote_state_loaded:
        analytics.record(member.guild.id, 'leaves')
    started = voice_sessions.pop((member.guild.id, member.id), None)
    if started:
        analytics.voice_interval(member.guild.id, member.id, started, analytics.now())


async def on_voice_state_update(member, before, after):
    if member.bot or not core.bot.remote_state_loaded:
        return
    key = (member.guild.id, member.id)
    current = analytics.now()
    if key in voice_sessions:
        analytics.voice_interval(*key, voice_sessions.pop(key), current)
    if after.channel:
        voice_sessions[key] = current


async def on_disconnect():
    # Ne jamais compter le temps passé hors connexion comme de la présence.
    flush_voice()
    voice_sessions.clear()


def flush_voice():
    current = analytics.now()
    for key, started in list(voice_sessions.items()):
        analytics.voice_interval(*key, started, current)
        voice_sessions[key] = current


async def collect():
    while True:
        await asyncio.sleep(60)
        if not core.bot.is_ready() or not core.bot.remote_state_loaded or core.bot.stopping:
            continue
        flush_voice()
        for guild in core.bot.guilds:
            analytics.day(guild.id)
            for channel in guild.voice_channels + guild.stage_channels:
                for member in channel.members:
                    if not member.bot:
                        voice_sessions.setdefault((guild.id, member.id), analytics.now())
        core.save_runtime_json(core.CONFIG_FILE, core.bot.config_data)


LISTENERS = (on_message, on_member_join, on_member_remove, on_voice_state_update, on_disconnect)


async def setup(client):
    global worker
    for listener in LISTENERS:
        client.add_listener(listener, listener.__name__)
    worker = asyncio.create_task(collect())


async def teardown(client):
    if worker:
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)
    flush_voice()
    voice_sessions.clear()
    for listener in LISTENERS:
        client.remove_listener(listener, listener.__name__)
