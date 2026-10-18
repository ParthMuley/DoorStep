#!/usr/bin/env bash
# Start a local MongoDB 7 in Docker for persistent demo data, then print the URI to use.
# Data is synthetic; the container listens on localhost only.
set -euo pipefail
NAME="${MONGO_CONTAINER:-doorstep-mongo}"
if docker ps --format '{{.Names}}' | grep -qx "$NAME"; then
  echo "MongoDB container '$NAME' already running."
elif docker ps -a --format '{{.Names}}' | grep -qx "$NAME"; then
  docker start "$NAME" >/dev/null && echo "Started existing container '$NAME'."
else
  docker run -d --name "$NAME" -p 127.0.0.1:27017:27017 mongo:7 >/dev/null && echo "Created container '$NAME' (mongo:7)."
fi
echo "Use: export MONGODB_URI=mongodb://127.0.0.1:27017   (or put it in .env)"
