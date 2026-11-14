#!/bin/sh
# Phase 0 spike: NSE corporate-announcements access verification.
# Honest client identification only — no spoofed browser headers/UA.
# Run from this directory. Writes raw results to ./results/.

set -e
mkdir -p results
UA="FINN-research-spike/0.1 (contact: geet8331@gmail.com)"

echo "--- NSE homepage ---"
curl -s -o results/nse_homepage.html -w "status=%{http_code} time=%{time_total}s size=%{size_download}\n" \
  --max-time 25 -A "$UA" "https://www.nseindia.com/" \
  | tee results/nse_homepage.status || echo "curl exit code: $?" | tee -a results/nse_homepage.status

echo "--- NSE corporate-announcements API (RELIANCE) ---"
curl -s -o results/nse_api_reliance.json -w "status=%{http_code} time=%{time_total}s size=%{size_download}\n" \
  --max-time 25 -A "$UA" \
  "https://www.nseindia.com/api/corporate-announcements?index=equities&symbol=RELIANCE" \
  | tee results/nse_api_reliance.status || echo "curl exit code: $?" | tee -a results/nse_api_reliance.status

echo "--- NSE archives subdomain (bhavcopy, unrelated to announcements, tested for comparison) ---"
curl -s -o results/nse_archives.html -w "status=%{http_code} time=%{time_total}s size=%{size_download}\n" \
  --max-time 25 -A "$UA" "https://archives.nseindia.com/" \
  | tee results/nse_archives.status || echo "curl exit code: $?" | tee -a results/nse_archives.status
