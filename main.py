import os
import re
import asyncio
import logging
from datetime import datetime, timezone
from threading import Thread
from dotenv import load_dotenv
from flask import Flask
from pymongo import MongoClient

import discord
from discord.ext import commands, tasks

# -----------------------------------------
# Web Server (Keep-Alive for Render)
# -----------------------------------------
app = Flask('')

@app.route('/')
def home():
    return "Bot is online with MongoDB, Plant Tracker & Smart Reminders!"

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

mongo_client = MongoClient(mongo_uri)
db = mongo_client["discord_bot_db"]
configs_col = db["server_configs"]
plants_col = db["plants_data"]

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.voice_states = True
intents.moderation = True

bot = commands.Bot(command_prefix='[]', intents=intents, case_insensitive=True)

# -----------------------------------------
# RAM Cache & Async Helpers
# -----------------------------------------
GUILD_CACHE = {}

def load_all_configs():
    global GUILD_CACHE
    try:
        for doc in configs_col.find({}):
            GUILD_CACHE[doc["_id"]] = doc
        print("✅ Settings cache loaded into RAM successfully!")
    except Exception as e:
        print(f"❌ Error loading settings cache: {e}")

def get_guild_setting(guild_id, key):
    guild_data = GUILD_CACHE.get(str(guild_id), {})
    return guild_data.get(key)

async def async_update_setting(guild_id, key, value):
    guild_id_str = str(guild_id)
    if guild_id_str not in GUILD_CACHE:
        GUILD_CACHE[guild_id_str] = {}
    GUILD_CACHE[guild_id_str][key] = value

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
            try:
                await channel.send(embed=embed)
            except Exception as e:
                print(f"Error sending embed to {log_key}: {e}")

def clean_text(text):
    text = text.lower()
    accent_map = {'ά': 'α', 'έ': 'ε', 'ή': 'η', 'ί': 'ι', 'ό': 'ο', 'ύ': 'υ', 'ώ': 'ω', 'ΐ': 'ι', 'ΰ': 'υ'}
    for accented, simple in accent_map.items():
        text = text.replace(accented, simple)
    text = text.replace('ς', 'σ')
    text = re.sub(r'[^a-zA-Z0-9α-ω\s]', '', text)
    return text

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
# UI: DM Response Button
# -----------------------------------------
class DMResponseButton(discord.ui.View):
    def __init__(self, message_id: int):
        super().__init__(timeout=None)
        self.message_id = message_id

    @discord.ui.button(label="✅ I'm on it! (Confirm Harvest)", style=discord.ButtonStyle.success)
    async def confirm_dm(self, interaction: discord.Interaction, button: discord.ui.Button):
        button.disabled = True
        button.label = "✅ Confirmed"
        await interaction.response.edit_message(view=self)
        await interaction.followup.send("Roger that! Go pick up the plants.", ephemeral=True)
        
        # Mark as responded so it won't ping @everyone
        await asyncio.to_thread(
            plants_col.update_one,
            {"message_id": self.message_id},
            {"$set": {"dm_confirmed": True}}
        )

