#!/usr/bin/env PYTHONIOENCODING=UTF-8 /opt/local/bin/python3
# -*- coding: utf-8 -*-
#
# <xbar.title>MyHusqvarna</xbar.title>
# <xbar.version>v1.0</xbar.version>
# <xbar.author>pvdabeel@mac.com</xbar.author>
# <xbar.author.github>pvdabeel</xbar.author.github>
# <xbar.desc>Control your Husqvarna Lawn mower from the MacOS menubar</xbar.desc>
# <xbar.dependencies>python</xbar.dependencies>
#
# Licence: GPL v3

# Installation instructions: 
# -------------------------- 
# Execute in terminal.app before running : 
#    sudo easy_install keyring
#    sudo easy_install pyobjc-framework-CoreLocation
#
# Ensure you have xbar installed https://github.com/matryer/xbar/releases/latest
# Copy this file to your xbar plugins folder and chmod +x the file from your terminal in that folder
# Run xbar

import requests
import json
import urllib
import datetime
import ast
import json
import sys
import datetime
import calendar
import base64
import math
import keyring                                  # Husqvarna access token is stored in OS X keychain
import getpass                                  # Getting password without showing chars in terminal.app
import time
import os
import subprocess
import requests
import binascii

import CoreLocation as cl

#from pyicloud   import PyiCloudService          # Icloud integration - schedule events in icloud agenda
from datetime   import date
from tinydb     import TinyDB                   # Keep track of location and husqvarna states
from os.path    import expanduser
from googlemaps import Client as googleclient   # Reverse lookup of addresses based on coordinates


_DEBUG_ = False 

# Disabled if you don't want your mower location to be tracked to a DB

_LOCATION_TRACKING_ = True
                                                                               
# Google map size                                                               
                                                                                
_MAP_SIZE_ = '800x600'     
_MAP_ZOOM_ = '19'

# Location where to store state files
home         = expanduser("~")
state_dir    = home+'/.state/myhusqvarna'

if not os.path.exists(state_dir):
    os.makedirs(state_dir)

# The full path to this file                                                    
                                                                                
cmd_path = os.path.realpath(__file__)      

# Location tracking database
locationdb = TinyDB(state_dir+'/myhusqvarna-locations.json')
geolocdb   = TinyDB(state_dir+'/myhusqvarna-geoloc.json')

# Nice ANSI colors
CEND    = '\33[0m'
CRED    = '\33[31m'
CGREEN  = '\33[32m'
CYELLOW = '\33[33m'
CBLUE   = '\33[36m'

# Support for OS X Dark Mode                                                    
DARK_MODE=True if os.getenv('XBARDarkMode','false') == 'true' else False  


# Replace with the Husqvarna API client ID and secret
MY_CLIENT_ID = ""
MY_CLIENT_SECRET = ""

try:
   MY_CLIENT_ID = keyring.get_password("myhusqvarna-xbar","client_id")
   MY_CLIENT_SECRET = keyring.get_password("myhusqvarna-xbar","client_secret")
except: 
   pass

# Set up the Authentication API endpoint for obtaining an access token
AUTH_ENDPOINT = "https://api.authentication.husqvarnagroup.dev/v1/oauth2/token"

# Set up the Automower Connect API endpoint
AUTOMOWER_CONNECT_ENDPOINT = "https://api.amc.husqvarna.dev/v1"


# Pretty print function MODE 

def pretty_print_mode(Mode):
   match Mode: 
      case "MAIN_AREA":
         return "Main Area, scheduled"
      case "SECONDARY_AREA":
         return "Secundary Area, scheduled"
      case "HOME":
         return "Until further notice"
      case "DEMO":
         return "Demo"
      case "UNKNOWN":
        return "Unknown"

# Pretty print function ACTIVITY

def pretty_print_activity(Activity):
   match Activity: 
      case "UNKNOWN":
         return "Unknown"
      case "NOT_APPLICABLE":
         return "Paused"
      case "MOWING":
         return "Mowing" 
      case "GOING_HOME":
         return "Going to charging station"
      case "CHARGING":
         return "Charging"
      case "LEAVING":
         return "Leaving charging station"
      case "PARKED_IN_CS":
         return "Parked in charging station"
      case "STOPPED_IN_GARDEN":
         return "Stopped in garden"

# Pretty print function STATE

