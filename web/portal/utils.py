import hmac
import secrets
from threading import Lock

from flask import request, session

import globus_sdk

from portal import app


def load_portal_client():
    """Create an AuthClient for the portal"""
    return globus_sdk.ConfidentialAppAuthClient(
        app.config['PORTAL_CLIENT_ID'], app.config['PORTAL_CLIENT_SECRET'])


def generate_csrf_token():
    """Return the session's CSRF token, creating it if needed.

    Registered as the `csrf_token()` Jinja global for use in form templates.
    """
    if '_csrf_token' not in session:
        session['_csrf_token'] = secrets.token_urlsafe(32)
    return session['_csrf_token']


def csrf_valid():
    """Check the submitted form's CSRF token against the session's."""
    token = session.get('_csrf_token')
    supplied = request.form.get('_csrf_token', '')
    return bool(token) and hmac.compare_digest(token, supplied)


def begin_oauth_flow(consent_for_transfer=False):
    """Record a fresh OAuth state nonce in the session and return it.

    The nonce is what ties the redirect back from Globus Auth to the browser
    session that started the flow; without one, anyone can replay an auth code
    for their own identity into another user's session.
    """
    state = secrets.token_urlsafe(32)
    session['_oauth_flow'] = {
        'state': state,
        'consent_for_transfer': consent_for_transfer,
    }
    return state


def finish_oauth_flow():
    """Consume the pending OAuth flow, returning it only if `state` matches.

    Returns None when no flow is in progress or the callback's state does not
    match it. The pending flow is dropped either way, so a callback URL is
    single-use.
    """
    flow = session.pop('_oauth_flow', None)
    if flow is None:
        return None
    supplied = request.args.get('state', '')
    # compare as bytes; compare_digest raises on non-ASCII str
    if not hmac.compare_digest(flow['state'].encode(), supplied.encode()):
        return None
    return flow


def get_portal_tokens(
        scopes=['openid', 'urn:globus:auth:scope:demo-resource-server:all']):
    """
    Uses the client_credentials grant to get access tokens on the
    Portal's "client identity."
    """
    with get_portal_tokens.lock:
        if not get_portal_tokens.access_tokens:
            get_portal_tokens.access_tokens = {}

        scope_string = ' '.join(scopes)

        client = load_portal_client()
        tokens = client.oauth2_client_credentials_tokens(
            requested_scopes=scope_string)

        # walk all resource servers in the token response (includes the
        # top-level server, as found in tokens.resource_server), and store the
        # relevant Access Tokens
        for resource_server, token_info in tokens.by_resource_server.items():
            get_portal_tokens.access_tokens.update({
                resource_server: {
                    'token': token_info['access_token'],
                    'scope': token_info['scope'],
                    'expires_at': token_info['expires_at_seconds']
                }
            })

        return get_portal_tokens.access_tokens


get_portal_tokens.lock = Lock()
get_portal_tokens.access_tokens = None
