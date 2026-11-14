#!/bin/sh
# Phase 0B spike: attempt real document downloads discovered from screener.in links.
# Honest client identification only — no spoofed browser headers/UA. Rate-limited with sleeps.
# Run from this directory. Writes to ./documents/.

set -e
mkdir -p documents
UA="FINN-research-spike/0.1 (contact: geet8331@gmail.com)"

echo "--- BSE static document path (Reliance AR 2023, via screener link) ---"
curl -s -o documents/reliance_ar_2023.pdf \
  -w "status=%{http_code} size=%{size_download} type=%{content_type}\n" --max-time 30 -A "$UA" \
  "https://www.bseindia.com/xml-data/corpfiling/AttachHis/b55b5dfc-a3bf-4f24-9d7f-ca09774a1dd9.pdf"
sleep 3

echo "--- NSE archives static annual-report path (Reliance AR 2013) ---"
curl -s -o documents/reliance_ar_2013.zip \
  -w "status=%{http_code} size=%{size_download} type=%{content_type}\n" --max-time 30 -A "$UA" \
  "https://archives.nseindia.com/annual_reports/AR_19_RELIANCE_2012_2013_08052013171218.zip"
sleep 3

echo "--- TCS official IR site (transcript PDF) ---"
curl -s -o documents/tcs_concall_transcript.pdf \
  -w "status=%{http_code} size=%{size_download} type=%{content_type}\n" --max-time 30 -A "$UA" \
  "https://www.tcs.com/content/dam/tcs/investor-relations/financial-statements/2025-26/q1/Management%20Commentary/Transcript%20of%20the%20Q1%202025-26%20Earnings%20Conference%20Call%20held%20at%201900%20hrs%20IST%20on%20Jul%2010,%202025.pdf"
sleep 3

echo "--- HDFC Bank official IR site (Q1 FY27 earnings presentation) ---"
curl -s -o documents/hdfcbank_earnings_presentation.pdf \
  -w "status=%{http_code} size=%{size_download} type=%{content_type}\n" --max-time 30 -A "$UA" \
  "https://www.hdfc.bank.in/content/dam/hdfcbankpws/in/en/pdf/about-us/financial-results/2026-2027/quarter-1/q1fy27-earnings-presentation.pdf"
