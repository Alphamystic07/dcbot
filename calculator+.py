import discord
import random
import string
import asyncio
import os
import json
import re
import math
from discord.ext import commands, tasks
from discord.ui import Button, View
from discord import app_commands
from datetime import timedelta
from datetime import datetime
from fractions import Fraction
from sympy import sqrt, Rational

# bot token
TOKEN = os.getenv('DISCORD_TOKEN')
if TOKEN is None:
    print('ERROR: Environment variable is not correctly set')
    exit()

# Intents
intents = discord.Intents.all()
bot = commands.Bot(command_prefix='/', intents=intents)

# Define file paths
SERVER_OPTIONS_FILE = 'server_options.json'
CHALLENGES_FILE = 'challenges.json'

# Load server options or initialize if not found
if os.path.exists(SERVER_OPTIONS_FILE):
    with open(SERVER_OPTIONS_FILE, 'r') as f:
        server_options = json.load(f)
else:
    server_options = {"rr_role_id": None}
    with open(SERVER_OPTIONS_FILE, 'w') as f:
        json.dump(server_options, f)

# Load challenges or initialize if not found
if os.path.exists(CHALLENGES_FILE):
    with open(CHALLENGES_FILE, 'r') as f:
        challenges = json.load(f)
else:
    challenges = []
    with open(CHALLENGES_FILE, 'w') as f:
        json.dump(challenges, f)

# Load player challenges or initialize if not found
player_challenges = {}


# Sync the command tree
@bot.event
async def on_ready():
    # Sync commands to ensure they're registered
    await bot.tree.sync()  # Re-sync the current commands
    print(f"Logged in as {bot.user}")


# calculator command
@bot.tree.command(name='calculator', description='Performs complex calculations')
@app_commands.describe(equation='calculation (i.e. 2+sqrt(16)-pi^2)')
async def calculator(interaction: discord.Interaction, equation: str):
    # Replace commas with periods for decimals
    equation = equation.replace(',', '.')

    # Replace 'x' or 'X' with '*' for multiplication
    equation = equation.replace('x', '*').replace('X', '*')

    # Replace '^' with '**' for exponentiation
    equation = equation.replace('^', '**')

    # Add support for constants and functions
    allowed_names = {
        'sqrt': lambda x: sqrt(x),  # Use sympy for simplification of square roots
        'pi': math.pi,
        'e': math.e,
        'Fraction': Fraction,  # Support fractions for better precision
        'Rational': Rational,  # Use sympy for fraction simplification
    }

    # Safely evaluate the mathematical expression
    try:
        # Use sympy for enhanced math simplification
        result = eval(equation, {"__builtins__": None}, allowed_names)

        # Handle result formatting
        if isinstance(result, float):
            # Check if rounding is needed (i.e., decimal places are unnecessary)
            if result.is_integer():
                result = int(result)
            else:
                # Detect repeating decimals or overly long decimals
                result = round(result, 12)  # Limit to 12 decimal places for rounding precision
        elif isinstance(result, Fraction):
            # Simplify fractions and provide both fraction and decimal representations
            result = f"{result} ≈ {float(result)}"
        elif isinstance(result, Rational):
            # Simplify square roots and rational numbers using sympy
            result = f"{result} ≈ {float(result)}"

    except (SyntaxError, NameError, ZeroDivisionError, ValueError):
        await interaction.response.send_message("Invalid input. Please enter a valid expression.")
        return

    # Send the result back to the user in 'equation = result' format
    await interaction.response.send_message(f"{equation} = {result}")


