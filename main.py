import os
import json
import asyncio
import logging
from threading import Thread
from dotenv import load_dotenv
from flask import Flask

import discord
from discord.ext import commands

# -----------------------------------------
# Web Server (Keep-Alive)
# -----------------------------------------
app = Flask('')

@app.route('/')
def home():
    return "Bot is active!"

def run():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run)
    t.start()

# -----------------------------------------
# Setup & Intents
# -----------------------------------------
load_dotenv()
token = os.getenv('DISCORD_TOKEN')
handler = logging.FileHandler(filename='discord.log', encoding='utf-8', mode='w')

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.voice_states = True
intents.moderation = True

bot = commands.Bot(command_prefix='[]', intents=intents, case_insensitive=True)
CONFIG_FILE = "server_configs.json"

# -----------------------------------------
# JSON Storage Helpers
# -----------------------------------------
def load_configs():
    if not os.path.exists(CONFIG_FILE):
        return {}
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_configs(data):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)

def get_guild_setting(guild_id, key):
    configs = load_configs()
    return configs.get(str(guild_id), {}).get(key)

def update_guild_setting(guild_id, key, value):
    configs = load_configs()
    guild_id_str = str(guild_id)
    if guild_id_str not in configs:
        configs[guild_id_str] = {}
    configs[guild_id_str][key] = value
    save_configs(configs)

async def send_log_embed(guild, log_key, embed):
    channel_id = get_guild_setting(guild.id, log_key)
    if channel_id:
        channel = guild.get_channel(channel_id)
        if channel:
            await channel.send(embed=embed)

def clean_text(text):
    text = text.lower()
    accent_map = {'ά': 'α', 'έ': 'ε', 'ή': 'η', 'ί': 'ι', 'ό': 'ο', 'ύ': 'υ', 'ώ': 'ω', 'ΐ': 'ι', 'ΰ': 'υ'}
    for accented, simple in accent_map.items():
        text = text.replace(accented, simple)
    return text.replace('ς', 'σ')

BANNED_WORDS = {
    'μουνοπανο', 'μουνοπανα', 'μουνοπανος', 'γαμημενο', 'γαμημενα', 'γαμημενος',
    'καριολη', 'καριολες', 'καριολης', 'πουτανα', 'πουτανες', 'πουτανος',
    'παιδοφιλος', 'παιδοφιλοι', 'μαλακας', 'μαλακες', 'μαλακης', 'μαλακια', 'μαλακα',
    'βλακας', 'βλακες', 'βλακης', 'βλαμμενη', 'βλαμμενε', 'τουβλο', 'χαζε',
    'ηλιθιος', 'ηλιθιοι', 'ηλιθια', 'παπαρας', 'παπαρες', 'παπαρος',
    'αρχιδι', 'αρχιδια', 'αρχιδιος', 'πουτσα', 'πουτσες', 'πουτσος',
    'shit', 'καθυστερημενος', 'καθυστερημενη', 'καθυστερημενο'
}

# -----------------------------------------
# Events & Categorized Logs
# -----------------------------------------
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user.name}")

# Server Logs & Auto-Role
@bot.event
async def on_member_join(member):
    # Auto-Role
    role_id = get_guild_setting(member.guild.id, "autorole")
    if role_id:
        role = member.guild.get_role(role_id)
        if role:
            try:
                await member.add_roles(role)
            except discord.Forbidden:
                pass

    # Public Welcome
    welcome_id = get_guild_setting(member.guild.id, "welcome_channel")
    if welcome_id:
        ch = member.guild.get_channel(welcome_id)
        if ch:
            await ch.send(f'👋 Καλώς όρισες στον server {member.mention}!')

    # Server Log Event
    embed = discord.Embed(title="📥 Μέλος Μπήκε", description=f"{member.mention} ({member.name})", color=discord.Color.green())
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.set_footer(text=f"ID: {member.id}")
    await send_log_embed(member.guild, "server_logs", embed)

@bot.event
async def on_member_remove(member):
    # Public Leave
    leave_id = get_guild_setting(member.guild.id, "leave_channel")
    if leave_id:
        ch = member.guild.get_channel(leave_id)
        if ch:
            await ch.send(f'👋 Ο/Η **{member.name}** αποχώρησε.')

    # Server Log Event
    embed = discord.Embed(title="📤 Μέλος Αποχώρησε", description=f"{member.mention} ({member.name})", color=discord.Color.red())
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.set_footer(text=f"ID: {member.id}")
    await send_log_embed(member.guild, "server_logs", embed)

