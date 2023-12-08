import requests
from flask import (abort, flash, redirect, render_template, request, session,
                   url_for)
from globus_sdk import (RefreshTokenAuthorizer, TransferAPIError,
                        TransferClient, TransferData)

from portal import app, database, datasets, dataset_desc
from portal.decorators import authenticated
from portal.utils import get_safe_redirect, load_portal_client

try:
    from urllib.parse import urlencode
except ImportError:
    from urllib import urlencode
    
from pathlib import PurePosixPath as GlobusPath


@app.route('/', methods=['GET'])
def home():
    """Home page - play with it if you must!"""
    return render_template('home.jinja2')


@app.route('/signup', methods=['GET'])
def signup():
    """Send the user to Globus Auth with signup=1."""
    return redirect(url_for('authcallback', signup=1))


@app.route('/login', methods=['GET'])
def login():
    """Send the user to Globus Auth."""
    return redirect(url_for('authcallback'))


@app.route('/about', methods=['GET'])
def about():
    """About page - for information about this portal!"""
    return render_template('about.jinja2')


@app.route('/logout', methods=['GET'])
@authenticated
def logout():
    """
    - Revoke the tokens with Globus Auth.
    - Destroy the session state.
    - Redirect the user to the Globus Auth logout page.
    """
    client = load_portal_client()

    # Revoke the tokens with Globus Auth
    for token, token_type in (
            (token_info[ty], ty)
            # get all of the token info dicts
            for token_info in session['tokens'].values()
            # cross product with the set of token types
            for ty in ('access_token', 'refresh_token')
            # only where the relevant token is actually present
            if token_info[ty] is not None):
        client.oauth2_revoke_token(
            token, additional_params={'token_type_hint': token_type})

    # Destroy the session state
    session.clear()

    redirect_uri = url_for('home', _external=True)

    ga_logout_url = []
    ga_logout_url.append(app.config['GLOBUS_AUTH_LOGOUT_URI'])
    ga_logout_url.append('?client={}'.format(app.config['PORTAL_CLIENT_ID']))
    ga_logout_url.append('&redirect_uri={}'.format(redirect_uri))
    ga_logout_url.append('&redirect_name=AbacusSummit Data Portal')

    # Redirect the user to the Globus Auth logout page
    return redirect(''.join(ga_logout_url))


@app.route('/profile', methods=['GET', 'POST'])
@authenticated
def profile():
    """User profile information. Assocated with a Globus Auth identity."""
    if request.method == 'GET':
        identity_id = session.get('primary_identity')
        profile = database.load_profile(identity_id)

        if profile:
            name, email, institution = profile

            session['name'] = name
            session['email'] = email
            session['institution'] = institution
        else:
            flash(
                'Please complete any missing profile fields and press Save.')

        if request.args.get('next'):
            session['next'] = get_safe_redirect()

        return render_template('profile.jinja2')
    elif request.method == 'POST':
        name = session['name'] = request.form['name']
        email = session['email'] = request.form['email']
        institution = session['institution'] = request.form['institution']

        database.save_profile(identity_id=session['primary_identity'],
                              name=name,
                              email=email,
                              institution=institution)

        flash('Thank you! Your profile has been successfully updated.')

        if 'next' in session:
            redirect_to = session['next']
            session.pop('next')
        else:
            redirect_to = url_for('profile')

        return redirect(redirect_to)


@app.route('/authcallback', methods=['GET'])
def authcallback():
    """Handles the interaction with Globus Auth."""
    # If we're coming back from Globus Auth in an error state, the error
    # will be in the "error" query string parameter.
    if 'error' in request.args:
        flash("You could not be logged into the portal: " +
              request.args.get('error_description', request.args['error']))
        return redirect(url_for('home'))

    # Set up our Globus Auth/OAuth2 state
    redirect_uri = url_for(
        'authcallback',
        _external=True,
        _scheme=app.config.get("AUTHCALLBACK_SCHEME")
    )

    client = load_portal_client()
    client.oauth2_start_flow(
        redirect_uri,
        refresh_tokens=True,
        requested_scopes=app.config['USER_SCOPES']
    )

    # If there's no "code" query string parameter, we're in this route
    # starting a Globus Auth login flow.
    if 'code' not in request.args:
        additional_authorize_params = (
            {'signup': 1} if request.args.get('signup') else {})

        auth_uri = client.oauth2_get_authorize_url(
            additional_params=additional_authorize_params)

        return redirect(auth_uri)
    else:
        # If we do have a "code" param, we're coming back from Globus Auth
        # and can start the process of exchanging an auth code for a token.
        code = request.args.get('code')
        tokens = client.oauth2_exchange_code_for_tokens(code)

        id_token = tokens.decode_id_token(client)
        session.update(
            tokens=tokens.by_resource_server,
            is_authenticated=True,
            name=id_token.get('name', ''),
            email=id_token.get('email', ''),
            institution=id_token.get('organization', ''),
            primary_username=id_token.get('preferred_username'),
            primary_identity=id_token.get('sub'),
        )

        profile = database.load_profile(session['primary_identity'])

        if profile:
            name, email, institution = profile

            session['name'] = name
            session['email'] = email
            session['institution'] = institution
        else:
            return redirect(url_for('profile',
                            next=url_for('transfer')))
        
        state = request.args.get('state')
        if state == '_inflight_transfer_consent':
            return redirect(url_for('process_inflight_transfer'))

        return redirect(url_for('transfer'))


