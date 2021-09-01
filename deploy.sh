#!/usr/bin/env bash

set -e

docker login registry.nersc.gov
docker build . -t registry.nersc.gov/desi/abacussummit-portal
docker push registry.nersc.gov/desi/abacussummit-portal
