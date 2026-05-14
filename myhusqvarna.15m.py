#!/usr/bin/env PYTHONIOENCODING=UTF-8 /opt/local/bin/python3
# -*- coding: utf-8 -*-
#
# <xbar.title>MyHusqvarna</xbar.title>
# <xbar.version>v1.1</xbar.version>
# <xbar.author>pvdabeel@mac.com</xbar.author>
# <xbar.author.github>pvdabeel</xbar.author.github>
# <xbar.desc>Control your Husqvarna Lawn mower from the MacOS menubar</xbar.desc>
# <xbar.dependencies>python</xbar.dependencies>
#
# Licence: GPL v3
#
# Installation:
#   /opt/local/bin/pip3 install requests tinydb keyring googlemaps
#   # (or substitute the pip for whichever python3 you pin the shebang to)
#
# The shebang above is the MacPorts Python path. If you use Homebrew, pyenv
# or asdf, change the shebang to point at that python — for example:
#   #!/opt/homebrew/bin/python3
#   #!/Users/<you>/.pyenv/shims/python3
# The script only uses Python 3.6+ features, so any modern Python works.
#
# Ensure xbar is installed (https://github.com/matryer/xbar/releases/latest),
# copy this file into your xbar plugins folder, and chmod +x it.
# On first launch you'll be prompted for your Husqvarna client_id / client_secret
# and (optionally) Google Maps Static + Geocoding API keys. All four are stored
# in the macOS Keychain — nothing sensitive is kept in this source file.

import base64
import concurrent.futures as cf
import datetime
import getpass
import os
import sys
import time
from os.path import expanduser

import keyring
import requests
from requests.adapters import HTTPAdapter

try:
    # urllib3 >= 2
    from urllib3.util.retry import Retry
except ImportError:  # pragma: no cover - very old urllib3
    from requests.packages.urllib3.util.retry import Retry  # type: ignore

from tinydb import TinyDB, Query
from googlemaps import Client as googleclient


# --------------------------
# Configuration
# --------------------------

_DEBUG_ = False

# Set to False if you don't want mower location to be tracked locally.
_LOCATION_TRACKING_ = True

# Google Static Maps options
_MAP_SIZE_ = '800x600'
_MAP_ZOOM_ = '19'

# Single timeout used for every outbound HTTP call (seconds).
_HTTP_TIMEOUT_ = 8

# Round lat/lon to this many decimals when keying caches. ~5 decimals == ~1 m,
# which keeps the map cache useful even when the mower drifts a few cm between
# readings.
_COORD_PRECISION_ = 5

# Keyring service name (also used for backward-compat with existing installs).
KEYRING_SERVICE = "myhusqvarna-xbar"

# Husqvarna API endpoints
AUTH_ENDPOINT = "https://api.authentication.husqvarnagroup.dev/v1/oauth2/token"
AUTOMOWER_CONNECT_ENDPOINT = "https://api.amc.husqvarna.dev/v1"

# Local state
home = expanduser("~")
state_dir = home + '/.state/myhusqvarna'
os.makedirs(state_dir, exist_ok=True)

cmd_path = os.path.realpath(__file__)

locationdb = TinyDB(state_dir + '/myhusqvarna-locations.json')
geolocdb = TinyDB(state_dir + '/myhusqvarna-geoloc.json')

# Dark mode flag set by xbar
DARK_MODE = os.getenv('XBARDarkMode', 'false') == 'true'


# --------------------------
# Keyring helpers
# --------------------------

def kr_get(key, default=None):
    try:
        return keyring.get_password(KEYRING_SERVICE, key) or default
    except Exception:
        return default


def kr_set(key, value):
    keyring.set_password(KEYRING_SERVICE, key, value)


# --------------------------
# Shared HTTP session (connection pooling + retries on transient 5xx)
# --------------------------

def _build_session():
    s = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=0.5,
        status_forcelist=(500, 502, 503, 504),
        allowed_methods=frozenset({"GET", "POST"}),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=4, pool_maxsize=4)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    return s


