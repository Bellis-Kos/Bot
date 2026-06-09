import discord 
from discord.ext import commands 
import logging 
from dotenv import load_dotenv
import os
import asyncio  # Χρειάζεται για το sleep!

from flask import Flask
from threading import Thread
import os
import discord

import datetime

app = Flask('')

@app.route('/')
def home():
    return "Bot is alive!"

def run():
    # Το Render δίνει αυτόματα μια Port, πρέπει να την ακούσουμε
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run)
    t.start()

load_dotenv()
token = os.getenv("DISCORD_TOKEN")
handler = logging.FileHandler(filename='discord.log', encoding='utf-8', mode='w')

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

# Ορίζουμε το prefix σου, και το κάνουμε case_insensitive για να πιάνει και []Clear
bot = commands.Bot(command_prefix='[]', intents=intents, case_insensitive=True)

@bot.event
async def on_ready():
    print(f"We are logged in as {bot.user.name}")

@bot.event 
async def on_member_join(member):
    await member.send(f'Welcome to the server, {member.name}!')

BANNED_WORDS = {
    "malaka",'βλακα', "malakas", "poustr", "gamo","poutana","hlithie",'βλακας','μαλακας','πουστης','γαμω','πουτανα','ηλιθιε','χαζε','χαζος','ηλιθιος','χαζο','μαλακα','πουστρακι','γαμωτο','πουτανακι','ηλιθια','χαζομαρα',"βλακας", "μαλακας", "πουστης", "γκαμο", "πουτανα", "ηλιθιε", 'πουστρα'
}
@bot.command()
@commands.has_permissions(kick_members=True)
async def kick(ctx, member: discord.Member, *, reason=None):
    try:
        await member.kick(reason=reason)
        await ctx.send(f'👢 Ο χρήστης {member.mention} έφαγε kick! Αιτία: {reason}')
    except Exception as e:
        await ctx.send(f'❌ Δεν μπόρεσα να κάνω kick τον χρήστη: {e}')

# --- COMMAND ΓΙΑ MUTE (TIMEOUT) ---
@bot.command()
@commands.has_permissions(moderate_members=True)
async def mute(ctx, member: discord.Member, minutes: int, *, reason=None):
    try:
        # Ορίζουμε τη διάρκεια του timeout
        duration = datetime.timedelta(minutes=minutes)
        await member.timeout(duration, reason=reason)
        await ctx.send(f'🤫 Ο χρήστης {member.mention} έφαγε mute για {minutes} λεπτά! Αιτία: {reason}')
    except Exception as e:
        await ctx.send(f'❌ Δεν μπόρεσα να κάνω mute τον χρήστη: {e}')

# --- COMMAND ΓΙΑ UNMUTE (REMOVE TIMEOUT) ---
@bot.command()
@commands.has_permissions(moderate_members=True)
async def unmute(ctx, member: discord.Member):
    try:
        await member.timeout(None)
        await ctx.send(f'🔊 Ο χρήστης {member.mention} έγινε unmute!')
    except Exception as e:
        await ctx.send(f'❌ Δεν μπόρεσα να κάνω unmute τον χρήστη: {e}')
        
@bot.event
async def on_message(message):
    if message.author == bot.user:
        return
        
    message_content_lower = message.content.lower()
    
    if any(word in message_content_lower for word in BANNED_WORDS):
        try:
            await message.delete()
            await message.channel.send(f'{message.author.mention}, Πρόσεχε μουνόπανο!')
        except Exception as e:
            print(f"Δεν μπόρεσα να διαγράψω το μήνυμα: {e}")
        return 

    # Επιτρέπει στα commands να δουλέψουν σωστά παράλληλα με το on_message
    await bot.process_commands(message)


@bot.command(aliases=['hi'])
async def hello(ctx):
    await ctx.send(f'Hello, {ctx.author.name}!')


@bot.command(aliases=['purge', 'clean'])
@commands.has_permissions(manage_messages=True)
async def clear(ctx, amount: int):
    # 1. Σβήνει το δικό σου μήνυμα ([]clear X)
    await ctx.message.delete()
    
    # 2. Περιμένει μισό δευτερόλεπτο για να προλάβει το Discord να ενημερώσει το chat
    await asyncio.sleep(0.5)
    
    # 3. Σβήνει τα ακριβώς από πάνω μηνύματα
    deleted = await ctx.channel.purge(limit=amount)
    
    # 4. Στέλνει την επιβεβαίωση
    confirm_msg = await ctx.send(f'🧹 Διαγράφηκαν {len(deleted)} μηνύματα!')
    
    # 5. Σβήνει την επιβεβαίωση μετά από 3 δευτερόλεπτα
    await confirm_msg.delete(delay=3)

keep_alive()
FINAL_TOKEN = os.getenv("DISCORD_TOKEN") or token

if not FINAL_TOKEN:
    print("❌ ΣΦΑΛΜΑ: Δεν βρέθηκε κανένα Discord Token!")
else:
    bot.run(FINAL_TOKEN)
