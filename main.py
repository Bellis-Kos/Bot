import os
import asyncio
import logging
from datetime import datetime, timezone
from threading import Thread
from dotenv import load_dotenv
from flask import Flask
from pymongo import MongoClient

import discord
from discord.ext import commands

# -----------------------------------------
# Web Server (Keep-Alive για Render)
# -----------------------------------------
app = Flask('')

@app.route('/')
def home():
    return "Bot is online with low latency & MongoDB!"

def run():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run)
    t.start()

# -----------------------------------------
# Setup & Database Connection
# -----------------------------------------
load_dotenv()
token = os.getenv('DISCORD_TOKEN')
mongo_uri = os.getenv('MONGO_URI')

# Σύνδεση με MongoDB Atlas
mongo_client = MongoClient(mongo_uri)
db = mongo_client["discord_bot_db"]
configs_col = db["server_configs"]

handler = logging.FileHandler(filename='discord.log', encoding='utf-8', mode='w')

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.voice_states = True
intents.moderation = True

bot = commands.Bot(command_prefix='[]', intents=intents, case_insensitive=True)

# -----------------------------------------
# RAM Cache & Async Helpers (Μείωση Ping)
# -----------------------------------------
GUILD_CACHE = {}

def load_all_configs():
    global GUILD_CACHE
    try:
        for doc in configs_col.find({}):
            GUILD_CACHE[doc["_id"]] = doc
        print("✅ Το Cache ρυθμίσεων φορτώθηκε επιτυχώς στη RAM!")
    except Exception as e:
        print(f"Σφάλμα φόρτωσης cache: {e}")

def get_guild_setting(guild_id, key):
    # Ανάκτηση ακαριαία από τη μνήμη RAM (0ms latency)
    guild_data = GUILD_CACHE.get(str(guild_id), {})
    return guild_data.get(key)

async def async_update_setting(guild_id, key, value):
    guild_id_str = str(guild_id)
    if guild_id_str not in GUILD_CACHE:
        GUILD_CACHE[guild_id_str] = {}
    GUILD_CACHE[guild_id_str][key] = value

    # Μη-μπλοκαριστική αποθήκευση στο background
    await asyncio.to_thread(
        configs_col.update_one,
        {"_id": guild_id_str},
        {"$set": {key: value}},
        upsert=True
    )

async def async_increment_abuse(guild_id, user_id):
    guild_id_str = str(guild_id)
    user_id_str = str(user_id)
    
    if guild_id_str not in GUILD_CACHE:
        GUILD_CACHE[guild_id_str] = {}
    if "abuse_counts" not in GUILD_CACHE[guild_id_str]:
        GUILD_CACHE[guild_id_str]["abuse_counts"] = {}
        
    current = GUILD_CACHE[guild_id_str]["abuse_counts"].get(user_id_str, 0) + 1
    GUILD_CACHE[guild_id_str]["abuse_counts"][user_id_str] = current

    # Ενημέρωση MongoDB στο background
    field_name = f"abuse_counts.{user_id_str}"
    await asyncio.to_thread(
        configs_col.update_one,
        {"_id": guild_id_str},
        {"$inc": {field_name: 1}},
        upsert=True
    )
    return current

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
# Events
# -----------------------------------------
@bot.event
async def on_ready():
    load_all_configs()
    print(f"Logged in as {bot.user.name} and connected to MongoDB!")

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

    # Public Welcome Message
    welcome_id = get_guild_setting(member.guild.id, "welcome_channel")
    if welcome_id:
        ch = member.guild.get_channel(welcome_id)
        if ch:
            await ch.send(f'👋 Καλώς όρισες στον server {member.mention}!')

    # Server Logs
    embed = discord.Embed(title="📥 Μέλος Μπήκε", description=f"{member.mention} ({member.name})", color=discord.Color.green())
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.set_footer(text=f"ID: {member.id}")
    await send_log_embed(member.guild, "server_logs", embed)

