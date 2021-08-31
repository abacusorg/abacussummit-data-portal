#!/usr/bin/env bash

# Run the Flask server in development mode
# To generate local SSL certificate: 
# $ openssl req -x509 -newkey rsa:4096 -nodes -out portal/ssl/cert.pem -keyout portal/ssl/key.pem -days 365

export PORTAL_SERVER_NAME='ccalin008.flatironinstitute.org:8142'
#export PORTAL_SERVER_NAME='docker.flatironinstitute.org:8142'

export FLASK_ENV=development
export FLASK_DEBUG=1
export FLASK_APP=portal/__init__.py

export GLOBUS_CLIENT_ID_FILE="portal/secrets/GLOBUS_CLIENT_ID"
export GLOBUS_CLIENT_SECRET_FILE="portal/secrets/GLOBUS_CLIENT_SECRET"
export GLOBUS_GLOBAL_SECRET_FILE="portal/secrets/GLOBUS_GLOBAL_SECRET"

./docker-entrypoint.sh flask run --host=0.0.0.0 --port=8142 --cert=portal/ssl/cert.pem --key=portal/ssl/key.pem