SESSION = _build_session()


# --------------------------
# Pretty-printers
# --------------------------

_MODE_LABELS = {
    "MAIN_AREA": "Main Area, scheduled",
    "SECONDARY_AREA": "Secondary Area, scheduled",
    "HOME": "Until further notice",
    "DEMO": "Demo",
    "UNKNOWN": "Unknown",
}

_ACTIVITY_LABELS = {
    "UNKNOWN": "Unknown",
    "NOT_APPLICABLE": "Paused",
    "MOWING": "Mowing",
    "GOING_HOME": "Going to charging station",
    "CHARGING": "Charging",
    "LEAVING": "Leaving charging station",
    "PARKED_IN_CS": "Parked in charging station",
    "STOPPED_IN_GARDEN": "Stopped in garden",
}

_STATE_LABELS = {
    "UNKNOWN": "Unknown",
    "NOT_APPLICABLE": "Not applicable",
    "PAUSED": "Paused",
    "IN_OPERATION": "In operation",
    "WAIT_UPDATING": "Awaiting update",
    "WAIT_POWER_UP": "Awaiting power up",
    "RESTRICTED": "Restricted",
    "OFF": "Powered off",
    "STOPPED": "Stopped",
    "ERROR": "Error",
    "FATAL_ERROR": "Fatal error",
    "ERROR_AT_POWER_UP": "Error during power up",
}


def _humanize(value):
    return str(value).replace("_", " ").title() if value else "Unknown"


def pretty_print_mode(mode):
    return _MODE_LABELS.get(mode) or _humanize(mode)


def pretty_print_activity(activity):
    return _ACTIVITY_LABELS.get(activity) or _humanize(activity)


def pretty_print_state(state):
    return _STATE_LABELS.get(state) or _humanize(state)


def color_setting(current, option, color, info_color):
    return color if current == option else info_color


# --------------------------
# Google Maps helpers
# --------------------------

# Inlined Google "Snazzy"-style dark theme for the static maps API.
_DARK_STYLE = (
    '&style=feature:all|element:labels|visibility:on'
    '&style=feature:all|element:labels.text.fill|saturation:36|color:0x000000|lightness:40'
    '&style=feature:all|element:labels.text.stroke|visibility:on|color:0x000000|lightness:16'
    '&style=feature:all|element:labels.icon|visibility:off'
    '&style=feature:administrative|element:geometry.fill|color:0x000000|lightness:20'
    '&style=feature:administrative|element:geometry.stroke|color:0x000000|lightness:17|weight:1.2'
    '&style=feature:administrative.country|element:labels.text.fill|color:0x838383'
    '&style=feature:administrative.locality|element:labels.text.fill|color:0xc4c4c4'
    '&style=feature:administrative.neighborhood|element:labels.text.fill|color:0xaaaaaa'
    '&style=feature:landscape|element:geometry|color:0x000000|lightness:20'
    '&style=feature:poi|element:geometry|color:0x000000|lightness:21|visibility:on'
    '&style=feature:poi.business|element:geometry|visibility:on'
    '&style=feature:road.highway|element:geometry.fill|color:0x6e6e6e|lightness:0'
    '&style=feature:road.highway|element:geometry.stroke|visibility:off'
    '&style=feature:road.highway|element:labels.text.fill|color:0xffffff'
    '&style=feature:road.arterial|element:geometry|color:0x000000|lightness:18'
    '&style=feature:road.arterial|element:geometry.fill|color:0x575757'
    '&style=feature:road.arterial|element:labels.text.fill|color:0xffffff'
    '&style=feature:road.arterial|element:labels.text.stroke|color:0x2c2c2c'
    '&style=feature:road.local|element:geometry|color:0x000000|lightness:16'
    '&style=feature:road.local|element:labels.text.fill|color:0x999999'
    '&style=feature:transit|element:geometry|color:0x000000|lightness:19'
    '&style=feature:water|element:geometry|color:0x000000|lightness:17'
)


