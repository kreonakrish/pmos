#!/usr/bin/env bash
set -euo pipefail
echo "Starting PMOS Validation Suite..."
echo ""

cd "$(dirname "$0")"

# Clean previous report
rm -f .validation_report.json .validation_state.json

# Generate fixtures
echo "=== Generating Fixtures ==="
python -c "from fixtures_gen import generate_fixtures; generate_fixtures()" 2>/dev/null || true
echo ""

# Suite 00 - abort if any fail
echo "=== Suite 00: Health Check ==="
python suites/00_health_check.py || { echo "[ABORT] Health checks failed. Fix services before proceeding."; exit 1; }

# Suites 01-09 in sequence
for i in 01 02 03 04 05 06 07 08 09 10; do
  suite="suites/${i}_*.py"
  for f in $suite; do
    [ -f "$f" ] && echo "" && echo "=== Suite $i ===" && python "$f" || true
  done
done

# Final report
echo ""
python -c "from utils import ValidationReporter; ValidationReporter.load_and_print_final()"
echo ""
echo "Validation complete."
