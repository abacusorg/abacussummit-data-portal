from flask import (abort, flash, redirect, render_template, request, session,
                   url_for)
from markupsafe import Markup
from globus_sdk import (GlobusAPIError, RefreshTokenAuthorizer,
                        TransferAPIError, TransferClient, TransferData)

from portal import app, datasets, dataset_desc
from portal.decorators import authenticated
from portal.utils import (begin_oauth_flow, csrf_valid, finish_oauth_flow,
                          load_portal_client, safe_next_url)

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
    return redirect(url_for('authcallback', next=request.args.get('next')))


@app.route('/about', methods=['GET'])
def about():
    """About page - for information about this portal!"""
    return render_template('about.jinja2')


@app.route('/logout', methods=['POST'])
@authenticated
def logout():
    """
    - Revoke the tokens with Globus Auth.
    - Destroy the session state.
    - Redirect the user to the Globus Auth logout page.

    POST + CSRF token, so that a cross-site request cannot revoke the
    user's tokens.
    """
    if not csrf_valid():
        abort(400)

    client = load_portal_client()

    # Revoke the tokens with Globus Auth
    for token in (
            token_info[ty]
            # get all of the token info dicts
            for token_info in session['tokens'].values()
            # cross product with the set of token types
            for ty in ('access_token', 'refresh_token')
            # only where the relevant token is actually present
            if token_info[ty] is not None):
        client.oauth2_revoke_token(token)

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

    # If there's no "code" query string parameter, we're in this route
    # starting a Globus Auth login flow.
    if 'code' not in request.args:
        client.oauth2_start_flow(
            redirect_uri,
            refresh_tokens=True,
            requested_scopes=app.config['USER_SCOPES'],
            state=begin_oauth_flow(
                next_url=safe_next_url(request.args.get('next'))),
        )

        additional_authorize_params = (
            {'signup': 1} if request.args.get('signup') else {})

        auth_uri = client.oauth2_get_authorize_url(
            query_params=additional_authorize_params)

        return redirect(auth_uri)

    # We do have a "code" param, so we're coming back from Globus Auth.
    # Match the state nonce before exchanging anything: a code that isn't tied
    # to a flow this session started may belong to someone else, and
    # exchanging it would authenticate this session as them.
    flow = finish_oauth_flow()
    if flow is None:
        flash('Your login could not be verified, or it expired before you'
              ' finished. Please log in again.')
        return redirect(url_for('home'))

    client.oauth2_start_flow(
        redirect_uri,
        refresh_tokens=True,
        requested_scopes=app.config['USER_SCOPES']
    )

    code = request.args.get('code')
    try:
        tokens = client.oauth2_exchange_code_for_tokens(code)
    except GlobusAPIError:
        # e.g. an expired auth code
        flash('Login with Globus Auth failed. Please try again.')
        return redirect(url_for('home'))

    id_token = tokens.decode_id_token()
    session.update(
        tokens=tokens.by_resource_server,
        is_authenticated=True,
        name=id_token.get('name', ''),
        email=id_token.get('email', ''),
        institution=id_token.get('organization', ''),
        primary_username=id_token.get('preferred_username'),
        primary_identity=id_token.get('sub'),
    )

    if flow['consent_for_transfer']:
        return redirect(url_for('process_inflight_transfer'))

    return redirect(flow.get('next_url') or url_for('transfer'))


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
            dataset = next(ds for ds in datasets['data']
                           if str(ds['id']) == dataset_id)
        except StopIteration:
            abort(404)

        endpoint_id = app.config['DATASET_ENDPOINT_ID']
        endpoint_path = app.config['DATASET_ENDPOINT_BASE'] + dataset['root']

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
        if not csrf_valid():
            abort(400)

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
        
        # sessions are server-side, so a large selection here cannot
        # overflow the 4 KB cookie limit
        session['form'] = {k: request.form.getlist(k) for k in keys}

        return redirect(browse_endpoint)