def _round_coord(value):
    try:
        return f"{round(float(value), _COORD_PRECISION_):.{_COORD_PRECISION_}f}"
    except (TypeError, ValueError):
        return str(value)


def _fetch_url(url):
    r = SESSION.get(url, timeout=_HTTP_TIMEOUT_)
    r.raise_for_status()
    return r.content


def retrieve_google_maps(latitude, longitude):
    """Return ``[b64_map, b64_satellite]`` for the given coordinates.

    Bytes are cached on disk as raw PNGs (binary), keyed by month and rounded
    coordinates, so the common case is a zero-network render.
    """
    maps_key = kr_get("google_maps_key")
    if not maps_key:
        return ["", ""]

    lat = _round_coord(latitude)
    lon = _round_coord(longitude)
    yyyymm = datetime.date.today().strftime("%Y%m")
    theme = 'dark' if DARK_MODE else 'light'
    base = f"{state_dir}/myhusqvarna-location"
    paths = (
        f"{base}-map-{theme}-{yyyymm}-{lat}-{lon}.png",
        f"{base}-sat-{yyyymm}-{lat}-{lon}.png",
    )

    try:
        if all(os.path.getsize(p) > 0 for p in paths):
            return [base64.b64encode(open(p, "rb").read()).decode("ascii") for p in paths]
    except OSError:
        pass

    style = _DARK_STYLE if DARK_MODE else ''
    common = (
        f"center={lat},{lon}"
        f"&key={maps_key}"
        f"&zoom={_MAP_ZOOM_}&size={_MAP_SIZE_}"
        f"&markers=color:red%7C{lat},{lon}"
    )
    urls = (
        f"https://maps.googleapis.com/maps/api/staticmap?{common}{style}",
        f"https://maps.googleapis.com/maps/api/staticmap?{common}&maptype=hybrid",
    )

    try:
        with cf.ThreadPoolExecutor(max_workers=2) as ex:
            blobs = list(ex.map(_fetch_url, urls))
    except requests.RequestException as e:
        if _DEBUG_:
            print(f"map fetch failed: {e}", file=sys.stderr)
        return ["", ""]

    for path, blob in zip(paths, blobs):
        try:
            with open(path, "wb") as f:
                f.write(blob)
        except OSError:
            pass

    return [base64.b64encode(b).decode("ascii") for b in blobs]


def retrieve_geo_loc(latitude, longitude):
    """Reverse-geocode ``(latitude, longitude)`` with a local TinyDB cache."""
    lat = _round_coord(latitude)
    lon = _round_coord(longitude)

    try:
        Q = Query()
        hits = geolocdb.search((Q.latitude == lat) & (Q.longitude == lon))
        if hits:
            return hits[-1]['geoloc']
    except Exception:
        pass

    geocode_key = kr_get("google_geocode_key")
    if not geocode_key:
        return f"{lat}, {lon}"

    try:
        gmaps = googleclient(geocode_key)
        result = gmaps.reverse_geocode((str(lat), str(lon)))
        if not result:
            return f"{lat}, {lon}"
        address = result[0]['formatted_address']
    except Exception as e:
        if _DEBUG_:
            print(f"geocode failed: {e}", file=sys.stderr)
        return f"{lat}, {lon}"

    if _LOCATION_TRACKING_:
        try:
            geolocdb.insert({'latitude': lat, 'longitude': lon, 'geoloc': address})
        except Exception:
            pass
    return address


# --------------------------
# Husqvarna API
# --------------------------

