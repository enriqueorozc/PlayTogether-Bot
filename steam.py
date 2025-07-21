import requests
import sqlite3
import re

from enum import Enum

class URLParseStatus(Enum):
  SUCCESS = 0
  INVALID_URL = 1
  NOT_FOUND = 2
  API_ERROR = 3

class AccountType(Enum):
  PUBLIC = 0
  PRIVATE = 1
  API_ERROR = 2

DB_FILE = 'database.db'

# Regex Constants
STEAM_PROFILE_URL = re.compile(r"https?://steamcommunity\.com/profiles/(\d{17})/?")
STEAM_VANITY_URL = re.compile(r"https?://steamcommunity\.com/id/([\w.-]+)/?")

# Steam API Constants
PROFILE_URL = 'https://api.steampowered.com/ISteamUser/GetPlayerSummaries/v0002/'
VANITY_URL = 'https://api.steampowered.com/ISteamUser/ResolveVanityURL/v1/'
GAMES_URL = 'https://api.steampowered.com/IPlayerService/GetOwnedGames/v1/'
API_KEY = "Please enter your Steam Web API Key"

def parse_steam_url(url):
  """Returns a SteamID64 from a valid Steam profile URL"""

  profileMatch = STEAM_PROFILE_URL.fullmatch(url)
  vanityMatch = STEAM_VANITY_URL.fullmatch(url)

  if profileMatch:
    return (URLParseStatus.SUCCESS, profileMatch.group(1))
  
  if vanityMatch:
    try:
      params = {
        'key': API_KEY,
        'vanityurl': vanityMatch.group(1)
      }
      data = requests.get(VANITY_URL, params=params, timeout=3).json()

      if data['response']['success'] == 1:
        return (URLParseStatus.SUCCESS, data['response']['steamid'])
      else:
        return (URLParseStatus.NOT_FOUND, None)
    except:
      return (URLParseStatus.API_ERROR, None)
  
  return (URLParseStatus.INVALID_URL, None)

def get_profile_info(steamID):
  """Returns the data associated with a user's SteamID64"""

  params = {
    'key': API_KEY,
    'steamids': steamID
  }

  try:
    data = requests.get(PROFILE_URL, params=params, timeout=3).json()
    return (URLParseStatus.SUCCESS, data['response']['players'][0])
  except:
    return (URLParseStatus.API_ERROR, None)
  
def get_owned_games(steamID):
  """Return a list of all the user's owned games (id)"""

  params = {
    'key': API_KEY,
    'steamid': steamID,
    'include_played_free_games': True
  }

  try:
    data = requests.get(GAMES_URL, params=params).json()
    if "games" in data.get("response", {}):
      games = {game['appid'] for game in data['response']['games']}
      return (AccountType.PUBLIC, games)
    else:
      return (AccountType.PRIVATE, None)

  except:
    return (AccountType.API_ERROR, None)
  
def get_multiplayer_games(sharedGames):
  """Returns a list of the shared multiplayer games"""

  sharedMulti = list()
  con = sqlite3.connect(DB_FILE)
  cur = con.cursor()

  for appID in sharedGames:
    cur.execute("SELECT * FROM game_info WHERE appID = ?", (appID,))
    result = cur.fetchone()

    if result:
      if result[1]:
        sharedMulti.append({
          'name': result[2],
          'header_image': result[3]
        })

    else:
      INFO_URL = f'https://store.steampowered.com/api/appdetails?appids={appID}&l=en'
      try:
        result = requests.get(INFO_URL).json().get(appID)

        if not result or not result.get('success'): continue
      
        data = result.get('data')
        isMultiplayer = any(category['id'] == 1 for category in data.get('categories', []))

        cur.execute(
          "INSERT INTO game_info (appID, multiplayer, name, header) VALUES (?, ?, ?, ?)", 
          (
            appID,
            '1' if isMultiplayer else '0', 
            data.get('name', 'Unknown'),
            data.get('header_image', 'None Given')
          )
        )
        con.commit()

        if isMultiplayer:
          sharedMulti.append({
            'name': data.get('name', 'Unknown'),
            'header_image': data.get('header_image', 'None Given')
          })

      except:
        return (URLParseStatus.API_ERROR, None)
  con.close()
    
  return (URLParseStatus.SUCCESS, sharedMulti)