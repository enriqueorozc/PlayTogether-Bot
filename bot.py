import discord
import random
import time 

from steam import *
from discord.ext import commands
from discord import app_commands

DISCORD_TOKEN = "Enter your Discord bot token here"

# === DATABASE FUNCTIONS ===
def db_create(con):
  """Creates all the SQL databases (if they doesn't already exist)"""

  cur = con.cursor()
  cur.execute("""CREATE TABLE IF NOT EXISTS users (
    userID TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    steamID TEXT
  )""")

  cur.execute("""CREATE TABLE IF NOT EXISTS owned_games (
    steamID TEXT,
    appID TEXT,
    PRIMARY KEY (steamID, appID)
  )""")

  cur.execute("""CREATE TABLE IF NOT EXISTS game_info (
    appID TEXT PRIMARY KEY,
    multiplayer BOOLEAN DEFAULT 0,
    name TEXT NOT NULL,
    header TEXT NOT NULL
  )""")

  con.commit()

def db_initialize(con, members, bot_id):
  """Adds all the members of a guild into the users database"""

  cur = con.cursor()
  for member in members:
    if (member.bot or member.id == bot_id): continue
    cur.execute("""INSERT OR IGNORE INTO users (userID, name)
      VALUES (?, ?)""", (member.id, member.name))
    
  con.commit()

def db_steamID_inuse(con, steamID):
  """Checks if the steamID is currently in use by another Discord user"""

  cur = con.cursor()
  cur.execute("SELECT userID FROM users WHERE steamID = ?", (steamID,))
  result = cur.fetchone()

  return result is not None

def db_same_steamID(con, userID, steamID):
  """Checks if the user's is attempting to reenter the same steamID"""

  cur = con.cursor()
  cur.execute("SELECT steamID FROM users WHERE userID = ?", (userID,))
  result = cur.fetchone()

  return result is not None and result[0] == steamID

def db_add_user_games(con, steamID, games):
  """Adds the user's owned games into the owned_games database"""

  cur = con.cursor()
  cur.execute("DELETE FROM owned_games WHERE steamID = ?", (steamID,))
  cur.executemany(
    "INSERT INTO owned_games (steamID, appID) VALUES (?, ?)",
    [(steamID, str(id)) for id in games]
  )

  con.commit()

def db_get_user_games(cur, steamID):
  """Returns a set of the appIDs owned by the steamID (user)"""

  cur.execute("SELECT appID FROM owned_games WHERE steamID = ?", (steamID, ))
  rows = cur.fetchall()

  return set(row[0] for row in rows)

def db_add_steamID(con, userID, steamID):
  """Links a SteamID64 to Discord User"""

  cur = con.cursor()
  cur.execute("UPDATE users SET steamID = ? WHERE userID = ?", (steamID, userID))
  con.commit()

# === DISCORD BOT SETUP === 
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix='.', intents=intents)

# === BOT EVENTS === 
@bot.event
async def on_ready():
  con = sqlite3.connect(DB_FILE)
  db_create(con)
  for guild in bot.guilds:
    db_initialize(con, guild.members, bot.user.id)
  con.close()

  try:
    await bot.tree.sync()
  except:
    return None
  
@bot.event
async def on_guild_join(guild):
  con = sqlite3.connect(DB_FILE)
  db_initialize(con, guild.members, bot.user.id)
  con.close()

@bot.event
async def on_member_join(member):
  if member.bot: return
  con = sqlite3.connect(DB_FILE)
  cur = con.cursor()
  cur.execute("""INSERT OR IGNORE INTO users (userID, name) 
    VALUES (?, ?)""", (member.id, member.name))
  con.commit()
  con.close()

# === BOT SLASH COMMANDS ===
@bot.tree.command(name="add_id", description="Enter your Steam profile URL")
async def add_steam_id(interaction: discord.Interaction, url: str):
  """Enters the users valid Steam URL into the SQL database"""

  if interaction.user.bot:
    message = "Bots cannot use this command"
    await interaction.response.send_message(message) 
    return
  
  statusID, steamID = parse_steam_url(url)

  # --- Error Handling ---

  if statusID == URLParseStatus.INVALID_URL:
    message = (
      "Invalid URL format. Please make sure your URL is in one of the following formats:\n"
      "```"
      "Steam vanity url: https://steamcommunity.com/id/yourCustomID\n\n"
      "Steam profile url: https://steamcommunity.com/profiles/yourSteamID64"
      "```"
    )
    await interaction.response.send_message(message)
    return

  elif statusID == URLParseStatus.NOT_FOUND:
    message = "No Steam user was found with that URL."
    await interaction.response.send_message(message)
    return

  elif statusID == URLParseStatus.API_ERROR:
    message = "Trouble reaching the Steam API, please try again later."
    await interaction.response.send_message(message) 
    return
  
  # --- Duplicate User ---
  con = sqlite3.connect(DB_FILE)

  sameID = db_same_steamID(con, interaction.user.id, steamID)
  if sameID:
    message = ("You already have this steamID associated with your account. "
      "If you want to refresh your library list, please use the /refresh command.")
    await interaction.response.send_message(message)
    return
  
  inUse = db_steamID_inuse(con, steamID)
  if inUse:
    message = ("This steamID is already associated with another account.")
    await interaction.response.send_message(message)
    return
  
  # --- Owned Games Data ---
  statusProfile, games = get_owned_games(steamID)

  if statusProfile == AccountType.API_ERROR:
    message = "Trouble reaching the Steam API, please try again later."
    await interaction.response.send_message(message) 
    return

  elif statusProfile == AccountType.PRIVATE:
    message = "This account's game library is private. Please set to public."
    await interaction.response.send_message(message) 
    return

  statusUser, userData = get_profile_info(steamID)

  if statusUser == URLParseStatus.API_ERROR:
    message = "Trouble reaching the Steam API, please try again later."
    await interaction.response.send_message(message) 
    return
  
  # --- Successful Requests --- 
  embed = discord.Embed(
    title=f"{userData['personaname']}",
    description="Successfully added your Steam library",
    color=discord.Color.dark_blue()
  )
  embed.set_thumbnail(url=userData['avatarmedium'])

  db_add_user_games(con, steamID, games)
  db_add_steamID(con, interaction.user.id, steamID)
  con.close()

  await interaction.response.send_message(embed=embed)