# Roles Logs
@bot.event
async def on_member_update(before, after):
    if before.roles != after.roles:
        added_roles = [r.mention for r in after.roles if r not in before.roles]
        removed_roles = [r.mention for r in before.roles if r not in after.roles]
        
        embed = discord.Embed(title="🛡️ Ενημέρωση Ρόλων Χρήστη", description=f"Χρήστης: {after.mention}", color=discord.Color.blue())
        if added_roles:
            embed.add_field(name="Προστέθηκαν", value=", ".join(added_roles), inline=False)
        if removed_roles:
            embed.add_field(name="Αφαιρέθηκαν", value=", ".join(removed_roles), inline=False)
        embed.set_thumbnail(url=after.display_avatar.url)
        await send_log_embed(after.guild, "roles_logs", embed)

# Message Logs
@bot.event
async def on_message_edit(before, after):
    if before.author.bot or before.content == after.content:
        return
    embed = discord.Embed(title="✏️ Επεξεργασία Μηνύματος", color=discord.Color.gold())
    embed.set_author(name=str(before.author), icon_url=before.author.display_avatar.url)
    embed.add_field(name="Κανάλι", value=before.channel.mention, inline=False)
    embed.add_field(name="Πριν", value=before.content or "*Κενό*", inline=False)
    embed.add_field(name="Μετά", value=after.content or "*Κενό*", inline=False)
    await send_log_embed(before.guild, "message_logs", embed)

@bot.event
async def on_message_delete(message):
    if message.author.bot:
        return
    embed = discord.Embed(title="🗑️ Διαγραφή Μηνύματος", color=discord.Color.dark_red())
    embed.set_author(name=str(message.author), icon_url=message.author.display_avatar.url)
    embed.add_field(name="Κανάλι", value=message.channel.mention, inline=False)
    embed.add_field(name="Περιεχόμενο", value=message.content or "*Κενό*", inline=False)
    await send_log_embed(message.guild, "message_logs", embed)

# Ban/Unban Logs
@bot.event
async def on_member_ban(guild, user):
    embed = discord.Embed(title="🔨 Ban Μέλους", description=f"Ο/Η {user.mention} ({user.name}) δέχτηκε Ban.", color=discord.Color.dark_purple())
    embed.set_thumbnail(url=user.display_avatar.url)
    await send_log_embed(guild, "ban_logs", embed)

@bot.event
async def on_member_unban(guild, user):
    embed = discord.Embed(title="Unban Μέλους", description=f"Ο/Η {user.mention} ({user.name}) έγινε Unban.", color=discord.Color.teal())
    embed.set_thumbnail(url=user.display_avatar.url)
    await send_log_embed(guild, "ban_logs", embed)

# Voice Logs
@bot.event
async def on_voice_state_update(member, before, after):
    if member.bot:
        return
    embed = None
    if before.channel is None and after.channel is not None:
        embed = discord.Embed(title="🔊 Join Voice", description=f"Ο/Η {member.mention} μπήκε στο `{after.channel.name}`", color=discord.Color.green())
    elif before.channel is not None and after.channel is None:
        embed = discord.Embed(title="🔇Left Voice", description=f"Ο/Η {member.mention} βγήκε από το `{before.channel.name}`", color=discord.Color.red())
    elif before.channel != after.channel:
        embed = discord.Embed(title="🔄 Move Voice", description=f"Ο/Η {member.mention} μετακινήθηκε: `{before.channel.name}` ➔ `{after.channel.name}`", color=discord.Color.light_grey())

    if embed:
        embed.set_thumbnail(url=member.display_avatar.url)
        await send_log_embed(member.guild, "voice_logs", embed)

# Abuse Logs & Command Processing
@bot.event
async def on_message(message):
    if message.author == bot.user:
        return

    clean_msg = clean_text(message.content)
    if any(word in clean_msg for word in BANNED_WORDS):
        try:
            await message.delete()
            await message.channel.send(f'{message.author.mention}, Πρόσεχε τις εκφράσεις σου!')
            
            # Αποστολή στο Abuse-Logs
            embed = discord.Embed(title="🚨 Εντοπισμός Υβριστικού Μηνύματος", color=discord.Color.red())
            embed.set_author(name=str(message.author), icon_url=message.author.display_avatar.url)
            embed.add_field(name="Χρήστης", value=message.author.mention, inline=True)
            embed.add_field(name="Κανάλι", value=message.channel.mention, inline=True)
            embed.add_field(name="Μήνυμα", value=f"||{message.content}||", inline=False)
            await send_log_embed(message.guild, "abuse_logs", embed)
        except Exception as e:
            print(f"Σφάλμα διαγραφής: {e}")
        return

    await bot.process_commands(message)

