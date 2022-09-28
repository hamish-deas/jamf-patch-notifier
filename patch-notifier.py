from slack_sdk import WebClient
from dotenv import load_dotenv
import sys
import requests
import base64
import xmltodict
import json
import os
import time
import re
import argparse
import logging

jamf_url = "https://YOUR_JAMF_URL.com/"
url = jamf_url+"JSSResource/"

computers = "computers"
patch_titles = "patchsoftwaretitles"
patch_reports = "patch_reports/patchsoftwaretitleid/"

excluded_apps = ()

load_dotenv()

class SlackMessageFormattingRegular:
    def __init__(self, fname, hostname, patches):
        # Initialise variables
        self.fname = fname
        self.patches = patches
        self.hostname = hostname
        self.slack_text = ''
        self.instructions = ''

    def __repr__(self):
        # All apps we don't want to push messaging for
        for self.patch in self.patches:
            if 'Apple macOS' in self.patch["name"]:
                continue
            
            self.slack_text += f'    - {self.patch["name"]} -> {self.patch  ["newver"]}\n'     

            # Instructions for updating apps which are picked up by Patch Management but aren't updated through Self Service/Munki/whatever platform.
            if 'Apple Safari' in self.patch["name"]:
                self.instructions += f'To update Safari, go to System Preferences > Software Update > More Info..., check that Safari is ticked, and then click "Install Now". '

            if 'Adobe' in self.patch["name"]:
                if "Adobe Acrobat DC" in self.patch["name"]:
                    continue
                else:
                    # In the case of multiple Adobe apps being installed, avoid multiple copies of instructions being given.
                    if "To update Adobe Apps" not in self.instructions:
                        self.instructions += f'To update Adobe Apps, you will need to use Adobe Creative Cloud rather than Self Service. '
                    else:
                        continue

        # Spacing
        self.instructions += '\n\n'

        if self.slack_text != '':
            # Formatting info here: https://api.slack.com/reference/surfaces/formatting
            return str(f"Hi {self.fname},\nYour laptop ({self.hostname}) has one or more applications that need to be updated:\n" + self.slack_text + self.instructions + f"You can update most applications by going to [INSTRUCTIONS FOR UPDATING APPS]. \n\nIf you are unsure how to update a specific app, please get in touch: <https://YOUR_TICKETING_PLATFORM.COM|YOUR_TICKETING_PLATFORM>\n_This is an automated message so apologies if I don't see your response_")
        else:
            return str('')


class SlackMessageFormattingLeave:
    def __init__(self, fname, hostname, patches):
        # Initialise variables
        self.fname = fname
        self.patches = patches
        self.hostname = hostname
        self.slack_text = ''
        self.instructions = ''

    def __repr__(self):
        # All apps we don't want to push messaging for
        for self.patch in self.patches:
            if 'Apple macOS' in self.patch["name"]:
                continue
            
            self.slack_text += f'    - {self.patch["name"]} -> {self.patch  ["newver"]}\n'

            # Instructions for updating apps which are picked up by Patch Management but aren't updated through Self Service/Munki/whatever platform.
            if 'Apple Safari' in self.patch["name"]:
                self.instructions += f'To update Safari, go to System Preferences > Software Update > More Info..., check that Safari is ticked, and then click "Install Now". '

            if 'Adobe' in self.patch["name"]:
                if "Adobe Acrobat DC" in self.patch["name"]:
                    continue
                else:
                    # In the case of multiple Adobe apps being installed, avoid multiple copies of instructions being given.
                    if "To update Adobe Apps" not in self.instructions:
                        self.instructions += f'To update Adobe Apps, you will need to use Adobe Creative Cloud rather than Self Service. '
                    else:
                        continue

        # Spacing
        self.instructions += '\n\n'

        if self.slack_text != '':
            # Formatting info here: https://api.slack.com/reference/surfaces/formatting
            return str(f"Hi {self.fname},\nYour laptop ({self.hostname}) has one or more applications that need to be updated, can you update these once you're back?\n" + self.slack_text + self.instructions + f"You can update most applications by going to [INSTRUCTIONS FOR UPDATING APPS]. \n\nIf you are unsure how to update a specific app, please get in touch: <https://YOUR_TICKETING_PLATFORM.COM|YOUR_TICKETING_PLATFORM>\n_This is an automated message so apologies if I don't see your response_")
        else:
            return str('')

