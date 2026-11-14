#!/bin/sh
# Phase 0 spike: BSE corporate-announcements access verification.
# Honest client identification only — no spoofed browser headers/UA.
# Run from this directory. Writes raw results to ./results/.

set -e
mkdir -p results
UA="FINN-research-spike/0.1 (contact: geet8331@gmail.com)"

echo "--- BSE homepage ---"
curl -s -o results/bse_homepage.html -w "status=%{http_code} time=%{time_total}s size=%{size_download}\n" \
  --max-time 25 -A "$UA" "https://www.bseindia.com/" \
  | tee results/bse_homepage.status

echo "--- BSE corporate-announcements API ---"
curl -s -o results/bse_api.json -w "status=%{http_code} time=%{time_total}s size=%{size_download}\n" \
  --max-time 25 -A "$UA" \
  "https://api.bseindia.com/BseIndiaAPI/api/AnnGetData/w?strCat=-1&strPrevDate=20241101&strScrip=&strSearch=P&strToDate=20241112&strType=C" \
  | tee results/bse_api.status
