"""Question à NathGPT depuis Discord, réservée au staff."""
import discord
from discord import app_commands
from rene import ai, analytics, core


@app_commands.command(name='reneia', description='Demander une analyse du serveur à René IA (staff).')
@app_commands.describe(question='Ta question sur les statistiques du serveur')
@app_commands.guild_only()
async def reneia(interaction: discord.Interaction, question: str):
    if not isinstance(interaction.user, discord.Member) or not core.member_has_moderator_role(interaction.user):
        await interaction.response.send_message('Cette commande est réservée au staff.', ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True, thinking=True)
    guild = interaction.guild
    assert guild is not None
    stats = analytics.summary(guild.id)
    context = {'guild': guild.name, 'since': stats['since'],
               'totals_30_days': stats['totals'], 'daily_30_days': stats['daily'],
               'top_members_30_days': sorted((
                   {'name': guild.get_member(int(uid)).display_name,
                    'messages': values['messages'], 'voice_seconds': round(values['voice_seconds']),
                    'active_days': values['active_days']}
                   for uid, values in stats['users'].items() if guild.get_member(int(uid))
               ), key=lambda item: item['messages'] + item['voice_seconds']/60, reverse=True)[:12]}
    try:
        answer = await ai.answer(question, context, f'discord:{interaction.user.id}')
    except ValueError as error:
        await interaction.followup.send(str(error), ephemeral=True)
        return
    # Discord limite chaque message à 2 000 caractères.
    chunks = [answer[i:i+1900] for i in range(0, len(answer), 1900)]
    for chunk in chunks[:12]:
        await interaction.followup.send(chunk, ephemeral=True)


async def setup(client):
    client.tree.add_command(reneia)


async def teardown(client):
    client.tree.remove_command(reneia.name)