def get_token():
    username = os.getenv('JAMF_PATCH_USER')
    password = os.getenv('JAMF_PATCH_PASS')

    token_url = jamf_url+"/api/v1/auth/token"

    credential = f"{username}:{password}"
    credential_b64 = base64.b64encode(credential.encode("utf-8"))

    headers = {"Accept": "application/json", "Authorization": f"Basic {str(credential_b64, 'utf-8')}"}

    try:
        response = requests.request("POST", token_url, headers=headers)
        print("Token acquired")
    except Exception as e:
        print(f"Error: {e}")
    return json.loads(response.text)["token"]

def api_request(url, endpoint):
    headers = {"Accept": "application/xml", "Authorization": f"Bearer {token}"}
    response = requests.request("GET", url+endpoint, headers=headers)
    return xmltodict.parse(response.text)

def parse_pc(title, install, new):
    return {
        "name": title["patch_report"]["name"],
        "installver": install["software_version"],
        "newver": new
        }

def manage_pc_definition(pc_definition, pc, pc_id):
    if pc_id in pc_definition:
        pc_definition[pc_id].append(pc)
    else:
        pc_definition[pc_id] = [pc]   

def validate_email(email):
    # Check that returned emails match abc@def.xyz
    if email is not None:
        valid_email = re.compile(r'^.+@.+\..+$')
        if re.fullmatch(valid_email, email):
            return True
        else:
            return False
    else:
        return False

def send_slack_message(pc_id, patches):
    slack_auth_token = os.getenv('SLACK_MAILER_TOKEN')
    # Create Slack client
    client = WebClient(token=slack_auth_token)

    fname = 'No firstname data'
    lname = 'No lastname data'
    userid = 'No userid data'

    # Enter hostnames that you don't want to send messages to assigned users of.
    # Useful for when exceptions occur and you don't want to send the same people multiple messages
    ignore_list=[
        "test-tim-9001",
    ]

    # If --id is supplied, as part of --slack_test, only grab info from the specified device
    if args.id is not None:
        device_info = api_request(url, computers+"/id/"+str(args.id))
    else:
        device_info = api_request(url, computers+"/id/"+pc_id)

    email_address = device_info["computer"]["location"]["email_address"]
    hostname = device_info["computer"]["general"]["name"]

    # Test that:
    # 1) Device isn't in the ignore list
    # 2) Supplied email address isn't none
    # 3) Device doesn't just have macOS or any other excluded apps to patch
    # 4) Catches an issue with inventory not being reported correctly
    if hostname in ignore_list:
        print(f'Skipping {hostname} as in ignore list')
    elif email_address is None:
        print(f'Skipping {hostname} as no email has been specified')
    elif patches is None or patches == '':
        print(f'Issue detected with inventory on {hostname}')
    elif str(SlackMessageFormattingRegular('', hostname, patches)) == '':
        print (f'Skipping {hostname} as only ignored apps available to patch')
        if args.slack_test is not None:
            sys.exit("Test case over, exiting...")
    else:
        if validate_email(email_address) == True:
            # Virtually identical to code block below, just sends specified email address (args.slack_test) a copy of both messages being sent, and then exits
            if args.slack_test is not None:
                try:
                    user_response = client.users_lookupByEmail(
                        email = args.slack_test
                    )
                    if user_response['ok']:
                        user = user_response['user']
                        userid = str(user['id'])
                        fname = user['real_name'].split(' ')[0]
                        lname = user['real_name'].split(' ')[1]
                        print(f"Sending regular test message to {hostname} - {userid} - {fname} {lname}")
                        client.chat_postMessage(
                            channel=userid,
                            text=str(SlackMessageFormattingRegular(fname, hostname, patches))
                        )
                        print(f"Sending on-leave test message to {hostname} - {userid} - {fname} {lname}")
                        client.chat_postMessage(
                                    channel=userid,
                                    text=str(SlackMessageFormattingLeave(fname, hostname, patches))
                                )
                        print(f"Messages have successfully been sent to {hostname} - {userid} - {fname} {lname}") 
                        time.sleep(3)
                        sys.exit("Test case over, exiting...")
                except Exception as e:
                    print(f"An error occured while processing {userid} - {fname} {lname}: {e}")

            # If Slack messaging has been selected, format and send the message
            if args.slack == True:
                try:
                    user_response = client.users_lookupByEmail(
                        email = email_address
                    )
                    if user_response['ok']:
                        user = user_response['user']
                        userid = str(user['id'])
                        fname = user['real_name'].split(' ')[0]
                        lname = user['real_name'].split(' ')[1]
                        user_profile = user['profile']
                        status_emoji = user_profile['status_emoji']
                        # If slack status has either a palm tree or a thermometer, respect their status unless the override is set (args.force, or --force)
                        if status_emoji == ":palm_tree" or status_emoji == ":face_with_thermometer":
                            if args.force == True:
                                client.chat_postMessage(
                                    channel=userid,
                                    text=str(SlackMessageFormattingRegular(fname, hostname, patches))
                                )
                                print(f"Message has been sent to {userid} - {fname} {lname}, ignoring Slack status.")
                            else:
                                client.chat_postMessage(
                                    channel=userid,
                                    text=str(SlackMessageFormattingLeave(fname, hostname, patches))
                                )
                                print(f"On-leave message has been sent to {userid} - {fname} {lname}")
                        else:
                            client.chat_postMessage(
                                channel=userid,
                                text=str(SlackMessageFormattingRegular(fname, hostname, patches))
                            )
                            print(f"Message has successfully been sent to {userid} - {fname} {lname}")
                        time.sleep(0.5)
                    else:
                        raise Exception(user_response['error'])
                except Exception as e:
                    print(f'An error occured while processing {userid} - {fname} {lname}: {e}')    

