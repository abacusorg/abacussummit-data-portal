from flask import redirect, request, session, url_for
from functools import wraps


def authenticated(fn):
    """Mark a route as requiring authentication."""
    @wraps(fn)
    def decorated_function(*args, **kwargs):
        if not session.get('is_authenticated'):
            # only GETs are safe to replay after login
            next_url = request.url if request.method == 'GET' else None
            return redirect(url_for('login', next=next_url))

        return fn(*args, **kwargs)
    return decorated_function