def pretty_print_state(STATE):
   match STATE:
      case "UNKNOWN":
         return "Unknown"
      case "NOT_APPLICABLE":
         return "Now applicable"
      case "PAUSED":
         return "Paused"
      case "IN_OPERATION":
         return "In operation"
      case "WAIT_UPDATING":
         return "Awaiting update"
      case "WAIT_POWER_UP":
         return "Awaiting power up"
      case "RESTRICTED":
         return "Restricted"
      case "OFF":
         return "Powered off"
      case "STOPPED":
         return "Stopped"
      case "ERROR":
         return "Error"
      case "FATAL_ERROR":
         return "Fatal error"
      case "ERROR_AT_POWER_UP":
         return "Error during power up"

# Pretty print cutting height setting                                             
def color_setting(current,option,color,info_color):                             
    if (current == option):                                                     
        return color                                                            
    else:                                                                       
        return info_color  

# Function to retrieve goole map & sat images for a given location
def retrieve_google_maps(latitude,longitude):
    todayDate = datetime.date.today()
    try:
        with open(state_dir+'/myhusqvarna-location-map-'+todayDate.strftime("%Y%m")+'-'+latitude+'-'+longitude+'.png') as location_map:
            my_img1 = base64.b64encode(location_map.read()).decode('utf-8')  
            location_map.close()
        with open(state_dir+'/myhusqvarna-location-sat-'+todayDate.strftime("%Y%m")+'-'+latitude+'-'+longitude+'.png') as location_sat:
            my_img2 = base64.b64encode(location_sat.read()).decode('utf-8')   
            location_sat.close()
    except: 
        with open(state_dir+'/myhusqvarna-location-map-'+todayDate.strftime("%Y%m")+'-'+latitude+'-'+longitude+'.png','w') as location_map, open(state_dir+'/myhusqvarna-location-sat-'+todayDate.strftime("%Y%m")+'-'+latitude+'-'+longitude+'.png','w') as location_sat:
            my_google_key = '&key=AIzaSyBrgHowqRH-ewRCNrhAgmK7EtFsuZCdXwk'
            my_google_dark_style = ''
                
            if bool(DARK_MODE):
                my_google_dark_style = '&style=feature:all|element:labels|visibility:on&style=feature:all|element:labels.text.fill|saturation:36|color:0x000000|lightness:40&style=feature:all|element:labels.text.stroke|visibility:on|color:0x000000|lightness:16&style=feature:all|element:labels.icon|visibility:off&style=feature:administrative|element:geometry.fill|color:0x000000|lightness:20&style=feature:administrative|element:geometry.stroke|color:0x000000|lightness:17|weight:1.2&style=feature:administrative.country|element:labels.text.fill|color:0x838383&style=feature:administrative.locality|element:labels.text.fill|color:0xc4c4c4&style=feature:administrative.neighborhood|element:labels.text.fill|color:0xaaaaaa&style=feature:landscape|element:geometry|color:0x000000|lightness:20&style=feature:poi|element:geometry|color:0x000000|lightness:21|visibility:on&style=feature:poi.business|element:geometry|visibility:on&style=feature:road.highway|element:geometry.fill|color:0x6e6e6e|lightness:0&style=feature:road.highway|element:geometry.stroke|visibility:off&style=feature:road.highway|element:labels.text.fill|color:0xffffff&style=feature:road.arterial|element:geometry|color:0x000000|lightness:18&style=feature:road.arterial|element:geometry.fill|color:0x575757&style=feature:road.arterial|element:labels.text.fill|color:0xffffff&style=feature:road.arterial|element:labels.text.stroke|color:0x2c2c2c&style=feature:road.local|element:geometry|color:0x000000|lightness:16&style=feature:road.local|element:labels.text.fill|color:0x999999&style=feature:transit|element:geometry|color:0x000000|lightness:19&style=feature:water|element:geometry|color:0x000000|lightness:17'
       
            my_google_size = '&size='+_MAP_SIZE_
            my_google_zoom = '&zoom='+_MAP_ZOOM_
            my_url1 ='https://maps.googleapis.com/maps/api/staticmap?center='+latitude+','+longitude+my_google_key+my_google_dark_style+my_google_zoom+my_google_size+'&markers=color:red%7C'+latitude+','+longitude
            my_url2 ='https://maps.googleapis.com/maps/api/staticmap?center='+latitude+','+longitude+my_google_key+my_google_zoom+my_google_size+'&maptype=hybrid&markers=color:red%7C'+latitude+','+longitude
            s = requests.Session()
            my_cnt1 = s.get(my_url1).content
            my_cnt2 = s.get(my_url2).content
            my_img1 = base64.b64encode(my_cnt1).decode('utf-8')
            my_img2 = base64.b64encode(my_cnt2).decode('utf-8')
            location_map.write(my_img1)
            location_sat.write(my_img2)
            location_map.close()
            location_sat.close()
    return [my_img1,my_img2]