def transfer_datasets(params):
    """
    - Take the data returned by the Browse Endpoint helper page
      and make a Globus transfer request.
    - Send the user to the transfer status page with the task id
      from the transfer.
    """

    form = session.get('form')
    if form is None:
        flash('Your transfer selection could not be found; please select again.')
        return redirect(url_for('transfer'))

    redshifts = form['redshifts[]']
    products  = form['products[]']
    simids    = form['simids[]']

    try:
        # the manifest keys redshifts by their form string (e.g. '0.1'), but
        # the directory names need the zero-padded float (e.g. 'z0.100')
        zstrs = {z: f'z{float(z):.3f}' for z in redshifts}

        # simids is actually a singlet string, just to try to keep the POST small
        simids = list(dict.fromkeys(int(s) for s in simids[0].split(',')))

        # flatten products into deduped (category, ftype) pairs,
        # e.g. [('halos','halo_info'), ('power','AB'), ('power','pack9')]
        products = sum((p.strip(',').split(',') for p in products), [])
        products = [p.split('.') for p in dict.fromkeys(products)]
        if not all(len(p) == 2 for p in products):
            raise ValueError
    except ValueError:
        flash('Your transfer selection could not be read; please select again.')
        return redirect(url_for('transfer'))

    sims = [sim for sim in datasets['data'] if sim['id'] in simids]

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
    destination_folder = params.get('destination_folder')
    dest_path_base = GlobusPath(params['destination_path'])
    if destination_folder:
        dest_path_base /= destination_folder

    label = params.get('label') or None

    transfer_data = TransferData(source_endpoint=source_endpoint_id,
                                 destination_endpoint=destination_endpoint_id,
                                 label=label,
                                 encrypt_data=False,verify_checksum=False,
                                 sync_level=app.config['GLOBUS_SYNC_LEVEL'],
                                )

    for sim in sims:
        for z in redshifts:
            zstr = zstrs[z]
            for category,ftype in products:
                if category not in sim or z not in sim[category] or ftype not in sim[category][z]:
                    continue
                
                pathfmt = datasets['products'][category]['path']  # cleaning/{}
                source_path = source_endpoint_base / pathfmt.format(sim['root']) / zstr / ftype
                dest_path = dest_path_base / pathfmt.format(sim['root']) / zstr / ftype

                # globus-sdk serializes the payload with json.dumps, which
                # cannot encode path objects
                transfer_data.add_item(source_path=str(source_path),
                                       destination_path=str(dest_path),
                                       recursive=True)

    try:
        task_id = transfer.submit_transfer(transfer_data)['task_id']
    except TransferAPIError as err:
        flash('Error [{}]: {}'.format(err.code, err.message))
        return redirect(url_for('transfer'))

    status_uri = f'https://app.globus.org/activity/{task_id}'
    # Markup.format escapes its arguments, so only the literal HTML is trusted
    flash(Markup('Transfer request submitted successfully! View transfer status'
                 ' on Globus: <a href="{0}" target="_blank">{0}'
                 ' <i class="fas fa-external-link-alt"></i></a>').format(status_uri))

    return(redirect(url_for('transfer', task_id=task_id)))



@app.route('/submit-transfer', methods=['GET'])
@authenticated
def process_inflight_transfer():
    transfer_data = session.pop('_inflight_transfer', None)
    if transfer_data is None:
        return redirect(url_for('transfer'))
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
    # This POST is cross-site by design (the Globus Browse Endpoint helper
    # page), so it cannot carry our CSRF token; only accept it from Globus.
    # Browsers always send Origin on cross-site POSTs, so a missing header
    # means the request did not come from the helper page.
    if request.headers.get('Origin') != 'https://app.globus.org':
        abort(403)

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
        major, minor = (int(x) for x in
                        destination['gcs_version'].split('.')[:2])
    except (KeyError, AttributeError, ValueError):
        major, minor = 0, 0

    # Only mapped collections on GCS >= 5.4 gate transfers behind a
    # data_access scope; guest collections and GCP endpoints have no such
    # scope, and requesting it for them fails at Globus Auth.
    needs_data_access = (
        destination.get('entity_type') == 'GCSv5_mapped_collection'
        and not destination['high_assurance']
        and (major, minor) >= (5, 4)
        and not destination['non_functional']
    )

    if needs_data_access:
        data_access_scope = "https://auth.globus.org/scopes/" + destination["id"] + "/data_access"
        # Consenting to a collection's data_access scope yields a token whose
        # resource server is the collection UUID, so its presence in the
        # session's tokens marks consent for this specific destination.
        has_consented = destination['id'] in session['tokens']

        if not has_consented:
            session['_inflight_transfer'] = transfer_params
            scopes = app.config['USER_SCOPES'] + (data_access_scope, "urn:globus:auth:scope:transfer.api.globus.org:all["+ data_access_scope +"]")
            redirect_uri = url_for('authcallback',
                                   _external=True,
                                   _scheme=app.config.get("AUTHCALLBACK_SCHEME"),
                                   )
            client = load_portal_client()
            client.oauth2_start_flow(
                redirect_uri,
                refresh_tokens=True,
                requested_scopes=scopes,
                state=begin_oauth_flow(consent_for_transfer=True),
            )
            auth_uri = client.oauth2_get_authorize_url()
            return redirect(auth_uri)

    return transfer_datasets(transfer_params)
