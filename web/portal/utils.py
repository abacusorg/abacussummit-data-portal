import hmac
import secrets
from urllib.parse import urlsplit, urlunsplit

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
    # compare as bytes; compare_digest raises on non-ASCII str
    return bool(token) and hmac.compare_digest(token.encode(),
                                               supplied.encode())


def generate_transfer_token():
    """Mint the token that authenticates the transfer submission POST.

    The Globus helper page POSTs back to us cross-site, so the form cannot
    carry our CSRF token; instead this single-purpose token rides in the
    action URL we hand to Globus.
    """
    token = secrets.token_urlsafe(32)
    session['_transfer_token'] = token
    return token


def transfer_token_valid():
    """Check the transfer submission's URL token against the session's."""
    token = session.get('_transfer_token')
    supplied = request.args.get('token', '')
    # compare as bytes; compare_digest raises on non-ASCII str
    return bool(token) and hmac.compare_digest(token.encode(),
                                               supplied.encode())


def safe_next_url(url):
    """Reduce a post-login destination to a same-site relative URL.

    Returns None if `url` is empty or points off-site, so callers can fall
    back to a default. Guards against open redirects: the result never
    carries a scheme or host, and backslashes are rejected because browsers
    treat them as slashes (so '/\\evil.com' would become protocol-relative).
    """
    if not url or '\\' in url:
        return None
    split = urlsplit(url)
    if split.netloc and split.netloc != request.host:
        return None
    # require a single leading slash: '//host' is protocol-relative
    if not split.path.startswith('/') or split.path.startswith('//'):
        return None
    return urlunsplit(('', '', split.path, split.query, ''))


def begin_oauth_flow(consent_for_transfer=False, next_url=None):
    """Record a fresh OAuth state nonce in the session and return it.

    The nonce is what ties the redirect back from Globus Auth to the browser
    session that started the flow; without one, anyone can replay an auth code
    for their own identity into another user's session.
    """
    state = secrets.token_urlsafe(32)
    session['_oauth_flow'] = {
        'state': state,
        'consent_for_transfer': consent_for_transfer,
        'next_url': next_url,
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


