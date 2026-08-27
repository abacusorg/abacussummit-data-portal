FROM ubuntu:20.04
RUN apt-get update --quiet -y && \
    apt-get install -y python3-flask python3-pip
WORKDIR /app
COPY web /app
# portal/data holds the server-side session store, created on first use by
# whatever UID the container runs as
RUN pip3 install -r requirements.txt && \
    mkdir -p portal/data && chmod a+rwx portal/data

EXPOSE 5000

ENV FLASK_APP portal/__init__.py

# Run the Flask server in development mode
# To generate local SSL certificate: 
# $ openssl req -x509 -newkey rsa:4096 -nodes -out portal/ssl/cert.pem -keyout portal/ssl/key.pem -days 365
# ENV FLASK_DEBUG 1
# ENV FLASK_ENV development
# ENV PORTAL_SERVER_NAME localhost:8142

# ENV GLOBUS_CLIENT_ID_FILE="portal/secrets/GLOBUS_CLIENT_ID"
# ENV GLOBUS_CLIENT_SECRET_FILE="portal/secrets/GLOBUS_CLIENT_SECRET"
# ENV GLOBUS_GLOBAL_SECRET_FILE="portal/secrets/GLOBUS_GLOBAL_SECRET"
# CMD ["flask", "run", "--host=0.0.0.0", "--cert=portal/ssl/cert.pem", "--key=portal/ssl/key.pem"]

CMD ["flask", "run", "--host=0.0.0.0"]
ENTRYPOINT ["/app/docker-entrypoint.sh"]
