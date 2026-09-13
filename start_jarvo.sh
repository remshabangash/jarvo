#!/bin/sh
set -eu
cd "$(dirname "$0")"

if [ ! -x ".venv/bin/python" ]; then
  echo "JARVO is not installed yet. Run:"
  echo "  python3 -m venv .venv && .venv/bin/python -m pip install -r requirements.txt"
  exit 1
fi

if [ ! -f ".env" ]; then
  printf "GROQ API key: "
  stty -echo
  read GROQ_API_KEY
  stty echo
  printf "\nGROQ_API_KEY=%s\n" "$GROQ_API_KEY" > .env
fi

.venv/bin/python server.py