def get_oauth_token(client_id, client_secret):
    if not (client_id and client_secret):
        return None
    try:
        response = SESSION.post(
            AUTH_ENDPOINT,
            data={
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
            },
            timeout=_HTTP_TIMEOUT_,
        )
    except requests.RequestException as e:
        print(f"Error contacting Husqvarna auth: {e}")
        return None

    if response.status_code != 200:
        print("Error obtaining access token!")
        print(response.text)
        return None

    payload = response.json()
    token = payload.get("access_token")
    expires_in = int(payload.get("expires_in", 3600))
    if token:
        kr_set("access_token", token)
        kr_set("access_token_expiry", str(int(time.time()) + max(60, expires_in - 60)))
    return token


def refresh_oauth_token():
    return get_oauth_token(kr_get("client_id"), kr_get("client_secret"))


def get_valid_access_token():
    """Return a non-expired access token, refreshing proactively if needed."""
    token = kr_get("access_token")
    try:
        expiry = int(kr_get("access_token_expiry", "0"))
    except (TypeError, ValueError):
        expiry = 0
    if token and time.time() < expiry:
        return token
    return refresh_oauth_token()


def _api_headers(access_token, client_id, json_api=False):
    headers = {
        "Authorization-Provider": "husqvarna",
        "Authorization": f"Bearer {access_token}",
        "X-Api-Key": client_id,
    }
    if json_api:
        headers["Content-Type"] = "application/vnd.api+json"
    return headers


def get_mowers(access_token, client_id, _retried=False):
    try:
        response = SESSION.get(
            AUTOMOWER_CONNECT_ENDPOINT + "/mowers",
            headers=_api_headers(access_token, client_id),
            timeout=_HTTP_TIMEOUT_,
        )
    except requests.RequestException as e:
        if _DEBUG_:
            print(f"get_mowers network error: {e}", file=sys.stderr)
        raise

    if response.status_code == 200:
        return response.json().get("data", [])
    if response.status_code == 401 and not _retried:
        refreshed = refresh_oauth_token()
        if refreshed:
            return get_mowers(refreshed, client_id, _retried=True)
    return None


def mower_send_cmd(access_token, client_id, mower_id, command, arg=None):
    body = {'data': {'type': command}}
    if arg is not None:
        body['data']['attributes'] = {'duration': int(arg)}
    print(f"Executing command: {body}")
    try:
        response = SESSION.post(
            f"{AUTOMOWER_CONNECT_ENDPOINT}/mowers/{mower_id}/actions",
            headers=_api_headers(access_token, client_id, json_api=True),
            json=body,
            timeout=_HTTP_TIMEOUT_,
        )
    except requests.RequestException as e:
        print(f"Network error: {e}")
        return
    if response.status_code == 202:
        print("Command executed successfully")
    else:
        print(f"Failed to execute command. Response: {response.text} status: {response.status_code}")


def mower_update_settings(access_token, client_id, mower_id, setting, arg):
    body = {'data': {'type': 'settings', 'attributes': {setting: int(arg)}}}
    print(f"Updating settings: {body}")
    try:
        response = SESSION.post(
            f"{AUTOMOWER_CONNECT_ENDPOINT}/mowers/{mower_id}/settings",
            headers=_api_headers(access_token, client_id, json_api=True),
            json=body,
            timeout=_HTTP_TIMEOUT_,
        )
    except requests.RequestException as e:
        print(f"Network error: {e}")
        return
    if response.status_code == 202:
        print("Settings update successful")
    else:
        print(f"Failed to update settings. Response: {response.text} status: {response.status_code}")


# --------------------------
# xbar rendering helpers
# --------------------------