# Purge command
@bot.tree.command(name="purge", description="Purge messages from a channel or thread")
@app_commands.describe(
    amount='Max 1000 messages',
    bot_messages='Should bot messages be deleted? (true/false)',
    user_messages='Should user messages be deleted? (true/false)'
)
async def purge(interaction: discord.Interaction, amount: int, bot_messages: bool = False, user_messages: bool = True):
    # Ensure only mods+ can use this command
    if not interaction.user.guild_permissions.manage_messages:
        await interaction.response.send_message("You do not have permission to use this command.", ephemeral=True)
        return

    # Defer the response since the command may take time to execute
    await interaction.response.defer(ephemeral=True)

    # Check if the amount is greater than 0 and not greater than 1000
    if amount <= 0 or amount > 1000:
        await interaction.followup.send("Please specify a number between 1 and 1000.")
        return

    channel = interaction.channel
    messages_to_delete = []
    old_messages = []

    # Fetch the message history and categorize messages based on age
    async for message in channel.history(limit=amount):
        if (message.author.bot and bot_messages) or (not message.author.bot and user_messages):
            if (discord.utils.utcnow() - message.created_at).days < 14:  # Bulk delete eligible
                messages_to_delete.append(message)
            else:
                old_messages.append(message)

    deleted_messages = 0

    # Step 1: Bulk delete messages that are less than 14 days old
    if messages_to_delete:
        try:
            await channel.delete_messages(messages_to_delete)
            deleted_messages += len(messages_to_delete)
        except discord.errors.HTTPException as e:
            await interaction.followup.send(f"Error deleting recent messages: {str(e)}")
            return

    # Step 2: Delete older messages (older than 14 days) individually
    if old_messages:
        for message in old_messages:
            try:
                await message.delete()
                deleted_messages += 1
                await asyncio.sleep(1)  # Add delay to avoid rate limits
            except discord.errors.HTTPException as e:
                await interaction.followup.send(f"Error deleting old messages: {str(e)}")
                return

    # Send feedback to the user
    if deleted_messages == 0:
        await interaction.followup.send("No messages were deleted based on the criteria provided.")
    else:
        await interaction.followup.send(f"Deleted {deleted_messages} messages.")


# slowmode
# Helper function to parse time string and convert to seconds
def parse_time_string(time_str):
    time_str = time_str.lower()  # Make case insensitive
    if time_str == "reset":
        return 0, 0  # Immediate reset to 0
    match = re.match(r'(\d+)(s|min|h|d|w|m|permanent)', time_str)

    if not match:
        return None, None

    value, unit = int(match.group(1)), match.group(2)

    # Convert value to seconds based on the unit
    if unit == 's':
        return value, value  # Seconds
    elif unit == 'min':
        return value, value * 60  # Minutes to seconds
    elif unit == 'h':
        return value, value * 3600  # Hours to seconds
    elif unit == 'd':
        return value, value * 86400  # Days to seconds
    elif unit == 'w':
        return value, value * 604800  # Weeks to seconds
    elif unit == 'm':  # Assuming a month is 30 days
        return value, value * 2592000  # 30 days (months) to seconds
    elif unit == 'permanent':
        return value, None  # Permanent means no reset

    return None, None


# Command to set slowmode
@bot.tree.command(name='slowmode', description='Set a slowmode with a time limit to reset it')
@app_commands.describe(
    slowmode_duration='Slowmode duration in seconds (s), minutes (min), hours (h), days (d), weeks (w), months (m), or "reset" to remove slowmode.',
    reset_time='Time after which slowmode will reset to the previous state (same units as slowmode duration). Use "permanent" for no reset.'
)
async def slowmode(interaction: discord.Interaction, slowmode_duration: str, reset_time: str = 'permanent'):
    # Ensure user has permission
    if not interaction.user.guild_permissions.manage_channels:
        await interaction.response.send_message("You do not have permission to change slowmode.", ephemeral=True)
        return

    channel = interaction.channel  # Get the current channel

    # Parse the slowmode duration and reset time
    slowmode_value, slowmode_seconds = parse_time_string(slowmode_duration)
    reset_value, reset_seconds = parse_time_string(reset_time)

    if slowmode_value is None or (reset_time != "permanent" and reset_value is None):
        await interaction.response.send_message("Invalid time format. Use s, min, h, d, w, m, 'reset', or 'permanent'.",
                                                ephemeral=True)
        return

    # Save the current slowmode state (in seconds)
    previous_slowmode = channel.slowmode_delay

    try:
        # Set the new slowmode in seconds (or reset it to 0 if "reset" was entered)
        await channel.edit(slowmode_delay=slowmode_seconds)
        if slowmode_seconds == 0:
            await interaction.response.send_message(f"Slowmode has been reset to 0 seconds (no slowmode).",
                                                    ephemeral=True)
        else:
            await interaction.response.send_message(f"Set slowmode to {slowmode_seconds} seconds.", ephemeral=True)

        # If not permanent, reset the slowmode after the specified time
        if reset_seconds:
            await asyncio.sleep(reset_seconds)
            await channel.edit(slowmode_delay=previous_slowmode)
            await interaction.followup.send(f"Slowmode has been reset to {previous_slowmode} seconds.", ephemeral=True)

    except discord.errors.HTTPException as e:
        await interaction.response.send_message(f"Failed to change slowmode: {str(e)}", ephemeral=True)


