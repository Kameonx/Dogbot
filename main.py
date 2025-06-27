import discord
from discord.ext import commands
import logging
from dotenv import load_dotenv
import os
import asyncio
from aiohttp import web
import httpx
import json

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

# Venice AI Configuration
VENICE_API_URL = "https://api.venice.ai/api/v1/chat/completions"
VENICE_MODEL = "venice-uncensored"

async def get_ai_response(prompt: str, max_tokens: int = 500) -> str:
    """Get response from Venice AI"""
    if not venice_api_key:
        return "AI features are disabled. Please set VENICE_API_KEY environment variable."
    
    headers = {
        "Authorization": f"Bearer {venice_api_key}",
        "Content-Type": "application/json"
    }
    
    data = {
        "model": VENICE_MODEL,
        "messages": [
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

@bot.event
async def on_ready():
    if bot.user is not None:
        print(f"We are ready to go in, {bot.user.name}")
    else:
        print("We are ready to go in, but bot.user is None")

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
    embed.add_field(name="🎭 Roles", value="`!dogsrole` - Get Dogs role\n`!catsrole` - Get Cats role\n`!lizardsrole` - Get Lizards role\n`!removedogsrole` - Remove Dogs role\n`!removecatsrole` - Remove Cats role\n`!removelizardsrole` - Remove Lizards role", inline=False)
    embed.add_field(name="🗳️ Utility", value="`!poll <question>` - Create a poll", inline=False)
    embed.add_field(name="🤖 AI", value="`!ask <question>` - Ask AI anything\n`!chat <message>` - Chat with AI", inline=False)
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
async def poll(ctx, *, question):
    embed = discord.Embed(title="Poll", description=question, color=discord.Color.blue())
    poll_message = await ctx.send(embed=embed)
    await poll_message.add_reaction("👍")
    await poll_message.add_reaction("👎")

@bot.command()
async def ask(ctx, *, question):
    """Ask the Venice AI a question"""
    if not venice_api_key:
        await ctx.send("❌ AI features are disabled. Please contact the bot owner to set up Venice API key.")
        return
    
    # Show typing indicator
    async with ctx.typing():
        response = await get_ai_response(question, max_tokens=800)
    
    # Split long responses if needed
    if len(response) > 2000:
        chunks = [response[i:i+2000] for i in range(0, len(response), 2000)]
        for chunk in chunks:
            await ctx.send(chunk)
    else:
        await ctx.send(response)

@bot.command()
async def chat(ctx, *, message):
    """Have a casual chat with the Venice AI"""
    if not venice_api_key:
        await ctx.send("❌ AI features are disabled. Please contact the bot owner to set up Venice API key.")
        return
    
    # Add some personality to the prompt
    prompt = f"You are a friendly dog bot assistant in a Discord server. Respond naturally and helpfully to: {message}"
    
    async with ctx.typing():
        response = await get_ai_response(prompt, max_tokens=600)
    
    # Split long responses if needed  
    if len(response) > 2000:
        chunks = [response[i:i+2000] for i in range(0, len(response), 2000)]
        for chunk in chunks:
            await ctx.send(chunk)
    else:
        await ctx.send(response)

# Simple web server for Render
async def health_check(request):
    return web.Response(text="Bot is running!")

async def start_web_server():
    app = web.Application()
    app.router.add_get('/', health_check)
    
    port = int(os.environ.get('PORT', 10000))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    print(f"Web server started on port {port}")

async def main():
    # Start web server
    await start_web_server()
    
    # Start Discord bot
    if token:
        await bot.start(token)
    else:
        print("No token provided")

if __name__ == "__main__":
    asyncio.run(main())
