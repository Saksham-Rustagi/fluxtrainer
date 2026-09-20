#!/bin/sh
# Phase 2, end to end. Reads only artefacts produced in Phase 0 and 1: the ranked tables under
# data/ranked/, the v3 simulation under runs/, and the clone's SQLite export. Nothing here
# re-solves a board or recomputes belief.
#
#   sh tools/queue/run_all.sh
#
# Writes reports/queue.html, reports/queue_hooks.tsv, reports/queue_words.tsv,
# reports/misswipes.tsv and reports/PHASE2_SUMMARY.md. Intermediates go to build-queue/.
set -e
cd "$(dirname "$0")/../.."
PY=${PY:-build-analytics/venv/bin/python}
Q=tools/queue
$PY $Q/wordrates.py
$PY $Q/misswipe.py > /dev/null
$PY $Q/pipeline.py