# -----------------------------------------
# Commands: General & Moderation
# -----------------------------------------
@bot.command()
async def ping(ctx):
    latency = round(bot.latency * 1000)
    await ctx.send(f'🏓 Pong! Το ping μου είναι **{latency}ms**.')

@bot.command(aliases=['hi'])
async def hello(ctx):
    await ctx.send(f'Hello, {ctx.author.name}!')

@bot.command(aliases=['purge', 'clean'])
@commands.has_permissions(manage_messages=True)
async def clear(ctx, amount: int):
    await ctx.message.delete()
    await asyncio.sleep(0.5)
    deleted = await ctx.channel.purge(limit=amount)
    confirm_msg = await ctx.send(f'🧹 Διαγράφηκαν {len(deleted)} μηνύματα!')
    await confirm_msg.delete(delay=3)

@bot.command(aliases=['ev', 'announce'])
@commands.has_permissions(mention_everyone=True)
async def pingeveryone(ctx, *, message: str):
    await ctx.message.delete()
    await ctx.send(f'@everyone {message}')

# -----------------------------------------
# Commands: Server Setups
# -----------------------------------------
@bot.command()
@commands.has_permissions(administrator=True)
async def setwelcome(ctx, channel: discord.TextChannel = None):
    target = channel or ctx.channel
    update_guild_setting(ctx.guild.id, "welcome_channel", target.id)
    await ctx.send(f'✅ Κανάλι Welcome: {target.mention}')

@bot.command()
@commands.has_permissions(administrator=True)
async def setleave(ctx, channel: discord.TextChannel = None):
    target = channel or ctx.channel
    update_guild_setting(ctx.guild.id, "leave_channel", target.id)
    await ctx.send(f'✅ Κανάλι Leave: {target.mention}')

@bot.command()
@commands.has_permissions(administrator=True)
async def setautorole(ctx, role: discord.Role):
    update_guild_setting(ctx.guild.id, "autorole", role.id)
    await ctx.send(f'✅ Auto-Role: **{role.name}**')

# -----------------------------------------
# Commands: Category Specific Logs Setup
# -----------------------------------------
@bot.command()
@commands.has_permissions(administrator=True)
async def setserverlogs(ctx, channel: discord.TextChannel = None):
    target = channel or ctx.channel
    update_guild_setting(ctx.guild.id, "server_logs", target.id)
    await ctx.send(f'🤖 Server-Logs ορίστηκε στο: {target.mention}')

@bot.command()
@commands.has_permissions(administrator=True)
async def setroleslogs(ctx, channel: discord.TextChannel = None):
    target = channel or ctx.channel
    update_guild_setting(ctx.guild.id, "roles_logs", target.id)
    await ctx.send(f'🤖 Roles-Logs ορίστηκε στο: {target.mention}')

@bot.command()
@commands.has_permissions(administrator=True)
async def setmessagelogs(ctx, channel: discord.TextChannel = None):
    target = channel or ctx.channel
    update_guild_setting(ctx.guild.id, "message_logs", target.id)
    await ctx.send(f'🤖 Message-Logs ορίστηκε στο: {target.mention}')

@bot.command()
@commands.has_permissions(administrator=True)
async def setbanlogs(ctx, channel: discord.TextChannel = None):
    target = channel or ctx.channel
    update_guild_setting(ctx.guild.id, "ban_logs", target.id)
    await ctx.send(f'🤖 Ban-Unban-Logs ορίστηκε στο: {target.mention}')

@bot.command()
@commands.has_permissions(administrator=True)
async def setvoicelogs(ctx, channel: discord.TextChannel = None):
    target = channel or ctx.channel
    update_guild_setting(ctx.guild.id, "voice_logs", target.id)
    await ctx.send(f'🤖 Voice-Logs ορίστηκε στο: {target.mention}')

@bot.command()
@commands.has_permissions(administrator=True)
async def setabuselogs(ctx, channel: discord.TextChannel = None):
    target = channel or ctx.channel
    update_guild_setting(ctx.guild.id, "abuse_logs", target.id)
    await ctx.send(f'🤖 Abuse-Logs ορίστηκε στο: {target.mention}')

# -----------------------------------------
# Run
# -----------------------------------------
keep_alive()
bot.run(token, log_handler=handler, log_level=logging.DEBUG)
