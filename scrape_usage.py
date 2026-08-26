#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "globus-sdk>=4.9.0",
# ]
# ///
'''
sum up lifetime data portal usage
based on a script kindly provided by Lisa Gerhardt at NERSC
'''

import argparse

from globus_sdk import GlobusAppConfig, TransferClient, UserApp

# The clientid of a *Native App* registered at https://developers.globus.org/
# For more information:
# https://docs.globus.org/api/auth/developer-guide/#register-app
CLIENT_ID = '644ae30e-c8f9-4996-8100-0035196aa49e'

APP_NAME = 'Scrape AbacusSummit Data Portal Usage'

ABACUSSUMMIT_NERSC_ENDPOINT = 'ffc65d7a-0bf9-11ec-90b4-41052087bc27'


def setup_transfer_client():
    # UserApp handles the login flow, token storage (under ~/.globus/app/),
    # and token refresh. The default command-line login flow prints a URL and
    # prompts for a code, so it works on a remote node with no browser.
    app = UserApp(
        APP_NAME,
        client_id=CLIENT_ID,
        config=GlobusAppConfig(request_refresh_tokens=True),
    )
    return TransferClient(app=app)


def get_endpoint_id(tc, endpoint_id_or_name):
    """Accept either an endpoint UUID or a display name to search for."""
    try:
        tc.get_endpoint(endpoint_id_or_name)
        return endpoint_id_or_name
    except Exception:
        for ep in tc.endpoint_search(filter_fulltext=endpoint_id_or_name):
            return ep['id']

    raise ValueError(f'Could not find endpoint: {endpoint_id_or_name}')


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Globus transfer lister')
    parser.add_argument('-i','--individual',help="List individual transfers (default is aggregate stats)", action='store_true')
    parser.add_argument('-e','--endpoint',help="Endpoint ID or display name", default=ABACUSSUMMIT_NERSC_ENDPOINT)

    args = vars(parser.parse_args())

    tc = setup_transfer_client()

    endpoint_id = get_endpoint_id(tc, args['endpoint'])
    print(f"Using endpoint: {endpoint_id}")

    ntask = 0
    bytes_transferred = 0
    files_transferred = 0
    users = []
    earliest = 'unknown'

    for page in tc.paginated.endpoint_manager_task_list(filter_endpoint=endpoint_id):
        for task in page:
            # we'll count all tasks, including "failed" ones. they might have still transfered useful data
            earliest = task['request_time']
            ntask += 1
            bytes_transferred += task['bytes_transferred']
            files_transferred += task['files_transferred']
            users += [task['owner_id']]
            if args['individual']:
                print(f"User {task['owner_id']} @ {task['request_time']}: {task['bytes_transferred']/1e9:7.2f} GB, {task['files_transferred']:5d} files")

    nusers = len(set(users))

    print(f'Found {ntask} transfers (from {earliest} onwards)')
    print(f'Data transfered: {bytes_transferred/1e12:.4g} TB, {files_transferred/1e3:.4g} K files')
    print(f'{nusers} unique users')