# Function to retrieve address for a given latitude and longitude
def retrieve_geo_loc(latitude,longitude):
    try:
        # First try cache
        result = geolocdb.search((Q.latitude==latitude) & (Q.longitude==longitude))[-1]['geoloc']
        return result['response']
    except:
        # Then try google 

        gmaps = googleclient('AIzaSyCtVR6-HQOVMYVGG6vOxWvPxjeggFz39mg')
        location_address = gmaps.reverse_geocode((str(latitude),str(longitude)))[0]['formatted_address']

        # Finally Update local cache
        if _LOCATION_TRACKING_:
            geolocdb.insert({'latitude':latitude,'longitude':longitude,'geoloc':location_address})
        return location_address


def get_oauth_token(client_id, client_secret):
    # Perform authorization code flow to obtain an access token
    data = {
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret
    }
    # Encode the request body using application/x-www-form-urlencoded
    encoded_data = urllib.parse.urlencode(data).encode("utf-8")

    # Set the Content-Type header to application/x-www-form-urlencoded
    headers = {"Content-Type": "application/x-www-form-urlencoded"}

    # Make the POST request to obtain an access token
    response = requests.post(AUTH_ENDPOINT, data=encoded_data, headers=headers)

    if response.status_code == 200:
        #print("Login succesful")
        #print(response.content)
        token_data = response.json()
        return token_data["access_token"]
    else:
        print("Error obtaining access token!")
        print(response.content)
        return None

def refresh_oauth_token():
    refreshed_access_token = get_oauth_token(MY_CLIENT_ID,MY_CLIENT_SECRET)
    if not (refreshed_access_token == None):
        #print("refreshing key")
        keyring.set_password("myhusqvarna-xbar","access_token",refreshed_access_token)
    return refreshed_access_token


def get_mowers(access_token,client_id):
    # Set the Authorization header with the correct format
    auth_header = {"Authorization-Provider": "husqvarna", "Authorization": f"Bearer {access_token}"}

    # Set the X-API-Key header with your API key
    api_key_header = {"X-Api-Key": client_id}

    # Make the GET request to retrieve a list of mowers
    response = requests.get(AUTOMOWER_CONNECT_ENDPOINT + "/mowers", headers={**auth_header, **api_key_header})

    if response.status_code == 200:
        mowers_data = response.json()["data"]
        return mowers_data
    elif response.status_code == 401:
        refreshed_access_token = refresh_oauth_token()
        if not (refreshed_access_token == None):
            return get_mowers(refreshed_access_token,client_id)
        app_print_logo()
        print('error - empty mower list')
        #print(response.text)
    else:
        app_print_logo()
        print('error - invalid credentials')    
        #print(response.text)
    return None


def mower_send_cmd(accessToken,client_id,mower_id,Command,Arg=None):
    if (Arg==None):
        json_args={'data':{'type':Command}}
    else: 
        json_args={'data':{'type':Command, 'attributes': {'duration' : int(Arg)}}}
    print ('Executing command: %s' % json_args)
    response = requests.post(AUTOMOWER_CONNECT_ENDPOINT + "/mowers/" + mower_id + "/actions",
                         headers={'Authorization': 'Bearer ' + accessToken,
                                 'X-Api-Key': client_id,
                                 'Authorization-Provider': 'husqvarna',
                                 'Content-Type': 'application/vnd.api+json'},
                         json=json_args)
    if (response.status_code == 202):
        print ('Command executed succesfull')
    else: 
        print ('Failed to execute command. Response: %s exited with status code: %s' % (response.text, response.status_code))

def mower_update_settings(accessToken,client_id,mower_id,Setting,Arg):
    json_args={'data':{'type':'settings', 'attributes': {Setting : int(Arg)}}}
    print ('Updating settings: %s' % json_args)
    response = requests.post(AUTOMOWER_CONNECT_ENDPOINT + "/mowers/" + mower_id + "/settings",
                         headers={'Authorization': 'Bearer ' + accessToken,
                                 'X-Api-Key': client_id,
                                 'Authorization-Provider': 'husqvarna',
                                 'Content-Type': 'application/vnd.api+json'},
                         json=json_args)
    if (response.status_code == 202):
        print ('Settings update succesfull')
    else: 
        print ('Failed to update settings. Response: %s exited with status code: %s' % (response.text, response.status_code))




