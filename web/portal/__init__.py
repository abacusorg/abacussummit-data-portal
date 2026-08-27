from flask import Flask
from flask_session import Session
import json

__author__ = 'Lehman Garrison <lgarrison@flatironinstitute.org>'

app = Flask(__name__)
app.config.from_pyfile('portal.conf')
app.config['TEMPLATES_AUTO_RELOAD'] = True
# Flask only autoescapes by file extension (.html etc.), which excludes our
# .jinja2 templates; force it on so untrusted values are escaped by default.
app.jinja_env.autoescape = True

Session(app)


@app.after_request
def set_security_headers(response):
    response.headers.setdefault('X-Content-Type-Options', 'nosniff')
    response.headers.setdefault('X-Frame-Options', 'SAMEORIGIN')
    return response

with open(app.config['PORTAL_ROOT'] + app.config['DATASETS']) as f:
    datasets = json.load(f)
with open(app.config['PORTAL_ROOT'] + app.config['DESCRIPTIONS']) as f:
    dataset_desc = json.load(f)

import portal.views

from portal.utils import generate_csrf_token
app.jinja_env.globals['csrf_token'] = generate_csrf_token
