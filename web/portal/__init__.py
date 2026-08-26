from flask import Flask
import json

from portal.database import Database

__author__ = 'Lehman Garrison <lgarrison@flatironinstitute.org>'

app = Flask(__name__)
app.config.from_pyfile('portal.conf')
app.config['TEMPLATES_AUTO_RELOAD'] = True
# Flask only autoescapes by file extension (.html etc.), which excludes our
# .jinja2 templates; force it on so untrusted values are escaped by default.
app.jinja_env.autoescape = True

database = Database(app)

with open(app.config['PORTAL_ROOT'] + app.config['DATASETS']) as f:
    datasets = json.load(f)
with open(app.config['PORTAL_ROOT'] + app.config['DESCRIPTIONS']) as f:
    dataset_desc = json.load(f)

import portal.views