@app.route('/browse/dataset/<dataset_id>', methods=['GET'])
@app.route('/browse/endpoint/<endpoint_id>/<path:endpoint_path>',
           methods=['GET'])
@authenticated
def browse(dataset_id=None, endpoint_id=None, endpoint_path=None):
    """
    - Get list of files for the selected dataset or endpoint ID/path
    - Return a list of files to a browse view

    The target template (browse.jinja2) expects an `endpoint_uri` (if
    available for the endpoint), `target` (either `"dataset"`
    or `"endpoint"`), and 'file_list' (list of dictionaries) containing
    the following information about each file in the result:

    {'name': 'file name', 'size': 'file size', 'id': 'file uri/path'}

    If you want to display additional information about each file, you
    must add those keys to the dictionary and modify the browse.jinja2
    template accordingly.
    """

    assert bool(dataset_id) != bool(endpoint_id and endpoint_path)

    if dataset_id:
        try:
            dataset = next(ds for ds in datasets if ds['id'] == dataset_id)
        except StopIteration:
            abort(404)

        endpoint_id = app.config['DATASET_ENDPOINT_ID']
        endpoint_path = app.config['DATASET_ENDPOINT_BASE'] + dataset['path']

    else:
        endpoint_path = '/' + endpoint_path

    transfer_tokens = session['tokens']['transfer.api.globus.org']

    authorizer = RefreshTokenAuthorizer(
        transfer_tokens['refresh_token'],
        load_portal_client(),
        access_token=transfer_tokens['access_token'],
        expires_at=transfer_tokens['expires_at_seconds'])

    transfer = TransferClient(authorizer=authorizer)

    try:
        transfer.endpoint_autoactivate(endpoint_id)
        listing = transfer.operation_ls(endpoint_id, path=endpoint_path)
    except TransferAPIError as err:
        flash('Error [{}]: {}'.format(err.code, err.message))
        return redirect(url_for('transfer'))

    file_list = [e for e in listing if e['type'] == 'file']

    ep = transfer.get_endpoint(endpoint_id)

    https_server = ep['https_server']
    endpoint_uri = https_server + endpoint_path if https_server else None
    webapp_xfer = 'https://app.globus.org/file-manager?' + \
        urlencode(dict(origin_id=endpoint_id, origin_path=endpoint_path))

    return render_template('browse.jinja2', endpoint_uri=endpoint_uri,
                           target="dataset" if dataset_id else "endpoint",
                           description=(dataset['name'] if dataset_id
                                        else ep['display_name']),
                           file_list=file_list, webapp_xfer=webapp_xfer)


@app.route('/transfer', methods=['GET', 'POST'])
@authenticated
def transfer():
    """
    - Save the submitted form to the session.
    - Send to Globus to select a destination endpoint using the
      Browse Endpoint helper page.
    """
    if request.method == 'GET':
        endpoint_id = app.config['DATASET_ENDPOINT_ID']
        endpoint_path = app.config['DATASET_ENDPOINT_BASE']
        browse_endpoint = f'https://app.globus.org/file-manager?{urlencode(dict(origin_id=endpoint_id,origin_path=endpoint_path))}'
        
        return render_template('transfer.jinja2',
                               dataset_uri=app.config['DATASETS_TABLE'],
                               browse_endpoint=browse_endpoint,
                               redshifts=datasets['redshifts'],
                               products=dataset_desc['products'],
                              )

    if request.method == 'POST':
        keys = 'redshifts[]', 'products[]', 'simids[]'
        for k in keys:
            if not request.form.getlist(k):
                # Not supposed to happen
                flash('Please select redshifts, products, and simulations.')
                return redirect(url_for('transfer'))

        params = {
            'method': 'POST',
            'action': url_for('submit_transfer', _external=True,
                              _scheme='https'),
            # user must select a folder dest
            'filelimit': 0,
            'folderlimit': 1
        }

        browse_endpoint = 'https://app.globus.org/file-manager?{}' \
            .format(urlencode(params))
        
        session['form'] = {k:request.form.getlist(k) for k in keys}

        return redirect(browse_endpoint)


