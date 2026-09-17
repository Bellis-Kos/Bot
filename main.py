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
# Web Server (Keep-Alive για Render)
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
# Αρχικοποίηση & Intents
# -----------------------------------------
load_dotenv()
token = os.getenv('DISCORD_TOKEN')
handler = logging.FileHandler(filename='discord.log', encoding='utf-8', mode='w')

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.voice_states = True

bot = commands.Bot(command_prefix='[]', intents=intents, case_insensitive=True)
CONFIG_FILE = "server_configs.json"

# -----------------------------------------
# JSON Helpers
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
# Events
# -----------------------------------------
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user.name}")

@bot.event
async def on_member_join(member):
    guild = member.guild
    
    # Προσωπικό μήνυμα
    try:
        await member.send(f'Welcome to the server, {member.name}!')
    except Exception:
        pass

    # Auto-Role
    role_id = get_guild_setting(guild.id, "autorole")
    if role_id:
        role = guild.get_role(role_id)
        if role:
            try:
                await member.add_roles(role)
            except discord.Forbidden:
                print(f"Αποτυχία ρόλου: Ο ρόλος του bot πρέπει να είναι πιο ψηλά στη λίστα.")

    # Welcome Channel
    welcome_channel_id = get_guild_setting(guild.id, "welcome_channel")
    if welcome_channel_id:
        ch = guild.get_channel(welcome_channel_id)
        if ch:
            await ch.send(f'👋 Καλώς όρισες στον server {member.mention}!')

@bot.event
async def on_member_remove(member):
    leave_channel_id = get_guild_setting(member.guild.id, "leave_channel")
    if leave_channel_id:
        ch = member.guild.get_channel(leave_channel_id)
        if ch:
            await ch.send(f'👋 Ο/Η **{member.name}** αποχώρησε από τον server.')

@bot.event
async def on_message_edit(before, after):
    if before.author.bot or before.content == after.content:
        return
    log_channel_id = get_guild_setting(before.guild.id, "log_channel")
    if log_channel_id:
        ch = before.guild.get_channel(log_channel_id)
        if ch:
            embed = discord.Embed(title="✏️ Επεξεργασία Μηνύματος", color=discord.Color.blue())
            embed.set_author(name=f"{before.author}", icon_url=before.author.display_avatar.url)
            embed.add_field(name="Κανάλι", value=before.channel.mention, inline=False)
            embed.add_field(name="Πριν", value=before.content or "*Κενό*", inline=False)
            embed.add_field(name="Μετά", value=after.content or "*Κενό*", inline=False)
            await ch.send(embed=embed)

@bot.event
async def on_voice_state_update(member, before, after):
    if member.bot:
        return
    log_channel_id = get_guild_setting(member.guild.id, "log_channel")
    if not log_channel_id:
        return
    ch = member.guild.get_channel(log_channel_id)
    if not ch:
        return

    if before.channel is None and after.channel is not None:
        await ch.send(f'🔊 Ο/Η **{member.name}** μπήκε στο κανάλι: `{after.channel.name}`')
    elif before.channel is not None and after.channel is None:
        await ch.send(f'🔇 Ο/Η **{member.name}** βγήκε από το κανάλι: `{before.channel.name}`')
    elif before.channel != after.channel:
        await ch.send(f'🔄 Ο/Η **{member.name}** μετακινήθηκε από `{before.channel.name}` σε `{after.channel.name}`')

@bot.event
async def on_message(message):
    if message.author == bot.user:
        return

    clean_msg = clean_text(message.content)
    if any(word in clean_msg for word in BANNED_WORDS):
        try:
            await message.delete()
            await message.channel.send(f'{message.author.mention}, Πρόσεχε τις εκφράσεις σου!')
        except Exception as e:
            print(f"Σφάλμα διαγραφής μηνύματος: {e}")
        return

    await bot.process_commands(message)

# -----------------------------------------
# Γενικές Εντολές
# -----------------------------------------
@bot.command()
async def ping(ctx):
    latency = round(bot.latency * 1000)
    await ctx.send(f'🏓 Pong! Το ping μου είναι **{latency}ms**.')

@bot.command(aliases=['hi'])
async def hello(ctx):
    await ctx.send(f'Hello, {ctx.author.name}!')

# -----------------------------------------
# Moderation Εντολές
# -----------------------------------------
@bot.command(aliases=['purge', 'clean'])
@commands.has_permissions(manage_messages=True)
async def clear(ctx, amount: int):
    await ctx.message.delete()
    await asyncio.sleep(0.5)
    deleted = await ctx.channel.purge(limit=amount)
    confirm_msg = await ctx.send(f'🧹 Διαγράφηκαν {len(deleted)} μηνύματα!')
    await confirm_msg.delete(delay=3)

@clear.error
async def clear_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send('❌ Δεν έχεις δικαίωμα διαχείρισης μηνυμάτων!')
    elif isinstance(error, (commands.MissingRequiredArgument, commands.BadArgument)):
        await ctx.send('❌ Χρήση: `[]clear <αριθμός>` (π.χ. `[]clear 5`)')

@bot.command(aliases=['ev', 'announce'])
@commands.has_permissions(mention_everyone=True)
async def pingeveryone(ctx, *, message: str):
    await ctx.message.delete()
    await ctx.send(f'@everyone {message}')

@pingeveryone.error
async def pingeveryone_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send('❌ Δεν έχεις το δικαίωμα (Mention Everyone) στον server!')
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send('❌ Πρέπει να γράψεις ένα μήνυμα! (π.χ. `[]pingeveryone Ανακοίνωση`)')

# -----------------------------------------
# Εντολές Ρυθμίσεων Server (Admin Only)
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
async def setlogs(ctx, channel: discord.TextChannel = None):
    target = channel or ctx.channel
    update_guild_setting(ctx.guild.id, "log_channel", target.id)
    await ctx.send(f'✅ Κανάλι Logs: {target.mention}')

@bot.command()
@commands.has_permissions(administrator=True)
async def setautorole(ctx, role: discord.Role):
    update_guild_setting(ctx.guild.id, "autorole", role.id)
    await ctx.send(f'✅ Auto-Role: **{role.name}**')

# Error handler για τις admin εντολές
@setwelcome.error
@setleave.error
@setlogs.error
@setautorole.error
async def admin_commands_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send('❌ Πρέπει να είσαι Administrator για να εκτελέσεις αυτή την εντολή!')

# -----------------------------------------
# Εκκίνηση
# -----------------------------------------
keep_alive()
bot.run(token, log_handler=handler, log_level=logging.DEBUG)