# Husqvarna logo (light variant — fill is recolored at runtime for dark mode).
_LOGO_SVG_B64 = (
    "PHN2ZyB2aWV3Qm94PSIwIDAgMzIgMzIiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2Z"
    "yIgd2lkdGg9IjgwJSIgYXNwZWN0LXJhdGlvPSd4TWluWU1pbic+PHBhdGggZmlsbD0iIzAwMDAwM"
    "CIgIGQ9Im04Ljc1MzkwNjIgNy4wMDE5NTMxYy0xLjIwMjA4OTMuMDE3MDIxMy0yLjIzODI5NTQuMT"
    "UyMjM0My0zLjA5OTYwOTMuNTIzNDM3NXMtMS42MzY3MTg4IDEuMTg3ODE1OS0xLjYzNjcxODggMi4"
    "xOTcyNjU2djQuMDQ0OTIxOGMtMS4yNDk3Njg4IDEuMTg4OTM5LTIuMDM1MTU2MiAyLjg2MTk3NS0y"
    "LjAzNTE1NjIgNC43MTQ4NDQgMCAzLjU4Nzk0NiAyLjkyOTYyOSA2LjUxNzU3OCA2LjUxNzU3ODEgN"
    "i41MTc1NzggMS4yNDg4NjkxIDAgMi4zODczODItLjM3NzIzMiAzLjM1NzQyMi0xaDkuOTUzMTI1Yy"
    "41NDk5NC42MDUxOTUgMS4zMzE3NTUgMSAyLjIwNzAzMSAxIC44NzUxMDQgMCAxLjY1Njg1NC0uMzk"
    "0MDE2IDIuMjA3MDMxLTFoLjY3NTc4MmMxLjY5MDc5NyAwIDMuMTE3MTg3LTEuMzUxNzg0IDMuMTE3"
    "MTg3LTMuMDM5MDYydi0yLjA2MDU0N2MwLTIuNjI4NDY4LTEuNzc4MjU4LTQuODIzNTEzLTQuMTY0M"
    "DYyLTYuNTQ2ODc1LTIuMzg1ODA1LTEuNzIzMzYzLTUuNDY5NzEyLTMuMDU0Mjc3OC04LjU1MDc4Mi"
    "0zLjk3MDcwMzUtMy4wODEwNjktLjkxNjQyNTctNi4xNDQ2NDktMS40MTQ5MDE5LTguNTQ4ODI3OC0"
    "xLjM4MDg1OTR6bS4wMjczNDM4IDJjMi4wOTU4MjEtLjAyOTY3NiA1LjAzMjI0Mi40Mjg2NzU4IDcu"
    "OTUxMTcyIDEuMjk2ODc0OSAyLjkxODkzLjg2ODE5OSA1LjgzNTAyMyAyLjE0ODYxMyA3Ljk0OTIxO"
    "SAzLjY3NTc4MSAxLjc0MTM2MiAxLjI1Nzg1NyAyLjg2NDQ1OCAyLjYyODE3MiAzLjIxMDkzNyA0Lj"
    "AyNTM5MWgtMTIuOTcyNjU2Yy0uMjYwNzk0LTMuMzUyNTc0LTMuMDAyNzgzLTYuMDM1MTU2LTYuNDE"
    "5OTIyLTYuMDM1MTU2LS44Nzg3MDIgMC0xLjcxNjA1MTkuMTc4MDMxLTIuNDgyNDIxOS40OTYwOTR2"
    "LTIuNzM4MjgxOGMwLS4xMzc4MDAxLS4wMjM0NTItLjE2NDkyNTguNDI3NzM0NC0uMzU5Mzc1LjQ1M"
    "TE4NjEtLjE5NDQ0OSAxLjI4ODAyNy0uMzQ2NDkgMi4zMzU5Mzc1LS4zNjEzMjgxem0tLjI4MTI1ID"
    "QuOTYyODkwOWMyLjUwNzA3IDAgNC41MTc1NzggMi4wMTA1MSA0LjUxNzU3OCA0LjUxNzU3OHMtMi4"
    "wMTA1MDggNC41MTc1NzgtNC41MTc1NzggNC41MTc1NzhjLTIuNTA3MDY5NSAwLTQuNTE3NTc4MS0y"
    "LjAxMDUxLTQuNTE3NTc4MS00LjUxNzU3OHMyLjAxMDUwODYtNC41MTc1NzggNC41MTc1NzgxLTQuN"
    "TE3NTc4em0wIDMuNTE3NTc4YTEgMSAwIDAgMCAwIDIgMSAxIDAgMCAwIDAtMnptNi4yMDg5ODQgMi"
    "41MTc1NzhoMTMuMzA4NTk0di45NjA5MzhjMCAuNTY0NzIxLS40Njc5ODUgMS4wMzkwNjItMS4xMTc"
    "xODcgMS4wMzkwNjJoLTEzLjA0NDkyMmMuMzgzODA5LS42MDc3MDYuNjc1NDc3LTEuMjgxMzQuODUz"
    "NTE1LTJ6Ii8+PC9zdmc+Cg=="
)