@bot.event
async def on_member_remove(member):
    # Public Leave Message
    leave_id = get_guild_setting(member.guild.id, "leave_channel")
    if leave_id:
        ch = member.guild.get_channel(leave_id)
        if ch:
            await ch.send(f'👋 Ο/Η **{member.name}** αποχώρησε.')

    # Server Logs
    embed = discord.Embed(title="📤 Μέλος Αποχώρησε", description=f"{member.mention} ({member.name})", color=discord.Color.red())
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.set_footer(text=f"ID: {member.id}")
    await send_log_embed(member.guild, "server_logs", embed)

# Roles Logs & Timeouts (Abuse Logs)
@bot.event
async def on_member_update(before, after):
    now = datetime.now(timezone.utc)
    was_timed_out = before.timed_out_until is not None and before.timed_out_until > now
    is_timed_out = after.timed_out_until is not None and after.timed_out_until > now

    # Timeout Added
    if not was_timed_out and is_timed_out:
        embed = discord.Embed(title="⏳ Timeout Επιβλήθηκε", color=discord.Color.red())
        embed.set_thumbnail(url=after.display_avatar.url)
        embed.add_field(name="Χρήστης", value=f"{after.mention} (`{after.id}`)", inline=False)
        embed.add_field(name="Διάρκεια έως", value=f"<t:{int(after.timed_out_until.timestamp())}:F> (<t:{int(after.timed_out_until.timestamp())}:R>)", inline=False)
        await send_log_embed(after.guild, "abuse_logs", embed)

    # Timeout Removed
    elif was_timed_out and not is_timed_out:
        embed = discord.Embed(title="🔓 Timeout Έληξε / Αφαιρέθηκε", color=discord.Color.green())
        embed.set_thumbnail(url=after.display_avatar.url)
        embed.add_field(name="Χρήστης", value=f"{after.mention} (`{after.id}`)", inline=False)
        await send_log_embed(after.guild, "abuse_logs", embed)

    # Role Changes
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

# Message Logs (Edit & Delete)
@bot.event
async def on_message_edit(before, after):
    if before.author.bot or before.guild is None or before.content == after.content:
        return

    embed = discord.Embed(
        title="✏️ Επεξεργασία Μηνύματος",
        description=f"Ο/Η {before.author.mention} επεξεργάστηκε ένα μήνυμα στο {before.channel.mention}. [Μετάβαση στο μήνυμα]({after.jump_url})",
        color=discord.Color.gold(),
        timestamp=discord.utils.utcnow()
    )
    embed.set_author(name=f"{before.author} ({before.author.id})", icon_url=before.author.display_avatar.url)
    embed.add_field(name="Αρχικό Μήνυμα (Πριν):", value=before.content or "*Κενό*", inline=False)
    embed.add_field(name="Νέο Μήνυμα (Μετά):", value=after.content or "*Κενό*", inline=False)
    embed.set_footer(text=f"Message ID: {after.id} | Channel ID: {after.channel.id}")
    await send_log_embed(before.guild, "message_logs", embed)

@bot.event
async def on_message_delete(message):
    if message.author.bot or message.guild is None:
        return

    embed = discord.Embed(
        title="🗑️ Διαγραφή Μηνύματος",
        description=f"Μήνυμα από {message.author.mention} διαγράφηκε στο κανάλι {message.channel.mention}.",
        color=discord.Color.dark_red(),
        timestamp=discord.utils.utcnow()
    )
    embed.set_author(name=f"{message.author} ({message.author.id})", icon_url=message.author.display_avatar.url)
    content = message.content if message.content else "*Δεν υπήρχε κείμενο (π.χ. μόνο αρχείο/εικόνα)*"
    embed.add_field(name="Περιεχόμενο που διαγράφηκε:", value=content, inline=False)

    if message.attachments:
        files = "\n".join([f"[{att.filename}]({att.proxy_url})" for att in message.attachments])
        embed.add_field(name="Συνημμένα Αρχεία:", value=files, inline=False)

    embed.set_footer(text=f"Message ID: {message.id} | Channel ID: {message.channel.id}")
    await send_log_embed(message.guild, "message_logs", embed)

