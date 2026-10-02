#!/usr/bin/env bash
# Reproduction script for week 13's exit test: "a fresh clone runs on a
# second machine." Run this from a freshly cloned copy of the repository,
# with nothing else set up -- no venv, no data, no prior runs.
#
# What it does, in order: build the pinned environment, run the test suite
# against fakes (no network, no cost), ingest the six-review evaluation
# subset (downloads SYNERGY, ~450MB, first run only), then run the smoke
# config (mock provider, $0) end to end through the harness. It does NOT
# call a real model -- that needs either Ollama running locally or a
# GEMINI_API_KEY, both optional, both described in SETUP.md.
#
# Usage (from the repository root, Git Bash or any POSIX shell):
#   bash scripts/reproduce.sh

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

echo "=== 1/4  Python venv + pinned dependencies ==="
python -m venv .venv
if [ -f .venv/Scripts/python.exe ]; then
    PY=.venv/Scripts/python.exe   # Windows
else
    PY=.venv/bin/python           # macOS / Linux
fi
"$PY" -m pip install --upgrade pip -q
"$PY" -m pip install -r requirements.txt -q

echo "=== 2/4  Test suite (fakes only, no network, no cost) ==="
"$PY" -m pytest -q

echo "=== 3/4  Ingest the six-review evaluation subset ==="
"$PY" -m slr.services.ingest --config configs/ingest_all.yaml

echo "=== 4/4  Smoke run through the harness (mock provider, \$0) ==="
"$PY" -m slr.eval.harness --config configs/smoke.yaml --require-clean

echo
echo "Reproduced. A fresh clone on this machine: installs, tests green,"
echo "ingests the real corpus, and runs the harness end to end."
echo
echo "Next (optional, not required by this script):"
echo "  - Local model screening (\$0): install Ollama, pull qwen2.5:7b-instruct,"
echo "    then: $PY -m slr.eval.harness --config configs/week08_ollama.yaml --require-clean"
echo "  - Dashboard: uvicorn slr.api.app:app   &&   streamlit run app/Home.py"
