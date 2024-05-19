# MyHusqvarna - MacOS Menubar plugin

Displays information regarding your Husqvarna Robot mower in the MacOS menubar. Allows you to remotely control your Robot Mower as well.

![Imgur](https://i.imgur.com/u9WSbg7.png)

## Changelog: 

**Update 2024.05.19:**
- [X] Initial release - tested with Husqvarna 435 mower.
- [X] Currently requires a developer account on the husqvarna developer site.

## Licence: GPL v3

## Installation instructions: 

1. Ensure you have [xbar](https://github.com/matryer/xbar/releases/latest) installed.
2. Execute 'sudo pip install requests tinydb==3.9 keyring pathos pyobjc-framework-CoreLocation googlemaps' in Terminal.app
3. Copy [myhusqvarna.15m.py](myhusqvarna.15m.py) to your xbar plugins folder and chmod +x the file from your terminal in that folder
4. Run xbar