def app_print_logo():
    if bool(DARK_MODE):
        print ('|image=PHN2ZyB2aWV3Qm94PSIwIDAgMzIgMzIiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyIgd2lkdGg9IjgwJSIgYXNwZWN0LXJhdGlvPSd4TWluWU1pbic+PHBhdGggZmlsbD0iI2ZmZmZmZiIgIGQ9Im04Ljc1MzkwNjIgNy4wMDE5NTMxYy0xLjIwMjA4OTMuMDE3MDIxMy0yLjIzODI5NTQuMTUyMjM0My0zLjA5OTYwOTMuNTIzNDM3NXMtMS42MzY3MTg4IDEuMTg3ODE1OS0xLjYzNjcxODggMi4xOTcyNjU2djQuMDQ0OTIxOGMtMS4yNDk3Njg4IDEuMTg4OTM5LTIuMDM1MTU2MiAyLjg2MTk3NS0yLjAzNTE1NjIgNC43MTQ4NDQgMCAzLjU4Nzk0NiAyLjkyOTYyOSA2LjUxNzU3OCA2LjUxNzU3ODEgNi41MTc1NzggMS4yNDg4NjkxIDAgMi4zODczODItLjM3NzIzMiAzLjM1NzQyMi0xaDkuOTUzMTI1Yy41NDk5NC42MDUxOTUgMS4zMzE3NTUgMSAyLjIwNzAzMSAxIC44NzUxMDQgMCAxLjY1Njg1NC0uMzk0MDE2IDIuMjA3MDMxLTFoLjY3NTc4MmMxLjY5MDc5NyAwIDMuMTE3MTg3LTEuMzUxNzg0IDMuMTE3MTg3LTMuMDM5MDYydi0yLjA2MDU0N2MwLTIuNjI4NDY4LTEuNzc4MjU4LTQuODIzNTEzLTQuMTY0MDYyLTYuNTQ2ODc1LTIuMzg1ODA1LTEuNzIzMzYzLTUuNDY5NzEyLTMuMDU0Mjc3OC04LjU1MDc4Mi0zLjk3MDcwMzUtMy4wODEwNjktLjkxNjQyNTctNi4xNDQ2NDktMS40MTQ5MDE5LTguNTQ4ODI3OC0xLjM4MDg1OTR6bS4wMjczNDM4IDJjMi4wOTU4MjEtLjAyOTY3NiA1LjAzMjI0Mi40Mjg2NzU4IDcuOTUxMTcyIDEuMjk2ODc0OSAyLjkxODkzLjg2ODE5OSA1LjgzNTAyMyAyLjE0ODYxMyA3Ljk0OTIxOSAzLjY3NTc4MSAxLjc0MTM2MiAxLjI1Nzg1NyAyLjg2NDQ1OCAyLjYyODE3MiAzLjIxMDkzNyA0LjAyNTM5MWgtMTIuOTcyNjU2Yy0uMjYwNzk0LTMuMzUyNTc0LTMuMDAyNzgzLTYuMDM1MTU2LTYuNDE5OTIyLTYuMDM1MTU2LS44Nzg3MDIgMC0xLjcxNjA1MTkuMTc4MDMxLTIuNDgyNDIxOS40OTYwOTR2LTIuNzM4MjgxOGMwLS4xMzc4MDAxLS4wMjM0NTItLjE2NDkyNTguNDI3NzM0NC0uMzU5Mzc1LjQ1MTE4NjEtLjE5NDQ0OSAxLjI4ODAyNy0uMzQ2NDkgMi4zMzU5Mzc1LS4zNjEzMjgxem0tLjI4MTI1IDQuOTYyODkwOWMyLjUwNzA3IDAgNC41MTc1NzggMi4wMTA1MSA0LjUxNzU3OCA0LjUxNzU3OHMtMi4wMTA1MDggNC41MTc1NzgtNC41MTc1NzggNC41MTc1NzhjLTIuNTA3MDY5NSAwLTQuNTE3NTc4MS0yLjAxMDUxLTQuNTE3NTc4MS00LjUxNzU3OHMyLjAxMDUwODYtNC41MTc1NzggNC41MTc1NzgxLTQuNTE3NTc4em0wIDMuNTE3NTc4YTEgMSAwIDAgMCAwIDIgMSAxIDAgMCAwIDAtMnptNi4yMDg5ODQgMi41MTc1NzhoMTMuMzA4NTk0di45NjA5MzhjMCAuNTY0NzIxLS40Njc5ODUgMS4wMzkwNjItMS4xMTcxODcgMS4wMzkwNjJoLTEzLjA0NDkyMmMuMzgzODA5LS42MDc3MDYuNjc1NDc3LTEuMjgxMzQuODUzNTE1LTJ6Ii8+PC9zdmc+Cg==')
    else:
        print ('|image=PHN2ZyB2aWV3Qm94PSIwIDAgMzIgMzIiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyIgd2lkdGg9IjgwJSIgYXNwZWN0LXJhdGlvPSd4TWluWU1pbic+PHBhdGggZmlsbD0iIzAwMDAwMCIgIGQ9Im04Ljc1MzkwNjIgNy4wMDE5NTMxYy0xLjIwMjA4OTMuMDE3MDIxMy0yLjIzODI5NTQuMTUyMjM0My0zLjA5OTYwOTMuNTIzNDM3NXMtMS42MzY3MTg4IDEuMTg3ODE1OS0xLjYzNjcxODggMi4xOTcyNjU2djQuMDQ0OTIxOGMtMS4yNDk3Njg4IDEuMTg4OTM5LTIuMDM1MTU2MiAyLjg2MTk3NS0yLjAzNTE1NjIgNC43MTQ4NDQgMCAzLjU4Nzk0NiAyLjkyOTYyOSA2LjUxNzU3OCA2LjUxNzU3ODEgNi41MTc1NzggMS4yNDg4NjkxIDAgMi4zODczODItLjM3NzIzMiAzLjM1NzQyMi0xaDkuOTUzMTI1Yy41NDk5NC42MDUxOTUgMS4zMzE3NTUgMSAyLjIwNzAzMSAxIC44NzUxMDQgMCAxLjY1Njg1NC0uMzk0MDE2IDIuMjA3MDMxLTFoLjY3NTc4MmMxLjY5MDc5NyAwIDMuMTE3MTg3LTEuMzUxNzg0IDMuMTE3MTg3LTMuMDM5MDYydi0yLjA2MDU0N2MwLTIuNjI4NDY4LTEuNzc4MjU4LTQuODIzNTEzLTQuMTY0MDYyLTYuNTQ2ODc1LTIuMzg1ODA1LTEuNzIzMzYzLTUuNDY5NzEyLTMuMDU0Mjc3OC04LjU1MDc4Mi0zLjk3MDcwMzUtMy4wODEwNjktLjkxNjQyNTctNi4xNDQ2NDktMS40MTQ5MDE5LTguNTQ4ODI3OC0xLjM4MDg1OTR6bS4wMjczNDM4IDJjMi4wOTU4MjEtLjAyOTY3NiA1LjAzMjI0Mi40Mjg2NzU4IDcuOTUxMTcyIDEuMjk2ODc0OSAyLjkxODkzLjg2ODE5OSA1LjgzNTAyMyAyLjE0ODYxMyA3Ljk0OTIxOSAzLjY3NTc4MSAxLjc0MTM2MiAxLjI1Nzg1NyAyLjg2NDQ1OCAyLjYyODE3MiAzLjIxMDkzNyA0LjAyNTM5MWgtMTIuOTcyNjU2Yy0uMjYwNzk0LTMuMzUyNTc0LTMuMDAyNzgzLTYuMDM1MTU2LTYuNDE5OTIyLTYuMDM1MTU2LS44Nzg3MDIgMC0xLjcxNjA1MTkuMTc4MDMxLTIuNDgyNDIxOS40OTYwOTR2LTIuNzM4MjgxOGMwLS4xMzc4MDAxLS4wMjM0NTItLjE2NDkyNTguNDI3NzM0NC0uMzU5Mzc1LjQ1MTE4NjEtLjE5NDQ0OSAxLjI4ODAyNy0uMzQ2NDkgMi4zMzU5Mzc1LS4zNjEzMjgxem0tLjI4MTI1IDQuOTYyODkwOWMyLjUwNzA3IDAgNC41MTc1NzggMi4wMTA1MSA0LjUxNzU3OCA0LjUxNzU3OHMtMi4wMTA1MDggNC41MTc1NzgtNC41MTc1NzggNC41MTc1NzhjLTIuNTA3MDY5NSAwLTQuNTE3NTc4MS0yLjAxMDUxLTQuNTE3NTc4MS00LjUxNzU3OHMyLjAxMDUwODYtNC41MTc1NzggNC41MTc1NzgxLTQuNTE3NTc4em0wIDMuNTE3NTc4YTEgMSAwIDAgMCAwIDIgMSAxIDAgMCAwIDAtMnptNi4yMDg5ODQgMi41MTc1NzhoMTMuMzA4NTk0di45NjA5MzhjMCAuNTY0NzIxLS40Njc5ODUgMS4wMzkwNjItMS4xMTcxODcgMS4wMzkwNjJoLTEzLjA0NDkyMmMuMzgzODA5LS42MDc3MDYuNjc1NDc3LTEuMjgxMzQuODUzNTE1LTJ6Ii8+PC9zdmc+Cg==')