def _logo_for_mode():
    svg = base64.b64decode(_LOGO_SVG_B64).decode("utf-8")
    if DARK_MODE:
        svg = svg.replace('fill="#000000"', 'fill="#ffffff"')
    return base64.b64encode(svg.encode("utf-8")).decode("ascii")


def app_print_logo():
    print(f"|image={_logo_for_mode()}")


def xbar_action(label, mower_id, command, arg=None, depth=1, color=None):
    """Emit one xbar menu line that re-invokes this script with command args."""
    indent = "-" * (2 * depth)
    arg_part = f" param3={arg}" if arg is not None else ""
    color_part = f" color={color}" if color else ""
    print(
        f'{indent}{label}| refresh=true terminal=true '
        f'shell="{cmd_path}" param1="{mower_id}" param2="{command}"{arg_part}{color_part}'
    )


# Durations (minutes) offered in the "Start" sub-menu.
_DURATIONS = (30, 60, 120, 180, 360, 480)


def emit_start_menu(mower_id, color, include_resume):
    print(f"--Start  | color={color}")
    if include_resume:
        xbar_action("Resume schedule", mower_id, "ResumeSchedule", depth=2, color=color)
    xbar_action("Until further Notice", mower_id, "Start", 480, depth=2, color=color)
    print(f"----For a number of minutes| color={color}")
    for minutes in _DURATIONS:
        xbar_action(str(minutes), mower_id, "Start", minutes, depth=3, color=color)


def emit_park_menu(mower_id, color):
    print(f"--Park  | color={color}")
    xbar_action("Until further notice", mower_id, "ParkUntilFurtherNotice", depth=2, color=color)
    xbar_action("Until next scheduled run", mower_id, "ParkUntilNextSchedule", depth=2, color=color)


# --------------------------
# init() — interactive credentials setup
# --------------------------

def _prompt_secret(label, key):
    current = kr_get(key, "")
    hint = ""
    if current:
        hint = f" (press Enter to keep current: …{current[-4:]})"
    print(f"{label}{hint}:")
    value = getpass.getpass()
    return value or current


def init():
    print("MyHusqvarna setup — all values are stored in macOS Keychain.\n")
    client_id = _prompt_secret("Husqvarna client_id", "client_id")
    client_secret = _prompt_secret("Husqvarna client_secret", "client_secret")

    print("\nGoogle API keys are optional. Leave blank to disable maps/address lookup.")
    maps_key = _prompt_secret(
        "Google Static Maps API key (for the map image)", "google_maps_key"
    )
    geocode_key = _prompt_secret(
        "Google Geocoding API key (for reverse address lookup) "
        "(can be the same key if both APIs are enabled on it)",
        "google_geocode_key",
    )

    token = get_oauth_token(client_id, client_secret)
    if not token:
        print("Could not obtain an access token from Husqvarna — credentials may be wrong.")
        time.sleep(1)
        return

    kr_set("client_id", client_id)
    kr_set("client_secret", client_secret)
    if maps_key:
        kr_set("google_maps_key", maps_key)
    if geocode_key:
        kr_set("google_geocode_key", geocode_key)

    print("\nCredentials stored in macOS Keychain.")
    time.sleep(1)