@bot.tree.command(name="refresh", description="Refreshes a user's game library on Steam")
async def refresh(interaction: discord.Interaction):
  "Updates the users owned games (if they're in the database)"

  if interaction.user.bot:
    message = "Bots cannot use this command"
    await interaction.response.send_message(message) 
    return
  
  con = sqlite3.connect(DB_FILE)
  cur = con.cursor()

  cur.execute("SELECT steamID FROM users WHERE userID = ?", (interaction.user.id,))
  res = cur.fetchone()

  if res is None:
    message = "You haven't added your Steam profile. Please use the /add_id command first."
    await interaction.response.send_message(message)
    return
  
  # --- Owned Games Data ---
  statusProfile, games = get_owned_games(res[0])

  if statusProfile == AccountType.API_ERROR:
    message = "Trouble reaching the Steam API, please try again later."
    await interaction.response.send_message(message) 
    return

  db_add_user_games(con, res[0], games)
  message = "Successfully updated your Steam library."
  await interaction.response.send_message(message)


@bot.tree.command(name="game", description="Returns a random multiplayer game")
async def game(
  interaction: discord.Interaction,
  user1: discord.Member,
  user2: discord.Member,
  user3: discord.Member = None,
  user4: discord.Member = None,
  user5: discord.Member = None,
  user6: discord.Member = None,
  user7: discord.Member = None,
  user8: discord.Member = None,
  user9: discord.Member = None,
  user10: discord.Member = None
):
  """Returns a random shared multiplayer game between all the users"""
  
  # --- User Type Handling ---
  users = [user1, user2, user3, user4, user5,
    user6, user7, user8, user9, user10]
  
  if any(user.bot for user in users if user is not None):
    await interaction.response.send_message("A bot was detected as a user.")
    return
  
  actualUsers = list(user for user in users if user is not None)
  
  if len(actualUsers) != len(set(actualUsers)):
    await interaction.response.send_message("Duplicate users detected.")
    return
  
  con = sqlite3.connect(DB_FILE)
  cur = con.cursor()

  unregisteredUsers = list()
  for user in actualUsers:
    cur.execute("SELECT * FROM users WHERE userID = ? AND steamID IS NULL", (user.id,))
    if cur.fetchone():
      unregisteredUsers.append(user)

  if len(unregisteredUsers) != 0:
    message = "These users haven't added their SteamID:\n```"
    message += ", ".join(user.name for user in unregisteredUsers)
    message += "```"
    await interaction.response.send_message(message)
    return

  # --- Shared Games ---
  await interaction.response.defer()

  allGames = list()
  for user in actualUsers:
    cur.execute("SELECT steamID FROM users WHERE userID = ?", (user.id,))
    allGames.append(db_get_user_games(cur, cur.fetchone()[0]))

  sharedGames = set.intersection(*allGames) if allGames else set()

  # --- Shared Multiplayer Games ---
  statusGame, sharedMulti = get_multiplayer_games(sharedGames)

  if statusGame == URLParseStatus.API_ERROR:
    message = "Trouble reaching the Steam API, please try again later."
    await interaction.followup.send(message)
    return
  
  if len(sharedMulti) == 0:
    message = "There are no shared multiplayer games between these users."
    await interaction.followup.send(message)
    return
  
  seed = int(time.time() * 1000)
  random.seed(seed)

  randomGame = random.choice(sharedMulti)

  embed = discord.Embed(
    title=f"{randomGame['name']}",
    description="Here's your randomly chosen game, enjoy!",
    color=discord.Color.dark_blue()
  )
  embed.set_image(url=randomGame['header_image'])

  await interaction.followup.send(embed=embed)

bot.run(DISCORD_TOKEN)