def transfer_datasets(params):
    """
    - Take the data returned by the Browse Endpoint helper page
      and make a Globus transfer request.
    - Send the user to the transfer status page with the task id
      from the transfer.
    """

    redshifts = session['form']['redshifts[]']
    products  = session['form']['products[]']
    simids    = session['form']['simids[]']
    
    # simids is actually a singlet string, just to try to keep the POST small
    simids = list(map(int, simids[0].split(',')))
    simids = list(dict.fromkeys(simids))  # dedupe
    sims = [sim for sim in datasets['data'] if sim['id'] in simids]
    
    # flatten products
    products = sum((p.strip(',').split(',') for p in products), [])
    products = list(dict.fromkeys(products))  # dedupe
    products = [ p.split('.') for p in products ]  # [ ('halos','halo_info'), ('power','AB'), ('power','pack9')]
    
    transfer_tokens = session['tokens']['transfer.api.globus.org']

    authorizer = RefreshTokenAuthorizer(
        transfer_tokens['refresh_token'],
        load_portal_client(),
        access_token=transfer_tokens['access_token'],
        expires_at=transfer_tokens['expires_at_seconds'])

    transfer = TransferClient(authorizer=authorizer)

    source_endpoint_id = app.config['DATASET_ENDPOINT_ID']
    source_endpoint_base = GlobusPath(app.config['DATASET_ENDPOINT_BASE'])
    destination_endpoint_id = params['destination_endpoint_id']
    destination_folder = params.get('folder[0]')
    dest_path_base = GlobusPath(params['destination_path'])
    if destination_folder:
        dest_path_base /= destination_folder

    label = params.get('label') or None

    transfer_data = TransferData(transfer_client=transfer,
                                 source_endpoint=source_endpoint_id,
                                 destination_endpoint=destination_endpoint_id,
                                 label=label,
                                 encrypt_data=False,verify_checksum=False,
                                 sync_level=app.config['GLOBUS_SYNC_LEVEL'],
                                )

    for sim in sims:
        for z in redshifts:
            zstr = f'z{float(z):.3f}'
            for category,ftype in products:
                if category not in sim or z not in sim[category] or ftype not in sim[category][z]:
                    continue
                
                pathfmt = datasets['products'][category]['path']  # cleaning/{}
                source_path = source_endpoint_base / pathfmt.format(sim['root']) / zstr / ftype
                dest_path = dest_path_base / pathfmt.format(sim['root']) / zstr / ftype

                transfer_data.add_item(source_path=source_path,
                                       destination_path=dest_path,
                                       recursive=True)

    transfer.endpoint_autoactivate(source_endpoint_id)
    transfer.endpoint_autoactivate(destination_endpoint_id)
    task_id = transfer.submit_transfer(transfer_data)['task_id']

    status_uri = f'https://app.globus.org/activity/{task_id}'
    status_uri = f'<a href="{status_uri}" target="_blank">{status_uri} <i class="fas fa-external-link-alt"></i></a>'
    flash('Transfer request submitted successfully! View transfer status on Globus: ' + status_uri)

    return(redirect(url_for('transfer', task_id=task_id)))



@app.route('/submit-transfer', methods=['GET'])
@authenticated
def process_inflight_transfer():
    transfer_data = session['_inflight_transfer']
    return transfer_datasets(transfer_data)


@app.route('/submit-transfer', methods=['POST'])
@authenticated
def submit_transfer():
    """
    - Take the data returned by the Browse Endpoint helper page
      and make a Globus transfer request.
    - Send the user to the transfer status page with the task id
      from the transfer.
    """
    browse_endpoint_form = request.form

    transfer_tokens = session['tokens']['transfer.api.globus.org']

    authorizer = RefreshTokenAuthorizer(
        transfer_tokens['refresh_token'],
        load_portal_client(),
        access_token=transfer_tokens['access_token'],
        expires_at=transfer_tokens['expires_at_seconds'])

    transfer = TransferClient(authorizer=authorizer)

    transfer_params = {
        'source_endpoint_id': app.config['DATASET_ENDPOINT_ID'],
        'source_endpoint_base': app.config['DATASET_ENDPOINT_BASE'],
        'destination_endpoint_id': browse_endpoint_form['endpoint_id'],
        'destination_path': browse_endpoint_form['path'],
        'destination_folder': browse_endpoint_form.get('folder[0]'),
        'label': browse_endpoint_form.get('label')
    }

    destination = transfer.get_endpoint(transfer_params['destination_endpoint_id'])

    try:
        [major, minor, _patch] = destination['gcs_version'].split('.')
    except:  # noqa: E722
        major = 0
        minor = 0

    is_share = 0
    is_non_ha_mapped = not destination['high_assurance'] and (
        int(major) >= 5
        and int(minor) >= 4
    ) and not destination['non_functional'] and not is_share

    if is_non_ha_mapped:
        data_access_scope = "https://auth.globus.org/scopes/" + destination["id"] + "/data_access"
        has_consented = session.get('_inflight_transfer_consent') and session['tokens'].get(session['_inflight_consent'])

        if not has_consented:
            session['_inflight_transfer_consent'] = data_access_scope
            session['_inflight_transfer'] = transfer_params
            scopes = app.config['USER_SCOPES'] + (data_access_scope, "urn:globus:auth:scope:transfer.api.globus.org:all["+ data_access_scope +"]")
            redirect_uri = url_for('authcallback', _external=True)
            client = load_portal_client()
            client.oauth2_start_flow(
                redirect_uri,
                refresh_tokens=True,
                requested_scopes=scopes,
                state="_inflight_transfer_consent"
            )
            auth_uri = client.oauth2_get_authorize_url()
            return redirect(auth_uri)

    return transfer_datasets(transfer_params)