# --------------------------
# The init function
# --------------------------

# The init function: Called to store your client_id and client_secret in OS X Keychain on first launch
def init():
    # Here we do the setup
    # Store access_token in OS X keychain on first run
    print ('Enter your Husqvarna client_id:')
    print ('Hint: '+str(MY_CLIENT_ID))
    init_client_id = getpass.getpass()
    if (init_client_id == ""): 
        init_client_id = MY_CLIENT_ID
    print ('Enter your Husqvarna client_secret:')
    print ('Hint: '+str(MY_CLIENT_SECRET))
    init_client_secret = getpass.getpass()
    if (init_client_secret == ""):
        init_client_secret = MY_CLIENT_SECRET
    init_access_token = None

    try:
        init_access_token = get_oauth_token(init_client_id,init_client_secret)
    except HTTPError as e:
        print ('Error contacting Husqvarna servers. Try again later.')
        print (e)
        time.sleep(0.5)
        return
    except URLError as e:
        print ('Error: Unable to connect. Check your connection settings.')
        print (e)
        return
    except Exception as e:
        print ('Error: Could not get an access token from Husqvarna. Try again later.')
        print (e)
        return
    keyring.set_password("myhusqvarna-xbar","client_id",init_client_id)
    keyring.set_password("myhusqvarna-xbar","client_secret",init_client_secret)
    keyring.set_password("myhusqvarna-xbar","access_token",init_access_token)
    init_client_secret = ''
    init_client_id = ''