def setup_keys():
    """Re-set just the Google API keys (no Husqvarna re-login)."""
    print("Update Google API keys stored in the macOS Keychain.\n")
    maps_key = _prompt_secret(
        "Google Static Maps API key (for the map image)", "google_maps_key"
    )
    geocode_key = _prompt_secret(
        "Google Geocoding API key (for reverse address lookup)",
        "google_geocode_key",
    )
    if maps_key:
        kr_set("google_maps_key", maps_key)
    if geocode_key:
        kr_set("google_geocode_key", geocode_key)
    print("\nDone. You can close this window.")
    time.sleep(1)


def emit_settings_menu(color):
    print(f"Settings | color={color}")
    print(
        f'--Update Google API keys | refresh=true terminal=true '
        f'shell="{cmd_path}" param1="keys" color={color}'
    )
    print(
        f'--Sign out & re-login | refresh=true terminal=true '
        f'shell="{cmd_path}" param1="init" color={color}'
    )


# --------------------------
# Menu rendering
# --------------------------

def _get(d, *path, default=None):
    """Safely walk a nested dict/list, returning ``default`` if anything is missing."""
    for key in path:
        if d is None:
            return default
        try:
            d = d[key]
        except (KeyError, IndexError, TypeError):
            return default
    return d if d is not None else default


def render_mower(mower, color, info_color, debug=False):
    mower_id = mower.get('id', '')
    mower_name = _get(mower, 'attributes', 'system', 'name', default='Unknown')
    mower_battery = _get(mower, 'attributes', 'battery', 'batteryPercent', default='?')
    mower_mode = _get(mower, 'attributes', 'mower', 'mode', default='UNKNOWN')
    mower_activity = _get(mower, 'attributes', 'mower', 'activity', default='UNKNOWN')
    mower_connected = _get(mower, 'attributes', 'metadata', 'connected', default=False)
    status_ts = _get(mower, 'attributes', 'metadata', 'statusTimestamp')
    if status_ts:
        try:
            mower_humantime = (
                datetime.datetime.fromtimestamp(float(status_ts) / 1000.0)
                .astimezone()
                .strftime("%Y-%m-%d %H:%M:%S %Z")
            )
        except (TypeError, ValueError):
            mower_humantime = "Unknown"
    else:
        mower_humantime = "Unknown"

    mower_latitude = _get(mower, 'attributes', 'positions', 0, 'latitude')
    mower_longitude = _get(mower, 'attributes', 'positions', 0, 'longitude')
    mower_cuttingheight = _get(mower, 'attributes', 'settings', 'cuttingHeight', default='?')
    mower_headlight = _get(mower, 'attributes', 'settings', 'headlight', 'mode', default='UNKNOWN')

    if debug:
        print(f'>>> Mower Id:\n{mower_id}\n')
        print(f'>>> Mower Name:\n{mower_name}\n')
        print(f'>>> Mower Battery:\n{mower_battery}\n')
        print(f'>>> Mower Mode:\n{mower_mode}\n')
        print(f'>>> Mower Activity:\n{mower_activity}\n')
        print(f'>>> Mower Connected:\n{mower_connected}\n')
        print(f'>>> Mower Humantime:\n{mower_humantime}\n')
        print(f'>>> Mower Latitude:\n{mower_latitude}\n')
        print(f'>>> Mower Longitude:\n{mower_longitude}\n')
        print(f'>>> Mower Cutting Height:\n{mower_cuttingheight}\n')
        print(f'>>> Mower Headlight Mode:\n{mower_headlight}\n')
        return

    # MOWER STATUS MENU
    print('---')
    print(f'Mower:\t\t\t\t{mower_name} | color={color}')
    print(f'Battery:\t\t\t\t{mower_battery}% | color={color}')
    print('---')
    print(f'Connected:\t\t\t{mower_humantime} | color={color}')
    print('---')
    print(f'Cutting Height:\t\t{mower_cuttingheight} cm | color={color}')
    for h in range(2, 9):
        xbar_action(
            f'{h} cm', mower_id, 'CuttingHeight', h, depth=1,
            color=color_setting(mower_cuttingheight, h, color, info_color),
        )

    print(f'Activity:\t\t\t\t{pretty_print_activity(mower_activity)} | color={color}')
    if mower_activity == 'MOWING':
        xbar_action('Pause', mower_id, 'Pause', depth=1, color=color)
        emit_park_menu(mower_id, color)
    elif mower_activity == 'PARKED_IN_CS':
        emit_start_menu(mower_id, color, include_resume=(mower_mode == 'HOME'))
    elif mower_activity == 'STOPPED_IN_GARDEN':
        emit_start_menu(mower_id, color, include_resume=True)
        emit_park_menu(mower_id, color)

    print(f'Mode:\t\t\t\t{pretty_print_mode(mower_mode)} | color={color}')
    print('---')

    # LOCATION + MAP MENU
    if mower_latitude is not None and mower_longitude is not None:
        address = retrieve_geo_loc(mower_latitude, mower_longitude)
        print(f'Location:\t\t\t\t{address}| color={color}')
        print(f'Lat:\t\t\t\t\t{mower_latitude}| color={color}')
        print(f'Lon:\t\t\t\t\t{mower_longitude}| color={color}')
        print('---')

        _, sat_b64 = retrieve_google_maps(str(mower_latitude), str(mower_longitude))
        if sat_b64:
            print(
                f'|image={sat_b64} '
                f'href="https://maps.google.com?q={mower_latitude},{mower_longitude}" '
                f'color={color}'
            )
            print('---')


