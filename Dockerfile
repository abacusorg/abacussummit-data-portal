FROM python:3.14-slim
WORKDIR /app
COPY web /app
# portal/data holds the server-side session store, created on first use by
# whatever UID the container runs as
RUN pip install --no-cache-dir -r requirements.txt && \
    mkdir -p portal/data && chmod a+rwx portal/data

EXPOSE 5000

# For local development, instead run the Flask dev server over HTTPS:
# $ openssl req -x509 -newkey rsa:4096 -nodes -out portal/ssl/cert.pem -keyout portal/ssl/key.pem -days 365
# ENV PORTAL_SERVER_NAME localhost:8142
# CMD ["flask", "--app", "portal", "run", "--debug", "--host=0.0.0.0", "--cert=portal/ssl/cert.pem", "--key=portal/ssl/key.pem"]

CMD ["gunicorn", "--bind=0.0.0.0:5000", "--workers=2", "--threads=4", "--access-logfile=-", "portal:app"]
ENTRYPOINT ["/app/docker-entrypoint.sh"]