# -----------------------------------------
# UI: Plant Interactive Buttons (Pick Up & Ownership)
# -----------------------------------------
class PlantView(discord.ui.View):
    def __init__(self, plant_id: str, planted_time: int, planter_id: int, is_released: bool = False):
        super().__init__(timeout=None)
        self.plant_id = plant_id
        self.planted_time = planted_time
        self.planter_id = planter_id
        self.is_released = is_released

        # Dynamic label & style based on release state
        if self.is_released:
            self.owner_btn.label = "✋ Claim Ownership"
            self.owner_btn.style = discord.ButtonStyle.primary
        else:
            self.owner_btn.label = "🔓 Release Ownership"
            self.owner_btn.style = discord.ButtonStyle.secondary

    @discord.ui.button(label="🌾 Pick Up (Harvest)", style=discord.ButtonStyle.success, custom_id="pickup_btn")
    async def pickup(self, interaction: discord.Interaction, button: discord.ui.Button):
        now_ts = int(discord.utils.utcnow().timestamp())
        diff_minutes = (now_ts - self.planted_time) // 60

        # Disable all buttons
        for child in self.children:
            child.disabled = True
        button.label = "✅ Completed"
        button.style = discord.ButtonStyle.secondary

        embed = interaction.message.embeds[0]
        embed.title = "🌾 Status: Picked Up"
        embed.color = discord.Color.green()

        embed.add_field(
            name="🧺 Harvested By",
            value=f"{interaction.user.mention} (<t:{now_ts}:T>)",
            inline=False
        )
        embed.add_field(
            name="⏳ Growth Duration",
            value=f"**{diff_minutes}** minutes",
            inline=True
        )

        await asyncio.to_thread(
            plants_col.update_one,
            {"message_id": interaction.message.id},
            {
                "$set": {
                    "status": "picked_up",
                    "picked_by": interaction.user.id,
                    "picked_time": now_ts,
                    "duration_minutes": diff_minutes
                }
            },
            upsert=True
        )

        await interaction.response.edit_message(embed=embed, view=self)
        await interaction.followup.send(f"✅ {interaction.user.mention}, harvest logged successfully!", ephemeral=True)

    @discord.ui.button(label="🔓 Release Ownership", style=discord.ButtonStyle.secondary, custom_id="ownership_btn")
    async def toggle_ownership(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = interaction.message.embeds[0]

        # Case 1: Owner releases ownership
        if not self.is_released:
            if interaction.user.id != self.planter_id and not interaction.user.guild_permissions.administrator:
                await interaction.response.send_message("❌ Only the owner can release this plant!", ephemeral=True)
                return

            self.is_released = True
            button.label = "✋ Claim Ownership"
            button.style = discord.ButtonStyle.primary

            embed.description = f"⚠️ **Plant is now OPEN! Anyone can claim ownership.**"
            await asyncio.to_thread(
                plants_col.update_one,
                {"message_id": interaction.message.id},
                {"$set": {"is_released": True}}
            )
            await interaction.response.edit_message(embed=embed, view=self)
            await interaction.followup.send("🔓 Ownership released!", ephemeral=True)

        # Case 2: Another user claims ownership
        else:
            self.is_released = False
            self.planter_id = interaction.user.id
            button.label = "🔓 Release Ownership"
            button.style = discord.ButtonStyle.secondary

            embed.description = f"New owner: {interaction.user.mention}"
            await asyncio.to_thread(
                plants_col.update_one,
                {"message_id": interaction.message.id},
                {"$set": {"is_released": False, "planter_id": interaction.user.id}}
            )
            await interaction.response.edit_message(embed=embed, view=self)
            await interaction.followup.send(f"✋ You claimed ownership! You will receive future reminders.", ephemeral=True)

    @property
    def owner_btn(self):
        return self.children[1]

# -----------------------------------------
# Background Task: Multi-Tier Plant Reminders
# -----------------------------------------
@tasks.loop(minutes=1)
async def check_plant_reminders():
    try:
        now_ts = int(discord.utils.utcnow().timestamp())
        
        # 15 min before (2h 45m = 9900s)
        time_for_dm = 9900
        # 10 min before / 5 min after DM (2h 50m = 10200s)
        time_for_everyone = 10200

        cursor = await asyncio.to_thread(
            plants_col.find,
            {"status": "planted"}
        )
        plants = await asyncio.to_thread(list, cursor)

        for plant in plants:
            guild = bot.get_guild(plant.get("guild_id"))
            if not guild:
                continue

            plant_channel_id = get_guild_setting(guild.id, "plant_channel")
            if not plant_channel_id:
                continue

            channel = guild.get_channel(plant_channel_id)
            if not channel:
                continue

            planted_time = plant.get("planted_time", 0)
            elapsed = now_ts - planted_time
            msg_id = plant.get("message_id")
            jump_url = f"https://discord.com/channels/{guild.id}/{channel.id}/{msg_id}"
            planter_id = plant.get("planter_id")

            # --- STEP 1: Send DM 15 minutes before readiness ---
            if elapsed >= time_for_dm and not plant.get("dm_sent", False):
                owner = guild.get_member(planter_id)
                if owner:
                    try:
                        dm_embed = discord.Embed(
                            title="🌿 Plant Reminder: 15 Minutes Remaining!",
                            description=(
                                f"Hey {owner.name}! Your plant in **{guild.name}** will be ready in 15 minutes!\n\n"
                                f"👉 **[Jump to Plant Record]({jump_url})**\n\n"
                                f"Please click the button below within 5 minutes, otherwise `@everyone` will be notified to pick it up!"
                            ),
                            color=discord.Color.gold()
                        )
                        if plant.get("image_url"):
                            dm_embed.set_thumbnail(url=plant.get("image_url"))

                        await owner.send(embed=dm_embed, view=DMResponseButton(message_id=msg_id))
                    except discord.Forbidden:
                        print(f"⚠️ Could not send DM to {owner.name} (DMs are closed).")

                # Mark DM as sent
                await asyncio.to_thread(
                    plants_col.update_one,
                    {"_id": plant["_id"]},
                    {"$set": {"dm_sent": True, "dm_sent_time": now_ts}}
                )

            # --- STEP 2: Ping @everyone if no answer within 5 minutes ---
            if elapsed >= time_for_everyone and plant.get("dm_sent", False) and not plant.get("everyone_pinged", False):
                # Check if user responded to the DM
                if not plant.get("dm_confirmed", False):
                    embed = discord.Embed(
                        title="⚠️ Unclaimed Plant Alert (~10 Minutes Left)",
                        description=(
                            f"The current planter (<@{planter_id}>) did not respond in time!\n\n"
                            f"🌾 **Plants will be ready in 10 minutes.** Anyone can go and harvest them!\n"
                            f"👉 **[Jump to Plant Record]({jump_url})**"
                        ),
                        color=discord.Color.red(),
                        timestamp=discord.utils.utcnow()
                    )
                    if plant.get("image_url"):
                        embed.set_thumbnail(url=plant.get("image_url"))

                    await channel.send(
                        content="@everyone ⚠️ Planter hasn't responded! Needs to be picked up in ~10 minutes!",
                        embed=embed
                    )

                    await asyncio.to_thread(
                        plants_col.update_one,
                        {"_id": plant["_id"]},
                        {"$set": {"everyone_pinged": True}}
                    )

    except Exception as e:
        print(f"❌ Error in plant reminder task: {e}")

# -----------------------------------------
# Events
# -----------------------------------------
@bot.event
async def on_ready():
    load_all_configs()
    if not check_plant_reminders.is_running():
        check_plant_reminders.start()
    print(f"Logged in as {bot.user.name} and connected to MongoDB!")

# Server Logs & Auto-Role
@bot.event
async def on_member_join(member):
    role_id = get_guild_setting(member.guild.id, "autorole")
    if role_id:
        role = member.guild.get_role(role_id)
        if role:
            try:
                await member.add_roles(role)
            except discord.Forbidden:
                pass

    welcome_id = get_guild_setting(member.guild.id, "welcome_channel")
    if welcome_id:
        ch = member.guild.get_channel(welcome_id)
        if ch:
            await ch.send(f'👋 Welcome to the server, {member.mention}!')

    embed = discord.Embed(title="📥 Member Joined", description=f"{member.mention} ({member.name})", color=discord.Color.green())
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.set_footer(text=f"ID: {member.id}")
    await send_log_embed(member.guild, "server_logs", embed)

@bot.event
async def on_member_remove(member):
    leave_id = get_guild_setting(member.guild.id, "leave_channel")
    if leave_id:
        ch = member.guild.get_channel(leave_id)
        if ch:
            await ch.send(f'👋 **{member.name}** left the server.')

    embed = discord.Embed(title="📤 Member Left", description=f"{member.mention} ({member.name})", color=discord.Color.red())
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.set_footer(text=f"ID: {member.id}")
    await send_log_embed(member.guild, "server_logs", embed)

# Roles Logs & Timeouts
@bot.event
async def on_member_update(before, after):
    now = datetime.now(timezone.utc)
    was_timed_out = before.timed_out_until is not None and before.timed_out_until > now
    is_timed_out = after.timed_out_until is not None and after.timed_out_until > now

    if not was_timed_out and is_timed_out:
        embed = discord.Embed(title="⏳ Timeout Issued", color=discord.Color.red(), timestamp=discord.utils.utcnow())
        embed.set_thumbnail(url=after.display_avatar.url)
        embed.add_field(name="User", value=f"{after.mention} (`{after.id}`)", inline=False)
        embed.add_field(name="Until", value=f"<t:{int(after.timed_out_until.timestamp())}:F> (<t:{int(after.timed_out_until.timestamp())}:R>)", inline=False)
        await send_log_embed(after.guild, "abuse_logs", embed)

    elif was_timed_out and not is_timed_out:
        embed = discord.Embed(title="🔓 Timeout Expired / Removed", color=discord.Color.green(), timestamp=discord.utils.utcnow())
        embed.set_thumbnail(url=after.display_avatar.url)
        embed.add_field(name="User", value=f"{after.mention} (`{after.id}`)", inline=False)
        await send_log_embed(after.guild, "abuse_logs", embed)

    if before.roles != after.roles:
        added_roles = [r.mention for r in after.roles if r not in before.roles]
        removed_roles = [r.mention for r in before.roles if r not in after.roles]
        
        embed = discord.Embed(title="🛡️ Member Roles Updated", description=f"User: {after.mention}", color=discord.Color.blue(), timestamp=discord.utils.utcnow())
        if added_roles:
            embed.add_field(name="Added", value=", ".join(added_roles), inline=False)
        if removed_roles:
            embed.add_field(name="Removed", value=", ".join(removed_roles), inline=False)
        embed.set_thumbnail(url=after.display_avatar.url)
        await send_log_embed(after.guild, "roles_logs", embed)

# Message Logs (Edit & Delete)
@bot.event
async def on_message_edit(before, after):
    if before.author.bot or before.guild is None or before.content == after.content:
        return

    embed = discord.Embed(
        title="✏️ Message Edited",
        description=f"{before.author.mention} edited a message in {before.channel.mention}. [Jump to Message]({after.jump_url})",
        color=discord.Color.gold(),
        timestamp=discord.utils.utcnow()
    )
    embed.set_author(name=f"{before.author} ({before.author.id})", icon_url=before.author.display_avatar.url)
    embed.add_field(name="Original (Before):", value=before.content or "*Empty*", inline=False)
    embed.add_field(name="New (After):", value=after.content or "*Empty*", inline=False)
    embed.set_footer(text=f"Message ID: {after.id} | Channel ID: {after.channel.id}")
    await send_log_embed(before.guild, "message_logs", embed)

@bot.event
async def on_message_delete(message):
    if message.author.bot or message.guild is None:
        return

    plant_channel_id = get_guild_setting(message.guild.id, "plant_channel")
    if plant_channel_id and message.channel.id == plant_channel_id:
        return

    embed = discord.Embed(
        title="🗑️ Message Deleted",
        description=f"Message by {message.author.mention} was deleted in {message.channel.mention}.",
        color=discord.Color.dark_red(),
        timestamp=discord.utils.utcnow()
    )
    embed.set_author(name=f"{message.author} ({message.author.id})", icon_url=message.author.display_avatar.url)
    content = message.content if message.content else "*No text content (e.g. image/attachment only)*"
    embed.add_field(name="Deleted Content:", value=content, inline=False)

    if message.attachments:
        files = "\n".join([f"[{att.filename}]({att.proxy_url})" for att in message.attachments])
        embed.add_field(name="Attachments:", value=files, inline=False)

    embed.set_footer(text=f"Message ID: {message.id} | Channel ID: {message.channel.id}")
    await send_log_embed(message.guild, "message_logs", embed)

# Ban / Unban Logs
@bot.event
async def on_member_ban(guild, user):
    embed = discord.Embed(title="🔨 Member Banned", description=f"{user.mention} ({user.name}) was banned.", color=discord.Color.dark_purple(), timestamp=discord.utils.utcnow())
    embed.set_thumbnail(url=user.display_avatar.url)
    await send_log_embed(guild, "ban_logs", embed)

@bot.event
async def on_member_unban(guild, user):
    embed = discord.Embed(title="🔓 Member Unbanned", description=f"{user.mention} ({user.name}) was unbanned.", color=discord.Color.teal(), timestamp=discord.utils.utcnow())
    embed.set_thumbnail(url=user.display_avatar.url)
    await send_log_embed(guild, "ban_logs", embed)

# Voice Logs
@bot.event
async def on_voice_state_update(member, before, after):
    if member.bot:
        return
    embed = None
    if before.channel is None and after.channel is not None:
        embed = discord.Embed(title="🔊 Joined Voice Channel", description=f"{member.mention} connected to `{after.channel.name}`", color=discord.Color.green(), timestamp=discord.utils.utcnow())
    elif before.channel is not None and after.channel is None:
        embed = discord.Embed(title="🔇 Left Voice Channel", description=f"{member.mention} disconnected from `{before.channel.name}`", color=discord.Color.red(), timestamp=discord.utils.utcnow())
    elif before.channel != after.channel:
        embed = discord.Embed(title="🔄 Switched Voice Channel", description=f"{member.mention} switched: `{before.channel.name}` ➔ `{after.channel.name}`", color=discord.Color.light_grey(), timestamp=discord.utils.utcnow())

    if embed:
        embed.set_thumbnail(url=member.display_avatar.url)
        await send_log_embed(member.guild, "voice_logs", embed)

# Dispatcher: Plant Tracker, Abuse Filter & Commands
@bot.event
async def on_message(message):
    if message.author.bot or message.guild is None:
        return

    # 1. Plant Tracker System
    plant_channel_id = get_guild_setting(message.guild.id, "plant_channel")
    if plant_channel_id and message.channel.id == plant_channel_id:
        valid_extensions = ('.png', '.jpg', '.jpeg', '.webp', '.gif')
        is_image = False
        plant_img = None

        if message.attachments:
            att = message.attachments[0]
            if (att.content_type and att.content_type.startswith('image/')) or att.filename.lower().endswith(valid_extensions):
                is_image = True
                plant_img = att

        if is_image and plant_img:
            planted_ts = int(discord.utils.utcnow().timestamp())

            try:
                file_to_send = await plant_img.to_file()

                embed = discord.Embed(
                    title="🌱 Status: Planted",
                    description=f"New entry by {message.author.mention}",
                    color=discord.Color.gold(),
                    timestamp=discord.utils.utcnow()
                )
                embed.set_author(name=f"{message.author.name}", icon_url=message.author.display_avatar.url)
                embed.add_field(name="🕒 Planted Time", value=f"<t:{planted_ts}:F> (<t:{planted_ts}:R>)", inline=False)
                embed.set_image(url=f"attachment://{plant_img.filename}")
                embed.set_footer(text="Click Pick Up when harvested, or Release Ownership to pass it to someone else.")

                view = PlantView(plant_id=str(message.id), planted_time=planted_ts, planter_id=message.author.id)
                sent_msg = await message.channel.send(file=file_to_send, embed=embed, view=view)

                try:
                    await message.delete()
                except discord.Forbidden:
                    print("❌ Missing Manage Messages permission to delete original message.")

                saved_url = sent_msg.attachments[0].url if sent_msg.attachments else plant_img.url
                await asyncio.to_thread(
                    plants_col.insert_one,
                    {
                        "message_id": sent_msg.id,
                        "guild_id": message.guild.id,
                        "planter_id": message.author.id,
                        "planted_time": planted_ts,
                        "image_url": saved_url,
                        "status": "planted",
                        "is_released": False,
                        "dm_sent": False,
                        "dm_confirmed": False,
                        "everyone_pinged": False
                    }
                )
                return
            except Exception as e:
                print(f"❌ Error uploading plant embed: {e}")

    # 2. Profanity Check & Abuse Counter
    clean_msg = clean_text(message.content)
    found_word = next((word for word in BANNED_WORDS if word in clean_msg), None)

    if found_word:
        try:
            abuse_total = await async_increment_abuse(message.guild.id, message.author.id)
            await message.channel.send(f'⚠️ {message.author.mention}, watch your language! (Violation #{abuse_total})')

            embed = discord.Embed(
                title="🚨 Profanity Detected", 
                color=discord.Color.red(),
                timestamp=discord.utils.utcnow()
            )
            embed.set_author(name=f"{message.author} ({message.author.id})", icon_url=message.author.display_avatar.url)
            embed.add_field(name="User", value=message.author.mention, inline=True)
            embed.add_field(name="Channel", value=message.channel.mention, inline=True)
            embed.add_field(name="Total Violations", value=f"⚠️ **{abuse_total} violation(s)**", inline=False)
            embed.add_field(name="Detected Word", value=f"`{found_word}`", inline=False)
            embed.add_field(name="Full Message", value=f"||{message.content}||", inline=False)
            embed.set_footer(text=f"User ID: {message.author.id}")
            
            await send_log_embed(message.guild, "abuse_logs", embed)
        except Exception as e:
            print(f"❌ Error logging abuse: {e}")

    # 3. Process Commands
    await bot.process_commands(message)

# -----------------------------------------
# Commands: General & Moderation
# -----------------------------------------
@bot.command()
async def ping(ctx):
    latency = round(bot.latency * 1000)
    await ctx.send(f'🏓 Pong! Latency: **{latency}ms**.')

@bot.command(aliases=['hi'])
async def hello(ctx):
    await ctx.send(f'Hello, {ctx.author.name}!')

@bot.command(aliases=['purge', 'clean'])
@commands.has_permissions(manage_messages=True)
async def clear(ctx, amount: int):
    await ctx.message.delete()
    await asyncio.sleep(0.5)
    deleted = await ctx.channel.purge(limit=amount)
    confirm_msg = await ctx.send(f'🧹 Cleared {len(deleted)} messages!')
    await confirm_msg.delete(delay=3)

@bot.command(aliases=['ev', 'announce'])
@commands.has_permissions(mention_everyone=True)
async def pingeveryone(ctx, *, message: str):
    await ctx.message.delete()
    await ctx.send(f'@everyone {message}')

# -----------------------------------------
# Commands: Setups
# -----------------------------------------
@bot.command()
@commands.has_permissions(administrator=True)
async def setwelcome(ctx, channel: discord.TextChannel = None):
    target = channel or ctx.channel
    await async_update_setting(ctx.guild.id, "welcome_channel", target.id)
    embed = discord.Embed(title="🎉 Welcome Channel Set", description=f"Channel: {target.mention}", color=discord.Color.green())
    await ctx.send(embed=embed)

@bot.command()
@commands.has_permissions(administrator=True)
async def setleave(ctx, channel: discord.TextChannel = None):
    target = channel or ctx.channel
    await async_update_setting(ctx.guild.id, "leave_channel", target.id)
    embed = discord.Embed(title="👋 Leave Channel Set", description=f"Channel: {target.mention}", color=discord.Color.orange())
    await ctx.send(embed=embed)

@bot.command()
@commands.has_permissions(administrator=True)
async def setautorole(ctx, role: discord.Role):
    await async_update_setting(ctx.guild.id, "autorole", role.id)
    embed = discord.Embed(title="🛡️️ Auto-Role Set", description=f"Role: {role.mention}", color=discord.Color.purple())
    await ctx.send(embed=embed)

@bot.command()
@commands.has_permissions(administrator=True)
async def setserverlogs(ctx, channel: discord.TextChannel = None):
    target = channel or ctx.channel
    await async_update_setting(ctx.guild.id, "server_logs", target.id)
    await ctx.send(f'🤖 Server-Logs set to: {target.mention}')

@bot.command()
@commands.has_permissions(administrator=True)
async def setroleslogs(ctx, channel: discord.TextChannel = None):
    target = channel or ctx.channel
    await async_update_setting(ctx.guild.id, "roles_logs", target.id)
    await ctx.send(f'🤖 Roles-Logs set to: {target.mention}')

@bot.command()
@commands.has_permissions(administrator=True)
async def setmessagelogs(ctx, channel: discord.TextChannel = None):
    target = channel or ctx.channel
    await async_update_setting(ctx.guild.id, "message_logs", target.id)
    await ctx.send(f'🤖 Message-Logs set to: {target.mention}')

@bot.command()
@commands.has_permissions(administrator=True)
async def setbanlogs(ctx, channel: discord.TextChannel = None):
    target = channel or ctx.channel
    await async_update_setting(ctx.guild.id, "ban_logs", target.id)
    await ctx.send(f'🤖 Ban-Unban-Logs set to: {target.mention}')

@bot.command()
@commands.has_permissions(administrator=True)
async def setvoicelogs(ctx, channel: discord.TextChannel = None):
    target = channel or ctx.channel
    await async_update_setting(ctx.guild.id, "voice_logs", target.id)
    await ctx.send(f'🤖 Voice-Logs set to: {target.mention}')

@bot.command()
@commands.has_permissions(administrator=True)
async def setabuselogs(ctx, channel: discord.TextChannel = None):
    target = channel or ctx.channel
    await async_update_setting(ctx.guild.id, "abuse_logs", target.id)
    await ctx.send(f'🤖 Abuse-Logs set to: {target.mention}')

@bot.command()
@commands.has_permissions(administrator=True)
async def setplantchannel(ctx, channel: discord.TextChannel = None):
    target = channel or ctx.channel
    await async_update_setting(ctx.guild.id, "plant_channel", target.id)
    embed = discord.Embed(
        title="🌱 Plant Channel Set",
        description=f"Plant / Pick Up tracker enabled in: {target.mention}",
        color=discord.Color.green()
    )
    await ctx.send(embed=embed)

# Error Handler
@setwelcome.error
@setleave.error
@setautorole.error
@setserverlogs.error
@setroleslogs.error
@setmessagelogs.error
@setbanlogs.error
@setvoicelogs.error
@setabuselogs.error
@setplantchannel.error
async def admin_perms_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send('❌ You must be an Administrator to run this command!')

# -----------------------------------------
# Start Bot
# -----------------------------------------
keep_alive()
bot.run(token)