# Ban / Unban Logs
@bot.event
async def on_member_ban(guild, user):
    embed = discord.Embed(title="🔨 Ban Μέλους", description=f"Ο/Η {user.mention} ({user.name}) δέχτηκε Ban.", color=discord.Color.dark_purple())
    embed.set_thumbnail(url=user.display_avatar.url)
    await send_log_embed(guild, "ban_logs", embed)

@bot.event
async def on_member_unban(guild, user):
    embed = discord.Embed(title="🔓 Unban Μέλους", description=f"Ο/Η {user.mention} ({user.name}) έγινε Unban.", color=discord.Color.teal())
    embed.set_thumbnail(url=user.display_avatar.url)
    await send_log_embed(guild, "ban_logs", embed)

# Voice Logs
@bot.event
async def on_voice_state_update(member, before, after):
    if member.bot:
        return
    embed = None
    if before.channel is None and after.channel is not None:
        embed = discord.Embed(title="🔊 Είσοδος σε Voice", description=f"Ο/Η {member.mention} μπήκε στο `{after.channel.name}`", color=discord.Color.green())
    elif before.channel is not None and after.channel is None:
        embed = discord.Embed(title="🔇 Έξοδος από Voice", description=f"Ο/Η {member.mention} βγήκε από το `{before.channel.name}`", color=discord.Color.red())
    elif before.channel != after.channel:
        embed = discord.Embed(title="🔄 Μετακίνηση Voice", description=f"Ο/Η {member.mention} μετακινήθηκε: `{before.channel.name}` ➔ `{after.channel.name}`", color=discord.Color.light_grey())

    if embed:
        embed.set_thumbnail(url=member.display_avatar.url)
        await send_log_embed(member.guild, "voice_logs", embed)

# Abuse Filter, Counter & Dispatch
@bot.event
async def on_message(message):
    if message.author.bot or message.guild is None:
        return

    clean_msg = clean_text(message.content)

    # Ελέγχουμε αν υπάρχει κάποια απαγορευμένη λέξη μέσα στο κείμενο
    found_word = next((word for word in BANNED_WORDS if word in clean_msg), None)

    if found_word:
        print(f"⚠️ Εντοπίστηκε λέξη: '{found_word}' από {message.author.name}")
        
        try:
            # 1. Αύξηση μετρητή στη RAM & αποθήκευση στη MongoDB
            abuse_total = await async_increment_abuse(message.guild.id, message.author.id)

            # 2. Προειδοποίηση στο κανάλι όπου γράφτηκε η λέξη
            await message.channel.send(f'⚠️ {message.author.mention}, πρόσεχε τις εκφράσεις σου! (Παράβαση #{abuse_total})')

            # 3. Αποστολή αναλυτικού Embed στο κανάλι Abuse Logs
            embed = discord.Embed(
                title="🚨 Εντοπισμός Υβριστικού Μηνύματος", 
                color=discord.Color.red(),
                timestamp=discord.utils.utcnow()
            )
            embed.set_author(name=f"{message.author} ({message.author.id})", icon_url=message.author.display_avatar.url)
            embed.add_field(name="Χρήστης", value=message.author.mention, inline=True)
            embed.add_field(name="Κανάλι", value=message.channel.mention, inline=True)
            embed.add_field(name="Σύνολο Παραβάσεων", value=f"⚠️ **{abuse_total}η φορά**", inline=False)
            embed.add_field(name="Λέξη που εντοπίστηκε", value=f"`{found_word}`", inline=False)
            embed.add_field(name="Πλήρες Μήνυμα", value=f"||{message.content}||", inline=False)
            embed.set_footer(text=f"User ID: {message.author.id}")
            
            await send_log_embed(message.guild, "abuse_logs", embed)

        except Exception as e:
            print(f"❌ Σφάλμα κατά την καταγραφή abuse: {e}")

    # Απαραίτητο για να συνεχίσουν να εκτελούνται όλες οι υπόλοιπες εντολές ([]ping, []setroleslogs κλπ.)
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
# Commands: Setups (Async MongoDB + RAM Cache)
# -----------------------------------------
@bot.command()
@commands.has_permissions(administrator=True)
async def setwelcome(ctx, channel: discord.TextChannel = None):
    target = channel or ctx.channel
    await async_update_setting(ctx.guild.id, "welcome_channel", target.id)
    embed = discord.Embed(title="🎉 Ρύθμιση Welcome", description=f"Κανάλι: {target.mention}", color=discord.Color.green())
    await ctx.send(embed=embed)

