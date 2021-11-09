#!/usr/bin/env python3
'''
sum up lifetime data portal usage
based on a script kindly provided by Lisa Gerhardt at NERSC
'''

from __future__ import print_function
import argparse
import tempfile, shlex, os
from subprocess import Popen, PIPE, STDOUT

from globus_sdk import (NativeAppAuthClient, TransferClient,
                        RefreshTokenAuthorizer, TransferData)

from fair_research_login import NativeClient

# You will need to register a *Native App* at https://developers.globus.org/
# Your app should include the following:
#     - The scopes should match the SCOPES variable below
#     - Your app's clientid should match the CLIENT_ID var below
#     - "Native App" should be checked
# For more information:
# https://docs.globus.org/api/auth/developer-guide/#register-app
CLIENT_ID = '644ae30e-c8f9-4996-8100-0035196aa49e'
REDIRECT_URI = 'https://auth.globus.org/v2/web/auth-code'
SCOPES = ('openid email profile '
          'urn:globus:auth:scope:transfer.api.globus.org:all')

APP_NAME = 'Scrape AbacusSummit Data Portal Usage'

ABACUSSUMMIT_NERSC_ENDPOINT = 'ffc65d7a-0bf9-11ec-90b4-41052087bc27'

def get_client_tokens():
    tokens = None
    client = NativeClient(client_id=CLIENT_ID, app_name=APP_NAME)
    try:
        # if we already have tokens, load and use them
        tokens = client.load_tokens(requested_scopes=SCOPES)
    except:
        pass

    if not tokens:
        # if we need to get tokens, start the Native App authentication process
        # need to specify that we want refresh tokens
        # N.B. the no_local_server is the key option not in the Globus automation-examples
        # that lets us accomplish the login on a remote node.
        tokens = client.login(requested_scopes=SCOPES,
                              refresh_tokens=True, no_local_server=True,
                              no_browser=True)
        try:
            client.save_tokens(tokens)
        except:
            pass

    return tokens


def setup_transfer_client():
    tokens = get_client_tokens()
    transfer_tokens = tokens['transfer.api.globus.org']

    authorizer = RefreshTokenAuthorizer(
        transfer_tokens['refresh_token'],
        NativeAppAuthClient(client_id=CLIENT_ID),
        access_token=transfer_tokens['access_token'],
        expires_at=transfer_tokens['expires_at_seconds'])

    transfer_client = TransferClient(authorizer=authorizer)

    return transfer_client


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Globus transfer lister')
    parser.add_argument('-d','--details',help="Get details on individual transfers", action='store_true')
    parser.add_argument('-i','--individual',help="List individual transfers (default is aggregate stats)", action='store_true')
    optionalNamed = parser.add_argument_group('Optional arguments')
    
    args = parser.parse_args()
    
    tc = setup_transfer_client()
    
    ntask = 0
    bytes_transferred = 0
    files_transferred = 0
    earliest = 'unknown'
    for page in tc.paginated.endpoint_manager_task_list(filter_endpoint=ABACUSSUMMIT_NERSC_ENDPOINT):
        for task in page:
            # we'll count all tasks, including "failed" ones. they might have still transfered useful data (e.g. could just be missing one file)
            # i think using "files/bytes_transferred" only counts successful transfers anyway
            earliest = task['request_time']
            ntask += 1
            bytes_transferred += task['bytes_transferred']
            files_transferred += task['files_transferred']

    print(f'Found {ntask} transfers (from {earliest} onwards)')
    print(f'Lifetime data transfered: {bytes_transferred/1e12:.4g} TB, {files_transferred/10**6:.4g} K files')
