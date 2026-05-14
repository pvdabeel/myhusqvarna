# MyHusqvarna - MacOS Menubar plugin

Displays information regarding your Husqvarna Robot mower in the MacOS menubar. Allows you to remotely control your Robot Mower as well.

![Imgur](https://i.imgur.com/u9WSbg7.png)

## Changelog:

**Update 2026.05.14 (v1.1):**
- [X] All API keys (Husqvarna client_id/secret + optional Google Maps/Geocoding) are now stored in the macOS Keychain — nothing sensitive lives in source any more.
- [X] Fixed broken Google Maps cache (was re-fetching both images on every refresh).
- [X] Parallel map + satellite requests, shared `requests` session with retries, proper timeouts.
- [X] Proactive OAuth token refresh based on `expires_in` instead of waiting for a 401.
- [X] Removed the 3 s `google.com` connectivity probe.
- [X] Defensive parsing of the mower payload (no crash on missing `positions`, `headlight`, etc.).
- [X] Refactored the duplicated xbar menu code (start/park sub-menus, cutting-height loop, logo dedup).
- [X] Portable shebang (`/usr/bin/env python3`) so Homebrew / pyenv / asdf users work out of the box.

**Update 2024.05.19 (v1.0):**
- [X] Initial release - tested with Husqvarna 435 mower.
- [X] Currently requires a developer account on the husqvarna developer site.

## Licence: GPL v3

## Installation instructions:

1. Ensure you have [xbar](https://github.com/matryer/xbar/releases/latest) installed.
2. Install the Python dependencies into the *same* Python interpreter that the shebang points at. The default shebang is MacPorts:

   ```
   sudo /opt/local/bin/pip3 install requests tinydb keyring googlemaps
   ```

   If you use Homebrew, pyenv, asdf, or any other Python, change the first line of `myhusqvarna.15m.py` to point at your `python3` (e.g. `#!/opt/homebrew/bin/python3`) and install the same packages with the matching `pip3`. The script itself only uses Python 3.6+ features.
3. Copy [myhusqvarna.15m.py](myhusqvarna.15m.py) to your xbar plugins folder and `chmod +x` the file from your terminal.
4. Run xbar — the menubar entry will show a *Login to Husqvarna* link. Click it and you'll be prompted in Terminal for:
   - your Husqvarna `client_id` and `client_secret` (create one at the [Husqvarna developer portal](https://developer.husqvarnagroup.cloud/)),
   - your Google Static Maps API key (optional — leave blank to disable the map image),
   - your Google Geocoding API key (optional — can be the same key as above if both APIs are enabled; leave blank to disable address lookup).

   All four values are stored in the macOS Keychain under the service name `myhusqvarna-xbar`. You can update the Google keys later via *Settings → Update Google API keys* in the menu, or sign out and re-login via *Settings → Sign out & re-login*.
