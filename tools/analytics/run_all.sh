#!/bin/sh
# Full pipeline for both players. Boards are solved once into data/ranked/shared/ and reused.
# The second analyze pass redraws the sections that show the other player's own results,
# which exist only once both players have run.
set -e
cd "$(dirname "$0")/../.."
PY=${PY:-build-analytics/venv/bin/python}
A=tools/analytics
for p in miningmath nicole; do
  FLUX_PLAYER=$p $PY $A/ingest.py
  FLUX_PLAYER=$p $PY $A/derive.py
done
$PY $A/crossval.py
for p in miningmath nicole; do FLUX_PLAYER=$p $PY $A/boards.py; done
for p in miningmath nicole; do FLUX_PLAYER=$p $PY $A/analyze.py; done
for p in miningmath nicole; do FLUX_PLAYER=$p $PY $A/analyze.py s4 sh sp; done
for p in miningmath nicole; do FLUX_PLAYER=$p $PY $A/render.py; done
