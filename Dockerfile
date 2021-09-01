FROM ubuntu:20.04
RUN apt-get update --quiet -y && \
    apt-get install -y python3-flask python3-pip
WORKDIR /app
COPY web /app
RUN pip3 install -r requirements.txt && \
    chmod o+rw portal/data/app.db

EXPOSE 5000

ENV FLASK_ENV development
ENV FLASK_APP portal/__init__.py
ENV PORTAL_SERVER_NAME docker.flatironinstitute.org:8142

ENV GLOBUS_CLIENT_ID_FILE="portal/secrets/GLOBUS_CLIENT_ID"
ENV GLOBUS_CLIENT_SECRET_FILE="portal/secrets/GLOBUS_CLIENT_SECRET"
ENV GLOBUS_GLOBAL_SECRET_FILE="portal/secrets/GLOBUS_GLOBAL_SECRET"

#ENTRYPOINT ["flask"]
CMD ["flask", "run", "--host=0.0.0.0", "--cert=adhoc"]
ENTRYPOINT ["/app/docker-entrypoint.sh"]
