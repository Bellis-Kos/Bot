import discord 
from discord.ext import commands 
import logging 
from dotenv import load_dotenv
import os
import asyncio  
from flask import Flask
from threading import Thread

# Flask setup για το Render
app = Flask('')

@app.route('/')
def home():
    return "Bot is alive!"

def run():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run)
    t.start()

load_dotenv()
token = os.getenv('DISCORD_TOKEN')
handler = logging.FileHandler(filename='discord.log', encoding='utf-8', mode='w')

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix='[]', intents=intents, case_insensitive=True)

@bot.event
async def on_ready():
    print(f"We are logged in as {bot.user.name}")

@bot.event 
async def on_member_join(member):
    await member.send(f'Welcome to the server, {member.name}!')

BANNED_WORDS = {
    'μουνοπανο', 'μουνοπανα', 'μουνοπανος',
    'γαμημενο', 'γαμημενα', 'γαμημενος',
    'καριολη', 'καριολες', 'καριολης',
    'πουτανα', 'πουτανες', 'πουτανος',
    'παιδοφιλος', 'παιδοφιλοι',
    'μαλακας', 'μαλακες', 'μαλακης', 'μαλακια', 'μαλακα',
    'βλακας', 'βλακες', 'βλακης',
    'βλαμμενη', 'βλαμμενε', 'τουβλο', 'χαζε',  # <- Μπήκε το κόμμα εδώ!
    'ηλιθιος', 'ηλιθιοι', 'ηλιθια', 
    'παπαρας', 'παπαρες', 'παπαρος',
    'γαμαω','γαμας','γαμαμε','γαμω'
    'αρχιδι', 'αρχιδια', 'αρχιδιος',
    'πουτσα', 'πουτσες', 'πουτσος',          
    'shit', 'καθυστερημενος', 'καθυστερημενη', 'καθυστερημενο'
}

def clean_text(text):
    text = text.lower()
    
    bold = {'ά': 'α', 'έ': 'ε', 'ή': 'η', 'ί': 'ι', 'ό': 'ο', 'ύ': 'υ', 'ώ': 'ω', 'ΐ': 'ι', 'ΰ': 'υ'}
    for bold_char, simple_char in bold.items():
        text = text.replace(bold_char, simple_char)
        
    text = text.replace('ς', 'σ')
    return text

@bot.event
async def on_message(message):
    if message.author == bot.user:
        return
        
    clean_message = clean_text(message.content)
    
    if any(word in clean_message for word in BANNED_WORDS):
        try:
            await message.delete()
            await message.channel.send(f'{message.author.mention}, Πρόσεχε μουνόπανο!')
        except Exception as e:
            print(f"Δεν μπόρεσα να διαγράψω το μήνυμα: {e}")
        return 

    # Εδώ στέλνεται το κανονικό message για να δουλέψουν οι εντολές σωστά!
    await bot.process_commands(message)

@bot.command()
async def ping(ctx):
    latency = round(bot.latency * 1000) 
    await ctx.send(f'🏓 Pong! Το ping μου είναι **{latency}ms**.') 
    
@bot.command(aliases=['hi'])
async def hello(ctx):
    await ctx.send(f'Hello, {ctx.author.name}!')

@bot.command(aliases=['ev', 'announce'])
@commands.has_permissions(mention_everyone=True) 
async def pingeveryone(ctx, *, message: str):
    await ctx.message.delete()
    await ctx.send(f'@everyone {message}')

@pingeveryone.error
async def pingeveryone_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send('❌ You are noob get access and tag later ')
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send('❌ Πρέπει να γράψεις ένα μήνυμα!')

@bot.command(aliases=['purge', 'clean'])
@commands.has_permissions(manage_messages=True)
async def clear(ctx, amount: int):
    await ctx.message.delete()
    await asyncio.sleep(0.5)
    deleted = await ctx.channel.purge(limit=amount)
    confirm_msg = await ctx.send(f'🧹 Διαγράφηκαν {len(deleted)} μηνύματα!')
    await confirm_msg.delete(delay=3)

# Ξεκινάει ο Web Server για το Render
keep_alive()

# Τρέχει ο Bot
bot.run(token, log_handler=handler, log_level=logging.DEBUG)
