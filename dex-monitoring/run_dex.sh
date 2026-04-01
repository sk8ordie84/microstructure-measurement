#!/bin/bash
# run_dex.sh — DEX CLOB toxicity pipeline
#
# Cron example (runs every 5 minutes):
#   */5 * * * * /bin/bash <your-project-dir>/run_dex.sh >> <your-project-dir>/logs/dex/pipeline.log 2>&1
#
# Runs collector then aggregator. If collector fails, aggregator still runs
# (scores existing data). Each step is independent.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
mkdir -p logs/dex

TS=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
echo "[$TS] run_dex.sh start"

# Step 1: Collect L2 snapshots
python3 dex_collector.py 2>&1 || echo "  ⚠ dex_collector.py failed"

# Step 2: Aggregate and score
python3 dex_aggregator.py 2>&1 || echo "  ⚠ dex_aggregator.py failed"

# Step 3: Dataset integrity monitor (non-blocking)
python3 dex_monitor.py 2>&1 || echo "  ⚠ dex_monitor.py failed — continuing"

TS2=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
echo "[$TS2] run_dex.sh done"
echo ""
