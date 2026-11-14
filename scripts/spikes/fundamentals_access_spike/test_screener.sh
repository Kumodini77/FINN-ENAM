#!/bin/sh
# Phase 0B spike: screener.in company-page access verification.
# Honest client identification only — no spoofed browser headers/UA.
# Run from this directory. Writes raw results to ./results/.

set -e
mkdir -p results
UA="FINN-research-spike/0.1 (contact: geet8331@gmail.com)"

for sym in RELIANCE TCS HDFCBANK; do
  echo "--- screener.in company page: $sym ---"
  curl -s -o "results/screener_${sym}.html" \
    -w "status=%{http_code} size=%{size_download} time=%{time_total}s\n" \
    --max-time 20 -A "$UA" "https://www.screener.in/company/${sym}/consolidated/"
  sleep 3
done
