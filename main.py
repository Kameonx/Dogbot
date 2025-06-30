import discord
from discord.ext import commands
import logging
from dotenv import load_dotenv
import os
import asyncio
from aiohttp import web
import httpx
import json
import aiosqlite
from datetime import datetime
import random
from typing import Optional

load_dotenv()
token = os.getenv('DISCORD_TOKEN')
venice_api_key = os.getenv('VENICE_API_KEY')
if token is None:
    raise ValueError("DISCORD_TOKEN environment variable not set")
if venice_api_key is None:
    print("Warning: VENICE_API_KEY not set. AI features will be disabled.")

handler = logging.FileHandler(filename='discord.log', encoding='utf-8', mode='w')
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)

dogs_role_name = "Dogs"
cats_role_name = "Cats"
lizards_role_name = "Lizards"
pvp_role_name = "PVP"
dnd_role_name = "DND"
dnd1_role_name = "DND1"
dnd2_role_name = "DND2"
dnd3_role_name = "DND3"


# Venice AI Configuration
VENICE_API_URL = "https://api.venice.ai/api/v1/chat/completions"
VENICE_MODEL = "venice-uncensored"

# Database setup
async def init_database():
    """Initialize the chat history database"""
    async with aiosqlite.connect("chat_history.db") as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS chat_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                user_name TEXT NOT NULL,
                channel_id TEXT NOT NULL,
                message TEXT NOT NULL,
                response TEXT NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Create campaign table for shared D&D sessions
        await db.execute("""
            CREATE TABLE IF NOT EXISTS campaign_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                user_name TEXT NOT NULL,
                character_name TEXT,
                message TEXT NOT NULL,
                response TEXT NOT NULL,
                is_active INTEGER DEFAULT 1,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Create undo stack table for universal undo/redo
        await db.execute("""
            CREATE TABLE IF NOT EXISTS undo_stack (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                action_type TEXT NOT NULL,  -- 'chat' or 'campaign'
                action_id INTEGER NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Migration: Add user_id and action_type columns to existing undo_stack if they don't exist
        try:
            await db.execute("ALTER TABLE undo_stack ADD COLUMN user_id TEXT")
        except:
            pass  # Column already exists
        
        try:
            await db.execute("ALTER TABLE undo_stack ADD COLUMN action_type TEXT DEFAULT 'campaign'")
        except:
            pass  # Column already exists
            
        await db.commit()

async def save_chat_history(user_id: str, user_name: str, channel_id: str, message: str, response: str) -> int:
    """Save chat interaction to database, returns the action ID"""
    async with aiosqlite.connect("chat_history.db") as db:
        cursor = await db.execute(
            "INSERT INTO chat_history (user_id, user_name, channel_id, message, response) VALUES (?, ?, ?, ?, ?)",
            (user_id, user_name, channel_id, message, response)
        )
        await db.commit()
        return cursor.lastrowid or 0

async def save_campaign_history(channel_id: str, user_id: str, user_name: str, character_name: str | None, message: str, response: str) -> int:
    """Save campaign interaction to shared channel history, returns the action ID"""
    async with aiosqlite.connect("chat_history.db") as db:
        cursor = await db.execute(
            "INSERT INTO campaign_history (channel_id, user_id, user_name, character_name, message, response, is_active) VALUES (?, ?, ?, ?, ?, ?, 1)",
            (channel_id, user_id, user_name, character_name, message, response)
        )
        await db.commit()
        return cursor.lastrowid or 0

async def get_chat_history(user_id: str, limit: int = 5):
    """Get recent chat history for a user (for context)"""
    async with aiosqlite.connect("chat_history.db") as db:
        cursor = await db.execute(
            "SELECT message, response FROM chat_history WHERE user_id = ? ORDER BY timestamp ASC LIMIT ?",
            (user_id, limit)
        )
        rows = await cursor.fetchall()
        return [(str(row[0]), str(row[1])) for row in rows]

async def get_campaign_history(channel_id: str, limit: int = 10):
    """Get recent campaign history for a channel (shared between all players) - only active actions"""
    async with aiosqlite.connect("chat_history.db") as db:
        cursor = await db.execute(
            "SELECT user_name, character_name, message, response FROM campaign_history WHERE channel_id = ? AND is_active = 1 ORDER BY timestamp ASC LIMIT ?",
            (channel_id, limit)
        )
        rows = await cursor.fetchall()
        return [(str(row[0]), str(row[1]) if row[1] else None, str(row[2]), str(row[3])) for row in rows]

async def undo_last_action(channel_id: str, user_id: str) -> tuple[bool, str]:
    """Undo the last action (chat or campaign) by the user in the channel. Returns (success, message)"""
    async with aiosqlite.connect("chat_history.db") as db:
        # Try campaign action first (most recent)
        cursor = await db.execute(
            "SELECT id, user_name, character_name, message FROM campaign_history WHERE channel_id = ? AND user_id = ? AND is_active = 1 ORDER BY timestamp DESC LIMIT 1",
            (channel_id, user_id)
        )
        campaign_row = await cursor.fetchone()
        
        # Try chat action
        cursor = await db.execute(
            "SELECT id, user_name, message FROM chat_history WHERE channel_id = ? AND user_id = ? ORDER BY timestamp DESC LIMIT 1",
            (channel_id, user_id)
        )
        chat_row = await cursor.fetchone()
        
        campaign_action = None
        chat_action = None
        
        if campaign_row:
            campaign_action = {
                'id': campaign_row[0],
                'user_name': campaign_row[1],
                'character_name': campaign_row[2],
                'message': campaign_row[3],
                'type': 'campaign'
            }
        
        if chat_row:
            chat_action = {
                'id': chat_row[0],
                'user_name': chat_row[1],
                'message': chat_row[2],
                'type': 'chat'
            }
        
        # Choose the most recent action (simplified - assumes IDs are sequential)
        action_to_undo = None
        if campaign_action and chat_action:
            action_to_undo = campaign_action if campaign_action['id'] > chat_action['id'] else chat_action
        elif campaign_action:
            action_to_undo = campaign_action
        elif chat_action:
            action_to_undo = chat_action
        
        if not action_to_undo:
            return False, "No actions to undo!"
        
        if action_to_undo['type'] == 'campaign':
            # Mark campaign action as inactive
            await db.execute(
                "UPDATE campaign_history SET is_active = 0 WHERE id = ?",
                (action_to_undo['id'],)
            )
            
            player_display = action_to_undo['user_name']
            if action_to_undo['character_name']:
                player_display += f" ({action_to_undo['character_name']})"
            
            message = f"Undone campaign action by {player_display}: {action_to_undo['message'][:100]}..."
        else:
            # Delete chat action
            await db.execute(
                "DELETE FROM chat_history WHERE id = ?",
                (action_to_undo['id'],)
            )
            
            message = f"Undone chat message by {action_to_undo['user_name']}: {action_to_undo['message'][:100]}..."
        
        # Add to undo stack
        await db.execute(
            "INSERT INTO undo_stack (channel_id, user_id, action_type, action_id) VALUES (?, ?, ?, ?)",
            (channel_id, user_id, action_to_undo['type'], action_to_undo['id'])
        )
        
        await db.commit()
        return True, message

async def redo_last_undo(channel_id: str, user_id: str) -> tuple[bool, str]:
    """Redo the last undone action by the user. Returns (success, message)"""
    async with aiosqlite.connect("chat_history.db") as db:
        # Get the most recent undo by this user
        cursor = await db.execute(
            "SELECT action_type, action_id FROM undo_stack WHERE channel_id = ? AND user_id = ? ORDER BY timestamp DESC LIMIT 1",
            (channel_id, user_id)
        )
        row = await cursor.fetchone()
        
        if not row:
            return False, "No actions to redo!"
        
        action_type, action_id = row
        
        if action_type == 'campaign':
            # Get campaign action details
            cursor = await db.execute(
                "SELECT user_name, character_name, message FROM campaign_history WHERE id = ?",
                (action_id,)
            )
            action_row = await cursor.fetchone()
            
            if not action_row:
                return False, "Action not found!"
            
            user_name, char_name, action = action_row
            
            # Reactivate the action
            await db.execute(
                "UPDATE campaign_history SET is_active = 1 WHERE id = ?",
                (action_id,)
            )
            
            player_display = user_name
            if char_name:
                player_display += f" ({char_name})"
            
            message = f"Redone campaign action by {player_display}: {action[:100]}..."
        else:
            # For chat actions, we need to restore them (this is complex since we deleted them)
            # For now, just inform that chat actions can't be redone
            return False, "Chat actions cannot be redone once undone!"
        
        # Remove from undo stack
        await db.execute(
            "DELETE FROM undo_stack WHERE channel_id = ? AND user_id = ? AND action_type = ? AND action_id = ? ORDER BY timestamp DESC LIMIT 1",
            (channel_id, user_id, action_type, action_id)
        )
        
        await db.commit()
        return True, message

async def get_ai_response_with_history(user_id: str, prompt: str, max_tokens: int = 500, use_history: bool = True) -> str:
    """Get response from Venice AI with chat history context"""
    if not venice_api_key:
        return "AI features are disabled. Please set VENICE_API_KEY environment variable."
    
    messages = []
    
    # Add system message for emoji usage
    messages.append({"role": "system", "content": "You are Dogbot, a helpful AI assistant with a friendly dog personality! 🐕 Use emojis frequently and Discord formatting to make your responses engaging and fun! Use **bold** for emphasis, *italics* for subtle emphasis, `code blocks` for technical terms, and > quotes for highlighting important information. Keep responses conversational and helpful! 😊✨"})
    
    # Add chat history for context if enabled
    if use_history:
        history = await get_chat_history(user_id, limit=3)  # Last 3 exchanges
        for user_msg, ai_response in history:
            messages.append({"role": "user", "content": user_msg})
            messages.append({"role": "assistant", "content": ai_response})
    
    # Add current message
    messages.append({"role": "user", "content": prompt})
    
    headers = {
        "Authorization": f"Bearer {venice_api_key}",
        "Content-Type": "application/json"
    }
    
    data = {
        "model": VENICE_MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0.7
    }
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(VENICE_API_URL, headers=headers, json=data)
            response.raise_for_status()
            
            result = response.json()
            return result["choices"][0]["message"]["content"].strip()
    except httpx.TimeoutException:
        return "⏰ AI response timed out. Please try again."
    except httpx.HTTPStatusError as e:
        return f"❌ AI service error: {e.response.status_code}"
    except Exception as e:
        return f"❌ Error: {str(e)}"

# Keep the old function for compatibility
async def get_ai_response(user_id: str, prompt: str, max_tokens: int = 500) -> str:
    """Get response from Venice AI, without chat history context"""
    if not venice_api_key:
        return "AI features are disabled. Please set VENICE_API_KEY environment variable."
    
    headers = {
        "Authorization": f"Bearer {venice_api_key}",
        "Content-Type": "application/json"
    }
    
    data = {
        "model": VENICE_MODEL,
        "messages": [
            {"role": "system", "content": "You are Dogbot, a helpful AI assistant with a friendly dog personality! 🐕 Use emojis frequently and Discord formatting to make your responses engaging and fun! Use **bold** for emphasis, *italics* for subtle emphasis, `code blocks` for technical terms, and > quotes for highlighting important information. Keep responses conversational and helpful! 😊✨"},
            {"role": "user", "content": prompt}
        ],
        "max_tokens": max_tokens,
        "temperature": 0.7
    }
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(VENICE_API_URL, headers=headers, json=data)
            response.raise_for_status()
            
            result = response.json()
            return result["choices"][0]["message"]["content"].strip()
    except httpx.TimeoutException:
        return "⏰ AI response timed out. Please try again."
    except httpx.HTTPStatusError as e:
        return f"❌ AI service error: {e.response.status_code}"
    except Exception as e:
        return f"❌ Error: {str(e)}"

async def get_ai_response_with_campaign_history(channel_id: str, user_name: str, character_name: str | None, prompt: str, max_tokens: int = 500) -> str:
    """Get response from Venice AI using shared campaign history"""
    if not venice_api_key:
        return "AI features are disabled. Please set VENICE_API_KEY environment variable."
    
    messages = []
    
    # Add campaign context
    campaign_context = f"""You are the Dungeon Master for a D&D campaign with a friendly, engaging personality! 🎲⚔️🏰🐉 

Use Discord formatting to make the adventure more immersive:
- **Bold** for important actions, names, and dramatic moments
- *Italics* for descriptions, thoughts, and atmospheric details  
- `Code blocks` for game mechanics, dice rolls, and stats
- > Quotes for NPC dialogue and special narration
- Emojis frequently to enhance the storytelling experience

Remember all characters, their actions, the story so far, and maintain consistency across the adventure.

When you need a player to make a roll (skill checks, saving throws, attack rolls, etc.), simply ask them to "roll a d20" and they will use the !roll command. You can then interpret their roll result based on the context and difficulty of the task.

Current player: {user_name}"""
    
    if character_name:
        campaign_context += f" (playing as {character_name})"
    
    messages.append({"role": "system", "content": campaign_context})
    
    # Add campaign history for context
    history = await get_campaign_history(channel_id, limit=8)  # More history for campaigns
    for player_name, char_name, user_msg, ai_response in history:
        player_display = f"{player_name}"
        if char_name:
            player_display += f" ({char_name})"
        
        messages.append({"role": "user", "content": f"{player_display}: {user_msg}"})
        messages.append({"role": "assistant", "content": ai_response})
    
    # Add current message
    current_player = f"{user_name}"
    if character_name:
        current_player += f" ({character_name})"
    
    messages.append({"role": "user", "content": f"{current_player}: {prompt}"})
    
    headers = {
        "Authorization": f"Bearer {venice_api_key}",
        "Content-Type": "application/json"
    }
    
    data = {
        "model": VENICE_MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0.8  # Slightly higher for creativity in storytelling
    }
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(VENICE_API_URL, headers=headers, json=data)
            response.raise_for_status()
            
            result = response.json()
            return result["choices"][0]["message"]["content"].strip()
    except httpx.TimeoutException:
        return "⏰ AI response timed out. Please try again."
    except httpx.HTTPStatusError as e:
        return f"❌ AI service error: {e.response.status_code}"
    except Exception as e:
        return f"❌ Error: {str(e)}"

@bot.event
async def on_ready():
    if bot.user is not None:
        print(f"We are ready to go in, {bot.user.name}")
    else:
        print("We are ready to go in, but bot.user is None")
    
    # Initialize database
    await init_database()
    print("Chat history database initialized")

@bot.event
async def on_member_join(member):
    # Get the system channel (default channel) or the first text channel
    channel = member.guild.system_channel
    if channel is None:
        # If no system channel, find the first text channel
        for ch in member.guild.text_channels:
            if ch.permissions_for(member.guild.me).send_messages:
                channel = ch
                break
    
    if channel:
        await channel.send(f"🐶 Woof woof! Welcome to the server, {member.mention}! ")

@bot.event
async def on_message(message):
    if message.author == bot.user:
        return
    
    # Just process commands, don't handle them manually here
    await bot.process_commands(message)

# Helper function to check for admin/moderator permissions
def has_admin_or_moderator_role(ctx):
    """Check if user has Admin or Moderator role"""
    user_roles = [role.name.lower() for role in ctx.author.roles]
    return any(role in ['admin', 'moderator', 'administrator'] for role in user_roles)

@bot.command()
async def hello(ctx):
    await ctx.send(f'🐕 Woof woof! Hello {ctx.author.name}!')

@bot.command()
async def help(ctx):
    embed = discord.Embed(
        title="🐶 Dog Bot Commands", 
        description="Here are all available commands:",
        color=discord.Color.blue()
    )
    embed.add_field(name="🐕 Basic", value="`!hello` - Greet the bot\n`!help` - Show this help", inline=False)
    
    # Add note about modhelp for admins/moderators
    if has_admin_or_moderator_role(ctx):
        embed.add_field(name="👑 Admin/Moderator", value="`!modhelp` - View admin/moderator commands", inline=False)
    
    embed.add_field(name="🎭 Roles", value="`!catsrole` - Get Cats role\n`!dogsrole` - Get Dogs role\n`!lizardsrole` - Get Lizards role\n`!pvprole` - Get PVP role\n`!dndrole` - Get DND role\n`!dnd1role` - Get DND1 role\n`!dnd2role` - Get DND2 role\n`!dnd3role` - Get DND3 role\n`!removecatsrole` - Remove Cats role\n`!removedogsrole` - Remove Dogs role\n`!removelizardsrole` - Remove Lizards role\n`!removepvprole` - Remove PVP role\n`!removedndrole` - Remove DND role\n`!removednd1role` - Remove DND1 role\n`!removednd2role` - Remove DND2 role\n`!removednd3role` - Remove DND3 role", inline=False)
    embed.add_field(name="🗳️ Utility", value="`!poll <question>` - Create a poll\n`!say <message>` - Make the bot say something", inline=False)
    embed.add_field(name="🤖 AI", value="`!ask <question>` - Ask AI anything\n`!chat <message>` - Chat with AI (with memory)\n`!history` - View your recent chat history\n`!clearhistory` - Clear your chat history\n`!undo` - Undo last action\n`!redo` - Redo last undone action", inline=False)
    embed.add_field(name="🎲 D&D Campaign", value="`!dnd <action>` - Take action in campaign\n`!character <name>` - Set your character name\n`!campaign` - View campaign history\n`!clearcampaign` - Clear channel campaign\n`!roll` - Roll a d20", inline=False)
    await ctx.send(embed=embed)

@bot.command()
async def modhelp(ctx):
    """Admin/Moderator only help command"""
    if not has_admin_or_moderator_role(ctx):
        await ctx.send("❌ You need Admin or Moderator role to use this command.")
        return
    
    embed = discord.Embed(
        title="👑 Admin/Moderator Commands", 
        description="Commands available to Admins and Moderators:",
        color=discord.Color.gold()
    )
    
    embed.add_field(
        name="🎭 Role Assignment", 
        value="`!assigndogsrole @user` - Assign Dogs role\n"
              "`!assigncatsrole @user` - Assign Cats role\n"
              "`!assignlizardsrole @user` - Assign Lizards role\n"
              "`!assigndndrole @user` - Assign DND role\n"
              "`!assigndnd1role @user` - Assign DND1 role\n"
              "`!assigndnd2role @user` - Assign DND2 role\n"
              "`!assigndnd3role @user` - Assign DND3 role\n"
              "`!assignpvprole @user` - Assign PVP role", 
        inline=False
    )
    
    embed.add_field(
        name="🚫 Role Removal", 
        value="`!removedogsrolefrom @user` - Remove Dogs role\n"
              "`!removecatsrolefrom @user` - Remove Cats role\n"
              "`!removelizardsrolefrom @user` - Remove Lizards role\n"
              "`!removedndrolefrom @user` - Remove DND role\n"
              "`!removednd1rolefrom @user` - Remove DND1 role\n"
              "`!removednd2rolefrom @user` - Remove DND2 role\n"
              "`!removednd3rolefrom @user` - Remove DND3 role\n"
              "`!removepvprolefrom @user` - Remove PVP role", 
        inline=False
    )
    
    embed.set_footer(text="💡 Tip: Use @username or user mentions to specify the target user")
    await ctx.send(embed=embed)

@bot.command()
async def dogsrole(ctx):
    role = discord.utils.get(ctx.guild.roles, name=dogs_role_name)
    if role:
        await ctx.author.add_roles(role)
        await ctx.send(f"🐶 Assigned {role.name} role to {ctx.author.name}!")
    else:
        await ctx.send("Dogs role not found. Please ensure the role exists in this server.")

@bot.command()
async def catsrole(ctx):
    role = discord.utils.get(ctx.guild.roles, name=cats_role_name)
    if role:
        await ctx.author.add_roles(role)
        await ctx.send(f"🐱 Assigned {role.name} role to {ctx.author.name}!")
    else:
        await ctx.send("Cats role not found. Please ensure the role exists in this server.")

@bot.command()
async def lizardsrole(ctx):
    role = discord.utils.get(ctx.guild.roles, name=lizards_role_name)
    if role:
        await ctx.author.add_roles(role)
        await ctx.send(f"🦎 Assigned {role.name} role to {ctx.author.name}!")
    else:
        await ctx.send("Lizards role not found. Please ensure the role exists in this server.")

@bot.command()
async def dndrole(ctx):
    role = discord.utils.get(ctx.guild.roles, name=dnd_role_name)
    if role:
        await ctx.author.add_roles(role)
        await ctx.send(f"🎲 Assigned {role.name} role to {ctx.author.name}!")
    else:
        await ctx.send("DND role not found. Please ensure the role exists in this server.")

@bot.command()
async def dnd1role(ctx):
    role = discord.utils.get(ctx.guild.roles, name=dnd1_role_name)
    if role:
        await ctx.author.add_roles(role)
        await ctx.send(f"🎲 Assigned {role.name} role to {ctx.author.name}!")
    else:
        await ctx.send("DND1 role not found. Please ensure the role exists in this server.")

@bot.command()
async def dnd2role(ctx):
    role = discord.utils.get(ctx.guild.roles, name=dnd2_role_name)
    if role:
        await ctx.author.add_roles(role)
        await ctx.send(f"🎲 Assigned {role.name} role to {ctx.author.name}!")
    else:
        await ctx.send("DND2 role not found. Please ensure the role exists in this server.")

@bot.command()
async def dnd3role(ctx):
    role = discord.utils.get(ctx.guild.roles, name=dnd3_role_name)
    if role:
        await ctx.author.add_roles(role)
        await ctx.send(f"🎲 Assigned {role.name} role to {ctx.author.name}!")
    else:
        await ctx.send("DND3 role not found. Please ensure the role exists in this server.")

@bot.command()
async def pvprole(ctx):
    role = discord.utils.get(ctx.guild.roles, name=pvp_role_name)
    if role:
        await ctx.author.add_roles(role)
        await ctx.send(f"⚔️ Assigned {role.name} role to {ctx.author.name}!")
    else:
        await ctx.send("PVP role not found. Please ensure the role exists in this server.")

@bot.command()
async def removedogsrole(ctx):
    role = discord.utils.get(ctx.guild.roles, name=dogs_role_name)
    if role:
        if role in ctx.author.roles:
            await ctx.author.remove_roles(role)
            await ctx.send(f"🐶 Removed {role.name} role from {ctx.author.name}!")
        else:
            await ctx.send(f"You don't have the {role.name} role to remove.")
    else:
        await ctx.send("Dogs role not found. Please ensure the role exists in this server.")

@bot.command()
async def removecatsrole(ctx):
    role = discord.utils.get(ctx.guild.roles, name=cats_role_name)
    if role:
        if role in ctx.author.roles:
            await ctx.author.remove_roles(role)
            await ctx.send(f"🐱 Removed {role.name} role from {ctx.author.name}!")
        else:
            await ctx.send(f"You don't have the {role.name} role to remove.")
    else:
        await ctx.send("Cats role not found. Please ensure the role exists in this server.")

@bot.command()
async def removelizardsrole(ctx):
    role = discord.utils.get(ctx.guild.roles, name=lizards_role_name)
    if role:
        if role in ctx.author.roles:
            await ctx.author.remove_roles(role)
            await ctx.send(f"🦎 Removed {role.name} role from {ctx.author.name}!")
        else:
            await ctx.send(f"You don't have the {role.name} role to remove.")
    else:
        await ctx.send("Lizards role not found. Please ensure the role exists in this server.")

@bot.command()
async def removedndrole(ctx):
    role = discord.utils.get(ctx.guild.roles, name=dnd_role_name)
    if role:
        if role in ctx.author.roles:
            await ctx.author.remove_roles(role)
            await ctx.send(f"🎲 Removed {role.name} role from {ctx.author.name}!")
        else:
            await ctx.send(f"You don't have the {role.name} role to remove.")
    else:
        await ctx.send("DND role not found. Please ensure the role exists in this server.")

@bot.command()
async def removednd1role(ctx):
    role = discord.utils.get(ctx.guild.roles, name=dnd1_role_name)
    if role:
        if role in ctx.author.roles:
            await ctx.author.remove_roles(role)
            await ctx.send(f"🎲 Removed {role.name} role from {ctx.author.name}!")
        else:
            await ctx.send(f"You don't have the {role.name} role to remove.")
    else:
        await ctx.send("DND1 role not found. Please ensure the role exists in this server.")

@bot.command()
async def removednd2role(ctx):
    role = discord.utils.get(ctx.guild.roles, name=dnd2_role_name)
    if role:
        if role in ctx.author.roles:
            await ctx.author.remove_roles(role)
            await ctx.send(f"🎲 Removed {role.name} role from {ctx.author.name}!")
        else:
            await ctx.send(f"You don't have the {role.name} role to remove.")
    else:
        await ctx.send("DND2 role not found. Please ensure the role exists in this server.")

@bot.command()
async def removednd3role(ctx):
    role = discord.utils.get(ctx.guild.roles, name=dnd3_role_name)
    if role:
        if role in ctx.author.roles:
            await ctx.author.remove_roles(role)
            await ctx.send(f"🎲 Removed {role.name} role from {ctx.author.name}!")
        else:
            await ctx.send(f"You don't have the {role.name} role to remove.")
    else:
        await ctx.send("DND3 role not found. Please ensure the role exists in this server.")

@bot.command()
async def removepvprole(ctx):
    role = discord.utils.get(ctx.guild.roles, name=pvp_role_name)
    if role:
        if role in ctx.author.roles:
            await ctx.author.remove_roles(role)
            await ctx.send(f"⚔️ Removed {role.name} role from {ctx.author.name}!")
        else:
            await ctx.send(f"You don't have the {role.name} role to remove.")
    else:
        await ctx.send("PVP role not found. Please ensure the role exists in this server.")

# Admin/Moderator role assignment commands
@bot.command()
async def assigndogsrole(ctx, member: Optional[discord.Member] = None):
    """Admin/Moderator command to assign Dogs role to a user"""
    if not has_admin_or_moderator_role(ctx):
        await ctx.send("❌ You need Admin or Moderator role to use this command.")
        return
    
    if member is None:
        await ctx.send("❌ Please mention a user to assign the role to. Usage: `!assigndogsrole @username`")
        return
    
    role = discord.utils.get(ctx.guild.roles, name=dogs_role_name)
    if role:
        if role not in member.roles:
            await member.add_roles(role)
            await ctx.send(f"🐶 Assigned {role.name} role to {member.mention}!")
        else:
            await ctx.send(f"{member.mention} already has the {role.name} role.")
    else:
        await ctx.send("Dogs role not found. Please ensure the role exists in this server.")

@bot.command()
async def assigncatsrole(ctx, member: Optional[discord.Member] = None):
    """Admin/Moderator command to assign Cats role to a user"""
    if not has_admin_or_moderator_role(ctx):
        await ctx.send("❌ You need Admin or Moderator role to use this command.")
        return
    
    if member is None:
        await ctx.send("❌ Please mention a user to assign the role to. Usage: `!assigncatsrole @username`")
        return
    
    role = discord.utils.get(ctx.guild.roles, name=cats_role_name)
    if role:
        if role not in member.roles:
            await member.add_roles(role)
            await ctx.send(f"🐱 Assigned {role.name} role to {member.mention}!")
        else:
            await ctx.send(f"{member.mention} already has the {role.name} role.")
    else:
        await ctx.send("Cats role not found. Please ensure the role exists in this server.")

@bot.command()
async def assignlizardsrole(ctx, member: Optional[discord.Member] = None):
    """Admin/Moderator command to assign Lizards role to a user"""
    if not has_admin_or_moderator_role(ctx):
        await ctx.send("❌ You need Admin or Moderator role to use this command.")
        return
    
    if member is None:
        await ctx.send("❌ Please mention a user to assign the role to. Usage: `!assignlizardsrole @username`")
        return
    
    role = discord.utils.get(ctx.guild.roles, name=lizards_role_name)
    if role:
        if role not in member.roles:
            await member.add_roles(role)
            await ctx.send(f"🦎 Assigned {role.name} role to {member.mention}!")
        else:
            await ctx.send(f"{member.mention} already has the {role.name} role.")
    else:
        await ctx.send("Lizards role not found. Please ensure the role exists in this server.")

@bot.command()
async def assigndndrole(ctx, member: Optional[discord.Member] = None):
    """Admin/Moderator command to assign DND role to a user"""
    if not has_admin_or_moderator_role(ctx):
        await ctx.send("❌ You need Admin or Moderator role to use this command.")
        return
    
    if member is None:
        await ctx.send("❌ Please mention a user to assign the role to. Usage: `!assigndndrole @username`")
        return
    
    role = discord.utils.get(ctx.guild.roles, name=dnd_role_name)
    if role:
        if role not in member.roles:
            await member.add_roles(role)
            await ctx.send(f"🎲 Assigned {role.name} role to {member.mention}!")
        else:
            await ctx.send(f"{member.mention} already has the {role.name} role.")
    else:
        await ctx.send("DND role not found. Please ensure the role exists in this server.")

@bot.command()
async def assigndnd1role(ctx, member: Optional[discord.Member] = None):
    """Admin/Moderator command to assign DND1 role to a user"""
    if not has_admin_or_moderator_role(ctx):
        await ctx.send("❌ You need Admin or Moderator role to use this command.")
        return
    
    if member is None:
        await ctx.send("❌ Please mention a user to assign the role to. Usage: `!assigndnd1role @username`")
        return
    
    role = discord.utils.get(ctx.guild.roles, name=dnd1_role_name)
    if role:
        if role not in member.roles:
            await member.add_roles(role)
            await ctx.send(f"🎲 Assigned {role.name} role to {member.mention}!")
        else:
            await ctx.send(f"{member.mention} already has the {role.name} role.")
    else:
        await ctx.send("DND1 role not found. Please ensure the role exists in this server.")

@bot.command()
async def assigndnd2role(ctx, member: Optional[discord.Member] = None):
    """Admin/Moderator command to assign DND2 role to a user"""
    if not has_admin_or_moderator_role(ctx):
        await ctx.send("❌ You need Admin or Moderator role to use this command.")
        return
    
    if member is None:
        await ctx.send("❌ Please mention a user to assign the role to. Usage: `!assigndnd2role @username`")
        return
    
    role = discord.utils.get(ctx.guild.roles, name=dnd2_role_name)
    if role:
        if role not in member.roles:
            await member.add_roles(role)
            await ctx.send(f"🎲 Assigned {role.name} role to {member.mention}!")
        else:
            await ctx.send(f"{member.mention} already has the {role.name} role.")
    else:
        await ctx.send("DND2 role not found. Please ensure the role exists in this server.")

@bot.command()
async def assigndnd3role(ctx, member: Optional[discord.Member] = None):
    """Admin/Moderator command to assign DND3 role to a user"""
    if not has_admin_or_moderator_role(ctx):
        await ctx.send("❌ You need Admin or Moderator role to use this command.")
        return
    
    if member is None:
        await ctx.send("❌ Please mention a user to assign the role to. Usage: `!assigndnd3role @username`")
        return
    
    role = discord.utils.get(ctx.guild.roles, name=dnd3_role_name)
    if role:
        if role not in member.roles:
            await member.add_roles(role)
            await ctx.send(f"🎲 Assigned {role.name} role to {member.mention}!")
        else:
            await ctx.send(f"{member.mention} already has the {role.name} role.")
    else:
        await ctx.send("DND3 role not found. Please ensure the role exists in this server.")

@bot.command()
async def assignpvprole(ctx, member: Optional[discord.Member] = None):
    """Admin/Moderator command to assign PVP role to a user"""
    if not has_admin_or_moderator_role(ctx):
        await ctx.send("❌ You need Admin or Moderator role to use this command.")
        return
    
    if member is None:
        await ctx.send("❌ Please mention a user to assign the role to. Usage: `!assignpvprole @username`")
        return
    
    role = discord.utils.get(ctx.guild.roles, name=pvp_role_name)
    if role:
        if role not in member.roles:
            await member.add_roles(role)
            await ctx.send(f"⚔️ Assigned {role.name} role to {member.mention}!")
        else:
            await ctx.send(f"{member.mention} already has the {role.name} role.")
    else:
        await ctx.send("PVP role not found. Please ensure the role exists in this server.")

# Admin/Moderator role removal commands
@bot.command()
async def removedogsrolefrom(ctx, member: Optional[discord.Member] = None):
    """Admin/Moderator command to remove Dogs role from a user"""
    if not has_admin_or_moderator_role(ctx):
        await ctx.send("❌ You need Admin or Moderator role to use this command.")
        return
    
    if member is None:
        await ctx.send("❌ Please mention a user to remove the role from. Usage: `!removedogsrolefrom @username`")
        return
    
    role = discord.utils.get(ctx.guild.roles, name=dogs_role_name)
    if role:
        if role in member.roles:
            await member.remove_roles(role)
            await ctx.send(f"🐶 Removed {role.name} role from {member.mention}!")
        else:
            await ctx.send(f"{member.mention} doesn't have the {role.name} role to remove.")
    else:
        await ctx.send("Dogs role not found. Please ensure the role exists in this server.")

@bot.command()
async def removecatsrolefrom(ctx, member: Optional[discord.Member] = None):
    """Admin/Moderator command to remove Cats role from a user"""
    if not has_admin_or_moderator_role(ctx):
        await ctx.send("❌ You need Admin or Moderator role to use this command.")
        return
    
    if member is None:
        await ctx.send("❌ Please mention a user to remove the role from. Usage: `!removecatsrolefrom @username`")
        return
    
    role = discord.utils.get(ctx.guild.roles, name=cats_role_name)
    if role:
        if role in member.roles:
            await member.remove_roles(role)
            await ctx.send(f"🐱 Removed {role.name} role from {member.mention}!")
        else:
            await ctx.send(f"{member.mention} doesn't have the {role.name} role to remove.")
    else:
        await ctx.send("Cats role not found. Please ensure the role exists in this server.")

@bot.command()
async def removelizardsrolefrom(ctx, member: Optional[discord.Member] = None):
    """Admin/Moderator command to remove Lizards role from a user"""
    if not has_admin_or_moderator_role(ctx):
        await ctx.send("❌ You need Admin or Moderator role to use this command.")
        return
    
    if member is None:
        await ctx.send("❌ Please mention a user to remove the role from. Usage: `!removelizardsrolefrom @username`")
        return
    
    role = discord.utils.get(ctx.guild.roles, name=lizards_role_name)
    if role:
        if role in member.roles:
            await member.remove_roles(role)
            await ctx.send(f"🦎 Removed {role.name} role from {member.mention}!")
        else:
            await ctx.send(f"{member.mention} doesn't have the {role.name} role to remove.")
    else:
        await ctx.send("Lizards role not found. Please ensure the role exists in this server.")

@bot.command()
async def removedndrolefrom(ctx, member: Optional[discord.Member] = None):
    """Admin/Moderator command to remove DND role from a user"""
    if not has_admin_or_moderator_role(ctx):
        await ctx.send("❌ You need Admin or Moderator role to use this command.")
        return
    
    if member is None:
        await ctx.send("❌ Please mention a user to remove the role from. Usage: `!removedndrolefrom @username`")
        return
    
    role = discord.utils.get(ctx.guild.roles, name=dnd_role_name)
    if role:
        if role in member.roles:
            await member.remove_roles(role)
            await ctx.send(f"🎲 Removed {role.name} role from {member.mention}!")
        else:
            await ctx.send(f"{member.mention} doesn't have the {role.name} role to remove.")
    else:
        await ctx.send("DND role not found. Please ensure the role exists in this server.")

@bot.command()
async def removednd1rolefrom(ctx, member: Optional[discord.Member] = None):
    """Admin/Moderator command to remove DND1 role from a user"""
    if not has_admin_or_moderator_role(ctx):
        await ctx.send("❌ You need Admin or Moderator role to use this command.")
        return
    
    if member is None:
        await ctx.send("❌ Please mention a user to remove the role from. Usage: `!removednd1rolefrom @username`")
        return
    
    role = discord.utils.get(ctx.guild.roles, name=dnd1_role_name)
    if role:
        if role in member.roles:
            await member.remove_roles(role)
            await ctx.send(f"🎲 Removed {role.name} role from {member.mention}!")
        else:
            await ctx.send(f"{member.mention} doesn't have the {role.name} role to remove.")
    else:
        await ctx.send("DND1 role not found. Please ensure the role exists in this server.")

@bot.command()
async def removednd2rolefrom(ctx, member: Optional[discord.Member] = None):
    """Admin/Moderator command to remove DND2 role from a user"""
    if not has_admin_or_moderator_role(ctx):
        await ctx.send("❌ You need Admin or Moderator role to use this command.")
        return
    
    if member is None:
        await ctx.send("❌ Please mention a user to remove the role from. Usage: `!removednd2rolefrom @username`")
        return
    
    role = discord.utils.get(ctx.guild.roles, name=dnd2_role_name)
    if role:
        if role in member.roles:
            await member.remove_roles(role)
            await ctx.send(f"🎲 Removed {role.name} role from {member.mention}!")
        else:
            await ctx.send(f"{member.mention} doesn't have the {role.name} role to remove.")
    else:
        await ctx.send("DND2 role not found. Please ensure the role exists in this server.")

@bot.command()
async def removednd3rolefrom(ctx, member: Optional[discord.Member] = None):
    """Admin/Moderator command to remove DND3 role from a user"""
    if not has_admin_or_moderator_role(ctx):
        await ctx.send("❌ You need Admin or Moderator role to use this command.")
        return
    
    if member is None:
        await ctx.send("❌ Please mention a user to remove the role from. Usage: `!removednd3rolefrom @username`")
        return
    
    role = discord.utils.get(ctx.guild.roles, name=dnd3_role_name)
    if role:
        if role in member.roles:
            await member.remove_roles(role)
            await ctx.send(f"🎲 Removed {role.name} role from {member.mention}!")
        else:
            await ctx.send(f"{member.mention} doesn't have the {role.name} role to remove.")
    else:
        await ctx.send("DND3 role not found. Please ensure the role exists in this server.")

@bot.command()
async def removepvprolefrom(ctx, member: Optional[discord.Member] = None):
    """Admin/Moderator command to remove PVP role from a user"""
    if not has_admin_or_moderator_role(ctx):
        await ctx.send("❌ You need Admin or Moderator role to use this command.")
        return
    
    if member is None:
        await ctx.send("❌ Please mention a user to remove the role from. Usage: `!removepvprolefrom @username`")
        return
    
    role = discord.utils.get(ctx.guild.roles, name=pvp_role_name)
    if role:
        if role in member.roles:
            await member.remove_roles(role)
            await ctx.send(f"⚔️ Removed {role.name} role from {member.mention}!")
        else:
            await ctx.send(f"{member.mention} doesn't have the {role.name} role to remove.")
    else:
        await ctx.send("PVP role not found. Please ensure the role exists in this server.")

# Missing Commands Implementation

@bot.command()
async def say(ctx, *, message):
    """Make the bot say something"""
    if not message:
        await ctx.send("❌ Please provide a message for me to say!")
        return
    
    # Delete the original command message
    try:
        await ctx.message.delete()
    except:
        pass  # Ignore if we can't delete (permissions)
    
    await ctx.send(message)

@bot.command()
async def ask(ctx, *, question):
    """Ask AI a question without memory context"""
    if not question:
        await ctx.send("❌ Please provide a question to ask!")
        return
    
    # Send typing indicator
    async with ctx.typing():
        response = await get_ai_response(str(ctx.author.id), question)
        await ctx.send(response)

@bot.command()
async def chat(ctx, *, message):
    """Chat with AI with memory context"""
    if not message:
        await ctx.send("❌ Please provide a message to chat about!")
        return
    
    # Send typing indicator
    async with ctx.typing():
        user_id = str(ctx.author.id)
        user_name = ctx.author.display_name
        channel_id = str(ctx.channel.id)
        
        # Get AI response with history
        response = await get_ai_response_with_history(user_id, message)
        
        # Save to chat history
        await save_chat_history(user_id, user_name, channel_id, message, response)
        
        await ctx.send(response)

@bot.command()
async def history(ctx):
    """View your recent chat history"""
    user_id = str(ctx.author.id)
    
    # Get user's chat history
    history = await get_chat_history(user_id, limit=10)
    
    if not history:
        await ctx.send("📝 You don't have any chat history yet! Use `!chat` to start chatting with AI.")
        return
    
    embed = discord.Embed(
        title=f"📝 Chat History for {ctx.author.display_name}",
        color=discord.Color.green()
    )
    
    for i, (user_msg, ai_response) in enumerate(history, 1):
        # Truncate long messages
        user_msg_short = user_msg[:100] + "..." if len(user_msg) > 100 else user_msg
        ai_response_short = ai_response[:100] + "..." if len(ai_response) > 100 else ai_response
        
        embed.add_field(
            name=f"Exchange {i}",
            value=f"**You:** {user_msg_short}\n**AI:** {ai_response_short}",
            inline=False
        )
    
    await ctx.send(embed=embed)

@bot.command()
async def clearhistory(ctx):
    """Clear your chat history"""
    user_id = str(ctx.author.id)
    
    async with aiosqlite.connect("chat_history.db") as db:
        await db.execute("DELETE FROM chat_history WHERE user_id = ?", (user_id,))
        await db.commit()
    
    await ctx.send(f"🗑️ Cleared chat history for {ctx.author.display_name}!")

@bot.command()
async def undo(ctx):
    """Undo your last action"""
    channel_id = str(ctx.channel.id)
    user_id = str(ctx.author.id)
    
    success, message = await undo_last_action(channel_id, user_id)
    
    if success:
        await ctx.send(f"↩️ {message}")
    else:
        await ctx.send(f"❌ {message}")

@bot.command()
async def redo(ctx):
    """Redo your last undone action"""
    channel_id = str(ctx.channel.id)
    user_id = str(ctx.author.id)
    
    success, message = await redo_last_undo(channel_id, user_id)
    
    if success:
        await ctx.send(f"↪️ {message}")
    else:
        await ctx.send(f"❌ {message}")

@bot.command()
async def dnd(ctx, *, action):
    """Take an action in the D&D campaign"""
    if not action:
        await ctx.send("❌ Please describe your action!")
        return
    
    # Send typing indicator
    async with ctx.typing():
        channel_id = str(ctx.channel.id)
        user_id = str(ctx.author.id)
        user_name = ctx.author.display_name
        
        # Get character name if set
        character_name = None
        # Check if user has set a character name (we'll store this in a simple way)
        async with aiosqlite.connect("chat_history.db") as db:
            cursor = await db.execute(
                "SELECT character_name FROM campaign_history WHERE user_id = ? AND character_name IS NOT NULL ORDER BY timestamp DESC LIMIT 1",
                (user_id,)
            )
            row = await cursor.fetchone()
            if row:
                character_name = row[0]
        
        # Get AI response with campaign history
        response = await get_ai_response_with_campaign_history(
            channel_id, user_name, character_name, action
        )
        
        # Save to campaign history
        await save_campaign_history(channel_id, user_id, user_name, character_name, action, response)
        
        player_display = user_name
        if character_name:
            player_display += f" ({character_name})"
        
        await ctx.send(f"🎲 **{player_display}:** {action}\n\n🏰 **DM:** {response}")

@bot.command()
async def character(ctx, *, name):
    """Set your character name for D&D campaigns"""
    if not name:
        await ctx.send("❌ Please provide a character name!")
        return
    
    # Limit character name length
    if len(name) > 50:
        await ctx.send("❌ Character name must be 50 characters or less!")
        return
    
    user_id = str(ctx.author.id)
    user_name = ctx.author.display_name
    channel_id = str(ctx.channel.id)
    
    # Save a special entry to set the character name
    await save_campaign_history(
        channel_id, user_id, user_name, name, 
        f"Set character name to: {name}", 
        f"Character name set! You are now playing as {name}."
    )
    
    await ctx.send(f"🎭 {ctx.author.display_name} is now playing as **{name}**!")

@bot.command()
async def campaign(ctx):
    """View the campaign history for this channel"""
    channel_id = str(ctx.channel.id)
    
    # Get campaign history
    history = await get_campaign_history(channel_id, limit=10)
    
    if not history:
        await ctx.send("📜 No campaign history in this channel yet! Use `!dnd` to start your adventure.")
        return
    
    embed = discord.Embed(
        title="📜 Campaign History",
        description="Recent events in your adventure:",
        color=discord.Color.purple()
    )
    
    for i, (user_name, char_name, action, response) in enumerate(history, 1):
        player_display = user_name
        if char_name:
            player_display += f" ({char_name})"
        
        # Truncate long messages
        action_short = action[:150] + "..." if len(action) > 150 else action
        response_short = response[:150] + "..." if len(response) > 150 else response
        
        embed.add_field(
            name=f"Event {i}: {player_display}",
            value=f"**Action:** {action_short}\n**Result:** {response_short}",
            inline=False
        )
    
    await ctx.send(embed=embed)

@bot.command()
async def clearcampaign(ctx):
    """Clear the campaign history for this channel (Admin/Moderator only)"""
    if not has_admin_or_moderator_role(ctx):
        await ctx.send("❌ You need Admin or Moderator role to clear campaign history.")
        return
    
    channel_id = str(ctx.channel.id)
    
    async with aiosqlite.connect("chat_history.db") as db:
        await db.execute("DELETE FROM campaign_history WHERE channel_id = ?", (channel_id,))
        await db.execute("DELETE FROM undo_stack WHERE channel_id = ?", (channel_id,))
        await db.commit()
    
    await ctx.send("🗑️ Cleared campaign history for this channel!")

@bot.command()
async def roll(ctx):
    """Roll a d20"""
    roll_result = random.randint(1, 20)
    
    # Add some flair based on the roll
    if roll_result == 20:
        emoji = "🌟"
        message = "CRITICAL SUCCESS!"
    elif roll_result == 1:
        emoji = "💥"
        message = "Critical failure..."
    elif roll_result >= 15:
        emoji = "✨"
        message = "Great roll!"
    elif roll_result >= 10:
        emoji = "🎲"
        message = "Not bad!"
    else:
        emoji = "😅"
        message = "Could be better..."
    
    await ctx.send(f"{emoji} {ctx.author.display_name} rolled a **{roll_result}**! {message}")

@bot.command()
async def poll(ctx, *, question):
    """Create a poll with yes/no reactions"""
    if not question:
        await ctx.send("❌ Please provide a question for the poll!")
        return
    
    embed = discord.Embed(
        title="🗳️ Poll",
        description=question,
        color=discord.Color.blue()
    )
    embed.set_footer(text=f"Poll created by {ctx.author.display_name}")
    
    poll_message = await ctx.send(embed=embed)
    
    # Add reactions for voting
    await poll_message.add_reaction("✅")  # Yes
    await poll_message.add_reaction("❌")  # No
    await poll_message.add_reaction("🤷")  # Maybe/Unsure

# Web server for health checks and port binding (similar to Express.js example)
async def health_check(request):
    """Health check endpoint - equivalent to Express.js app.get('/')"""
    return web.Response(text="Hello World! Dog Bot is running!", status=200)

async def start_web_server():
    """Start the web server to ensure proper port binding"""
    app = web.Application()
    
    # Add routes - equivalent to Express.js app.get('/', ...)
    app.router.add_get('/', health_check)
    app.router.add_get('/health', health_check)  # Additional health endpoint
    
    # Get port from environment or default to 4000 (like Express.js example)
    port = int(os.environ.get('PORT', 4000))
    
    # Create and start the web server
    runner = web.AppRunner(app)
    await runner.setup()
    
    # Bind to all interfaces (0.0.0.0) and the specified port
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    
    # Log like Express.js example: "Example app listening on port ${port}"
    print(f"Dog Bot web server listening on port {port}")
    print(f"Health check available at: http://localhost:{port}/")
    
    return runner

async def main():
    """Main function to start both the Discord bot and web server"""
    web_runner = None
    try:
        # Initialize database first
        await init_database()
        print("✅ Chat history database initialized")
        
        # Start web server for port binding
        web_runner = await start_web_server()
        print("✅ Web server started successfully")
        
        # Start Discord bot
        if token:
            print("🤖 Starting Discord bot...")
            await bot.start(token)
        else:
            print("❌ No Discord token provided")
            
    except Exception as e:
        print(f"❌ Error starting services: {e}")
        if web_runner is not None:
            await web_runner.cleanup()
        raise

if __name__ == "__main__":
    print("🚀 Starting Dog Bot services...")
    asyncio.run(main())