# --------------------------
# The main function
# --------------------------

def main(argv):

    # CASE 1: init was called 
    if 'init' in argv:
       init()
       return
  

    # CASE 2: init was not called, keyring not initialized
    if bool(DARK_MODE):                                                         
        color = '#FFFFFE'                                                       
        info_color = '#C0C0C0'                                                  
    else:                                                                       
        color = '#00000E'                                                       
        info_color = '#616161'  

    CLIENT_ID = keyring.get_password("myhusqvarna-xbar","client_id")
    CLIENT_SECRET = keyring.get_password("myhusqvarna-xbar","client_secret")
    ACCESS_TOKEN = keyring.get_password("myhusqvarna-xbar","access_token")

    if not ACCESS_TOKEN:   
       # restart in terminal calling init 
       app_print_logo()
       print ('Login to Husqvarna | refresh=true terminal=true shell="%s" param1="%s" color=%s' % (cmd_path, 'init', color))
       return

    # CASE 3a: check for internet connectivity
    try:
       requests.get('http://www.google.com',timeout=3)
    except:
       app_print_logo()
       print ('No internet connection | refresh=true terminal=false shell="%s" param1="%s" color=%s' % (cmd_path, 'true', color))
       return


    # CASE 3b: init was not called, keyring initialized, no connection (access code not valid)
    try:
       mowers_data = get_mowers(ACCESS_TOKEN,CLIENT_ID)
    except Exception as e:
       print (e)
       app_print_logo()
       print ('Login to Husqvarna | refresh=true terminal=true shell="%s" param1="%s" color=%s' % (cmd_path, 'init', color))
       return


    # CASE 4: all ok, specific command for a specific bike received
    if (len(sys.argv) > 1) and not ("debug" in sys.argv):
        if (sys.argv[2]=='Start'):
            print ('Command received for mower with id: %s, executing command: %s with duration argument: %s' % (sys.argv[1],sys.argv[2],sys.argv[3]))
            mower_send_cmd(ACCESS_TOKEN,CLIENT_ID,sys.argv[1],sys.argv[2],sys.argv[3])
        elif (sys.argv[2]=='CuttingHeight'):
            print ('Command received for mower with id: %s, updating settings: %s with argument: %s' % (sys.argv[1],sys.argv[2],sys.argv[3]))
            mower_update_settings(ACCESS_TOKEN,CLIENT_ID,sys.argv[1],'cuttingHeight',sys.argv[3])
        else:
            print ('Command received for mower with id: %s, executing command: %s' % (sys.argv[1],sys.argv[2]))
            mower_send_cmd(ACCESS_TOKEN,CLIENT_ID,sys.argv[1],sys.argv[2],None)
        return


    # CASE 5: all ok, all other cases
    app_print_logo()
    prefix = ''

    try:
        for mower in mowers_data:
            mower_id = mower['id']
            mower_name = mower['attributes']['system']['name']
            mower_battery = mower['attributes']['battery']['batteryPercent']
            mower_mode = mower['attributes']['mower']['mode']
            mower_activity = mower['attributes']['mower']['activity']
            mower_connected = mower['attributes']['metadata']['connected']
            mower_epochtime = datetime.datetime.fromtimestamp(float(mower['attributes']['metadata']['statusTimestamp'])/1000.0).astimezone()
            mower_humantime = mower_epochtime.strftime("%Y-%m-%d %H:%M:%S %Z")
            mower_latitude = mower['attributes']['positions'][0]['latitude']
            mower_longitude = mower['attributes']['positions'][0]['longitude']
            mower_cuttingheight = mower['attributes']['settings']['cuttingHeight']
            mower_headlight = mower['attributes']['settings']['headlight']['mode']

            #if _LOCATION_TRACKING_:                                                     
            #    locationdb.insert({'date':str(datetime.datetime.now()),'mower_name':mower_name,'mower_battery':mower_battery,'mower_mode':mower_mode,'mower_activity':mower_activity,'mower_connected':mower_connected,'mower_epochtime':mower_epochtime,'mower_latitude':mower_latitude,'mower_longitude':mower_longitude,'mower_cuttingheight':mower_cuttingheight,'mower_headlight':mower_headlight})

            # --------------------------------------------------
            # MOWER STATUS MENU
            # --------------------------------------------------

            if 'debug' in argv:
                print ('>>> Mower Id:\n%s\n'                % mower_id)
                print ('>>> Mower Name:\n%s\n'              % mower_name)
                print ('>>> Mower Battery:\n%s\n'           % mower_battery)
                print ('>>> Mower Mode:\n%s\n'              % mower_mode)
                print ('>>> Mower Activity:\n%s\n'          % mower_activity)
                print ('>>> Mower Connected:\n%s\n'         % mower_connected)
                print ('>>> Mower Humantime:\n%s\n'         % mower_humantime)
                print ('>>> Mower Latitude:\n%s\n'          % mower_latitude)
                print ('>>> Mower Longitude:\n%s\n'         % mower_longitude)
                print ('>>> Mower Cutting Height:\n%s\n'    % mower_cuttingheight)
                print ('>>> Mower Headlight Mode:\n%s\n'    % mower_headlight)
                continue

                                                                              
            print ('%s---' % prefix)                                                    
            print ('%sMower:\t\t\t\t%s | color=%s' % (prefix, mower_name, color))   
            print ('%sBattery:\t\t\t\t%s%% | color=%s' % (prefix, mower_battery, color))
            print ('%s---' % prefix)                                                    
            print ('%sConnected:\t\t\t%s | color=%s' % (prefix, mower_humantime, color))
            print ('%s---' % prefix)                                                    
            print ('%sCutting Height:\t\t%s cm | color=%s' % (prefix, mower_cuttingheight, color))
            for cuttingheight in range(2,9):
                print ('%s--%s cm| refresh=true terminal=true shell="%s" param1="%s" param2="%s" param3=%s color=%s' % (prefix,cuttingheight,cmd_path,mower_id,"CuttingHeight",cuttingheight,color_setting(mower_cuttingheight,cuttingheight,color,info_color)))
            
            print ('%sActivity:\t\t\t\t%s | color=%s' % (prefix, pretty_print_activity(mower_activity), color))
            if (mower_activity == "MOWING") :
                print ('%s--Pause | refresh=true terminal=true shell="%s" param1="%s" param2="%s" color=%s' % (prefix,cmd_path,mower_id,"Pause",color))
                print ('%s--Park  | color=%s' % (prefix, color))
                print ('%s----Until further notice| refresh=true terminal=true shell="%s" param1="%s" param2="%s" color=%s' % (prefix,cmd_path,mower_id,"ParkUntilFurtherNotice",color))
                print ('%s----Until next scheduled run| refresh=true terminal=true shell="%s" param1="%s" param2="%s" color=%s' % (prefix,cmd_path,mower_id,"ParkUntilNextSchedule",color))
            if (mower_activity == "PARKED_IN_CS"):
                print ('%s--Start  | color=%s' % (prefix, color))
                if (mower_mode == "HOME"):
                    print ('%s----Resume schedule| refresh=true terminal=true shell="%s" param1="%s" param2="%s" color=%s' % (prefix,cmd_path,mower_id,"ResumeSchedule",color))
                print ('%s----Until further Notice| refresh=true terminal=true shell="%s" param1="%s" param2="%s" param3=%s color=%s' % (prefix,cmd_path,mower_id,"Start",480,color))
                print ('%s----For a number of minutes| color=%s' % (prefix,color))
                print ('%s------30| refresh=true terminal=true shell="%s" param1="%s" param2="%s" param3=%s color=%s' % (prefix,cmd_path,mower_id,"Start",30,color))
                print ('%s------60| refresh=true terminal=true shell="%s" param1="%s" param2="%s" param3=%s color=%s' % (prefix,cmd_path,mower_id,"Start",60,color))
                print ('%s------120| refresh=true terminal=true shell="%s" param1="%s" param2="%s" param3=%s color=%s' % (prefix,cmd_path,mower_id,"Start",120,color))
                print ('%s------180| refresh=true terminal=true shell="%s" param1="%s" param2="%s" param3=%s color=%s' % (prefix,cmd_path,mower_id,"Start",180,color))
                print ('%s------360| refresh=true terminal=true shell="%s" param1="%s" param2="%s" param3=%s color=%s' % (prefix,cmd_path,mower_id,"Start",360,color))
                print ('%s------480| refresh=true terminal=true shell="%s" param1="%s" param2="%s" param3=%s color=%s' % (prefix,cmd_path,mower_id,"Start",480,color))
            if (mower_activity == "STOPPED_IN_GARDEN"):
                print ('%s--Start  | color=%s' % (prefix, color))
                print ('%s----Resume schedule| refresh=true terminal=true shell="%s" param1="%s" param2="%s" color=%s' % (prefix,cmd_path,mower_id,"ResumeSchedule",color))
                print ('%s----Until further Notice| refresh=true terminal=true shell="%s" param1="%s" param2="%s" param3="%s" color=%s' % (prefix,cmd_path,mower_id,"Start",480,color))
                print ('%s----For a number of minutes| color=%s' % (prefix,color))
                print ('%s------30| refresh=true terminal=true shell="%s" param1="%s" param2="%s" param3=%s color=%s' % (prefix,cmd_path,mower_id,"Start",30,color))
                print ('%s------60| refresh=true terminal=true shell="%s" param1="%s" param2="%s" param3=%s color=%s' % (prefix,cmd_path,mower_id,"Start",60,color))
                print ('%s------120| refresh=true terminal=true shell="%s" param1="%s" param2="%s" param3=%s color=%s' % (prefix,cmd_path,mower_id,"Start",120,color))
                print ('%s------180| refresh=true terminal=true shell="%s" param1="%s" param2="%s" param3=%s color=%s' % (prefix,cmd_path,mower_id,"Start",180,color))
                print ('%s------360| refresh=true terminal=true shell="%s" param1="%s" param2="%s" param3=%s color=%s' % (prefix,cmd_path,mower_id,"Start",360,color))
                print ('%s------480| refresh=true terminal=true shell="%s" param1="%s" param2="%s" param3=%s color=%s' % (prefix,cmd_path,mower_id,"Start",480,color))
                print ('%s--Park  | color=%s' % (prefix, color))
                print ('%s----Until further notice| refresh=true terminal=true shell="%s" param1="%s" param2="%s" color=%s' % (prefix,cmd_path,mower_id,"ParkUntilFurtherNotice",color))
                print ('%s----Until next scheduled run| refresh=true terminal=true shell="%s" param1="%s" param2="%s" color=%s' % (prefix,cmd_path,mower_id,"ParkUntilNextSchedule",color))

            print ('%sMode:\t\t\t\t%s | color=%s' % (prefix, pretty_print_mode(mower_mode), color))
            print ('%s---' % prefix)                                                    

            # --------------------------------------------------                        
            # LOCATION MENU                                                             
            # --------------------------------------------------                        

            mower_location_address = retrieve_geo_loc(mower_latitude,mower_longitude)

            print ('%sLocation:\t\t\t\t%s| color=%s' % (prefix, mower_location_address, color))
            print ('%sLat:\t\t\t\t\t%s| color=%s' % (prefix, mower_latitude, color))
            print ('%sLon:\t\t\t\t\t%s| color=%s' % (prefix, mower_longitude, color))
            print ('%s---' % prefix)                                                    
 
                                                                                
            # --------------------------------------------------                        
            # VEHICLE MAP MENU                                                          
            # --------------------------------------------------                        
                                                                                
            google_maps = retrieve_google_maps(str(mower_latitude),str(mower_longitude))
            mower_location_map = google_maps[0]                                       
            mower_location_sat = google_maps[1]                                       
                                                                                
            #print ('%s|image=%s href="https://maps.google.com?q=%s,%s" color=%s' % (prefix, mower_location_map, mower_latitude, mower_longitude, color))
            print ('%s|image=%s href="https://maps.google.com?q=%s,%s" color=%s' % (prefix, mower_location_sat, mower_latitude, mower_longitude, color))
            print ('%s---' % prefix)  

    except:
        return


if __name__ == "__main__":
    main(sys.argv)