# --------------------------
# Main entry point
# --------------------------

def _login_link(color):
    print(
        f'Login to Husqvarna | refresh=true terminal=true '
        f'shell="{cmd_path}" param1="init" color={color}'
    )


def main(argv):
    if 'init' in argv:
        init()
        return
    if 'keys' in argv:
        setup_keys()
        return

    color = '#FFFFFE' if DARK_MODE else '#00000E'
    info_color = '#C0C0C0' if DARK_MODE else '#616161'

    client_id = kr_get("client_id")
    client_secret = kr_get("client_secret")

    if not (client_id and client_secret):
        app_print_logo()
        _login_link(color)
        return

    access_token = get_valid_access_token()
    if not access_token:
        app_print_logo()
        _login_link(color)
        return

    # Fetch mowers — a network/transport error is treated as "no internet";
    # an auth/permission failure (None) is treated as needing re-login.
    try:
        mowers_data = get_mowers(access_token, client_id)
    except requests.RequestException as e:
        app_print_logo()
        print(f'No internet connection | refresh=true color={color}')
        if _DEBUG_:
            print(f'-- {e} | color={color}')
        return

    if mowers_data is None:
        app_print_logo()
        _login_link(color)
        return

    # If invoked with a command for a specific mower, execute and exit.
    if len(argv) > 1 and 'debug' not in argv and argv[1] != 'init':
        if len(argv) < 3:
            return
        target_id, command = argv[1], argv[2]
        third = argv[3] if len(argv) > 3 else None
        if command == 'Start' and third is not None:
            print(f'Command for mower {target_id}: {command} duration={third}')
            mower_send_cmd(access_token, client_id, target_id, command, third)
        elif command == 'CuttingHeight' and third is not None:
            print(f'Command for mower {target_id}: cuttingHeight={third}')
            mower_update_settings(access_token, client_id, target_id, 'cuttingHeight', third)
        else:
            print(f'Command for mower {target_id}: {command}')
            mower_send_cmd(access_token, client_id, target_id, command, None)
        return

    # Render the full menu.
    app_print_logo()
    debug = 'debug' in argv
    for mower in mowers_data:
        try:
            render_mower(mower, color, info_color, debug=debug)
        except Exception as e:
            print(f'---')
            print(f'Error rendering mower: {e} | color={color}')

    if not debug:
        emit_settings_menu(color)


if __name__ == "__main__":
    main(sys.argv)