def main():
    patch_ids = api_request(url, patch_titles) 
    # Creates a dict, which is then used in manage_pc_definition()
    pc_definition = {}

    print("Checking patches")
    # Iterates though patch titles and builds a pc_definition for any devices which have an update to complete
    for patch in patch_ids["patch_software_titles"]["patch_software_title"]:
        software_title = api_request(url, patch_reports+patch["id"])
        for patch_id, patch_version in enumerate(software_title["patch_report"]["versions"]["version"]):
            if patch_id == 0:
                currentver = patch_version["software_version"]
                continue
            if patch_version["software_version"]  == "Unknown":
                continue
            device_count = patch_version["computers"]["size"]
            if device_count == "1":
                manage_pc_definition(pc_definition, parse_pc(software_title, patch_version, currentver), patch_version["computers"]["computer"]["id"])
            elif device_count != "0":
                for pc in patch_version["computers"]["computer"]:
                    manage_pc_definition(pc_definition, parse_pc(software_title, patch_version, currentver), pc["id"])

    print("Composing messaging")
    if args.slack_test is not None:
        for key in pc_definition.keys():
            # We iterate through the pc_definition dict until we find the key, aka device ID, we supplied as an argument
            if str(args.id) in str(key):
                print(f'Provided computer ID has been found, and has patches to complete')
                send_slack_message(key, pc_definition[key])
            else:
                continue
    else:
        for key in pc_definition.keys():
            send_slack_message(key, pc_definition[key])
        else:
            print('Something went wrong when attempting to send messages. Turn on verbose_mode for more info.')
            time.sleep(1)
        print(f"All tasks completed")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Send Slack messages to Mac users with pending updates.')
    parser.add_argument('-f', '--force', help="Ignore status emojis", action='store_true')
    parser.add_argument('-st', '--slack_test', type=str, help="Sends a test message via Slack", default=None)
    parser.add_argument('-v', '--verbose_mode', help='Use to enable verbose mode', action='store_true')
    parser.add_argument('-id', '--id', type=int, help='Specify a device ID in Jamf. Required when testing.')

    args = parser.parse_args()

    if args.verbose_mode is True:
        print(f"Verbose mode mode enabled!")
        logging.basicConfig(level=logging.verbose_mode)
        time.sleep(0.5)

    # Get Jamf token
    token = get_token()

    # Require -id to be passed with -st
    if args.slack_test is True:
        if args.id is None:
            sys.exit('No device ID passed, exiting...')

    main()