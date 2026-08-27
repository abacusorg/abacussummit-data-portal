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