@bot.command()
@commands.has_permissions(administrator=True)
async def setleave(ctx, channel: discord.TextChannel = None):
    target = channel or ctx.channel
    await async_update_setting(ctx.guild.id, "leave_channel", target.id)
    embed = discord.Embed(title="👋 Ρύθμιση Leave", description=f"Κανάλι: {target.mention}", color=discord.Color.orange())
    await ctx.send(embed=embed)

@bot.command()
@commands.has_permissions(administrator=True)
async def setautorole(ctx, role: discord.Role):
    await async_update_setting(ctx.guild.id, "autorole", role.id)
    embed = discord.Embed(title="🛡️ Ρύθμιση Auto-Role", description=f"Ρόλος: {role.mention}", color=discord.Color.purple())
    await ctx.send(embed=embed)

@bot.command()
@commands.has_permissions(administrator=True)
async def setserverlogs(ctx, channel: discord.TextChannel = None):
    target = channel or ctx.channel
    await async_update_setting(ctx.guild.id, "server_logs", target.id)
    await ctx.send(f'🤖 Server-Logs ορίστηκε στο: {target.mention}')

@bot.command()
@commands.has_permissions(administrator=True)
async def setroleslogs(ctx, channel: discord.TextChannel = None):
    target = channel or ctx.channel
    await async_update_setting(ctx.guild.id, "roles_logs", target.id)
    await ctx.send(f'🤖 Roles-Logs ορίστηκε στο: {target.mention}')

@bot.command()
@commands.has_permissions(administrator=True)
async def setmessagelogs(ctx, channel: discord.TextChannel = None):
    target = channel or ctx.channel
    await async_update_setting(ctx.guild.id, "message_logs", target.id)
    await ctx.send(f'🤖 Message-Logs ορίστηκε στο: {target.mention}')

@bot.command()
@commands.has_permissions(administrator=True)
async def setbanlogs(ctx, channel: discord.TextChannel = None):
    target = channel or ctx.channel
    await async_update_setting(ctx.guild.id, "ban_logs", target.id)
    await ctx.send(f'🤖 Ban-Unban-Logs ορίστηκε στο: {target.mention}')

@bot.command()
@commands.has_permissions(administrator=True)
async def setvoicelogs(ctx, channel: discord.TextChannel = None):
    target = channel or ctx.channel
    await async_update_setting(ctx.guild.id, "voice_logs", target.id)
    await ctx.send(f'🤖 Voice-Logs ορίστηκε στο: {target.mention}')

@bot.command()
@commands.has_permissions(administrator=True)
async def setabuselogs(ctx, channel: discord.TextChannel = None):
    target = channel or ctx.channel
    await async_update_setting(ctx.guild.id, "abuse_logs", target.id)
    await ctx.send(f'🤖 Abuse-Logs ορίστηκε στο: {target.mention}')

# Global Error Handler για Admins
@setwelcome.error
@setleave.error
@setautorole.error
@setserverlogs.error
@setroleslogs.error
@setmessagelogs.error
@setbanlogs.error
@setvoicelogs.error
@setabuselogs.error
async def admin_perms_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send('❌ Πρέπει να είσαι Administrator για να εκτελέσεις αυτή την εντολή!')

# -----------------------------------------
# Run
# -----------------------------------------
keep_alive()
bot.run(token, log_handler=handler, log_level=logging.DEBUG)