# Commands to play Russian Roulette
@bot.tree.command(name='setup_rr', description='Setup the role for Russian Roulette')
async def setup_rr(interaction: discord.Interaction, role: discord.Role):
    server_options["rr_role_id"] = role.id
    with open(SERVER_OPTIONS_FILE, 'w') as f:
        json.dump(server_options, f)
    await interaction.response.send_message(f"✅ Role for Russian Roulette set to {role.mention}")


@bot.tree.command(name='add_rr_challenge', description='Add a challenge for Russian Roulette')
async def add_rr_challenge(interaction: discord.Interaction, challenge: str):
    challenges.append(challenge)
    with open(CHALLENGES_FILE, 'w') as f:
        json.dump(challenges, f)
    await interaction.response.send_message(f"✅ Challenge added: {challenge}")


@bot.tree.command(name='view_rr_challenges', description='View all challenges for Russian Roulette')
async def view_rr_challenges(interaction: discord.Interaction):
    if challenges:
        await interaction.response.send_message("📝 Available Challenges:\n" + "\n".join(challenges))
    else:
        await interaction.response.send_message("❌ No challenges available.")


@bot.tree.command(name='clear_role', description='Clear the role of a user after completing a challenge')
async def clear_role(interaction: discord.Interaction, member: discord.Member):
    role_id = server_options["rr_role_id"]
    role = interaction.guild.get_role(role_id) if role_id else None
    if role and role in member.roles:
        await member.remove_roles(role)
        player_challenges.pop(member.id, None)  # Clear the player's challenge
        await interaction.response.send_message(f"✅ Cleared {role.mention} from {member.display_name}.")
    else:
        await interaction.response.send_message(f"❌ {member.display_name} does not have the role.")


@bot.tree.command(name='active_challenges', description='View your active challenges')
async def active_challenges(interaction: discord.Interaction):
    user_id = interaction.user.id
    if user_id in player_challenges:
        await interaction.response.send_message(f"📝 Your active challenge: {player_challenges[user_id]}")
    else:
        await interaction.response.send_message("❌ You have no active challenges.")


@bot.tree.command(name='russian_roulette', description='Play Russian Roulette')
async def russian_roulette(interaction: discord.Interaction):
    role_id = server_options["rr_role_id"]
    role = interaction.guild.get_role(role_id) if role_id else None
    bullet_player = interaction.user  # The user who invoked the command

    # Check if the user already has a challenge
    if bullet_player.id in player_challenges:
        await interaction.response.send_message(
            f"❌ You have an active challenge: {player_challenges[bullet_player.id]}. Complete it before playing.")
        return

    # Send the starting message and stop the "thinking" phase
    await interaction.response.defer(thinking=True)
    await interaction.followup.send(
        f"🎲 {bullet_player.display_name} played Russian Roulette!")  # Stops the "thinking" phase

    # Continue with the animation sequence
    await interaction.channel.send("🔄 Loading chamber...")
    await asyncio.sleep(1)

    await interaction.channel.send("🔄 Started the spin...")
    await asyncio.sleep(1)

    await interaction.channel.send("🔄 The chamber is spinning...")
    await asyncio.sleep(2)

    await interaction.channel.send("🔄 The chamber has stopped!")
    await asyncio.sleep(1)

    await interaction.channel.send(f"🔫 {bullet_player.display_name} points the gun and shoots...")

    # Determine if the user gets shot (2/6 chance of getting shot)
    shot = random.randint(1, 3) == 1  # 1 out of 3 chance of getting shot (2/6)

    if shot:
        if role:
            await bullet_player.add_roles(role)
            await interaction.channel.send(f"💥 {bullet_player.display_name} got shot! {role.mention}")
        else:
            await interaction.channel.send("❌ No role assigned for Russian Roulette.")
    else:
        await interaction.channel.send(
            f"✅ {bullet_player.display_name} is safe! No bullet fired.")  # Final result message

    # Challenge message after the result if shot
    if shot and challenges:
        challenge = random.choice(challenges)
        player_challenges[bullet_player.id] = challenge  # Save the player's challenge
        await interaction.channel.send(f"📜 Here is your challenge: {challenge}")


bot.run(TOKEN)