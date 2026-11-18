#!/usr/bin/env bash
# Captures the app's screens on one booted iOS simulator, in Korean and English, light and
# dark, and at an accessibility text size. Debug builds open each screen from the
# -FootnoteOpen launch argument (ios/Footnote/App/LaunchRoute.swift).
#
#   ios/scripts/screenshots.sh <simulator-udid> <path/to/Footnote.app> <output-dir>
#
# Build the app first, for example:
#   xcodebuild build -project ios/Footnote.xcodeproj -scheme Footnote \
#     -destination 'platform=iOS Simulator,id=<udid>' -derivedDataPath build/dd CODE_SIGNING_ALLOWED=NO
set -euo pipefail

udid="$1"
app="$2"
out="$3"
bundle_id="com.filingfootnote.footnote"
mkdir -p "$out"

xcrun simctl boot "$udid" 2>/dev/null || true
xcrun simctl bootstatus "$udid" -b >/dev/null
xcrun simctl install "$udid" "$app"
xcrun simctl status_bar "$udid" override --time 9:41 --batteryState charged --batteryLevel 100 \
  --cellularBars 4 --wifiBars 3

hyundai="dart:00164742"
apple="sec:0000320193"
buyback="dart:20261029000247"
lgchem="dart:00356361"

# name | route | language | appearance | content size
shots=(
  "companies-ko-light|-|ko|light|large"
  "companies-en-dark|-|en|dark|large"
  "company-hyundai-ko-light|company=$hyundai|ko|light|large"
  "company-hyundai-en-light|company=$hyundai|en|light|large"
  "company-hyundai-ko-dark|company=$hyundai|ko|dark|large"
  "company-apple-ko-light|company=$apple|ko|light|large"
  "company-apple-en-dark|company=$apple|en|dark|large"
  "company-lgchem-ko-light|company=$lgchem|ko|light|large"
  "company-lgchem-en-dark|company=$lgchem|en|dark|large"
  "notices-hyundai-ko-light|notices=$hyundai|ko|light|large"
  "notices-hyundai-en-dark|notices=$hyundai|en|dark|large"
  "filing-buyback-ko-light|filing=$hyundai|$buyback|ko|light|large"
  "filing-buyback-en-dark|filing=$hyundai|$buyback|en|dark|large"
  "news-ko-light|news|ko|light|large"
  "company-hyundai-ko-ax|company=$hyundai|ko|light|accessibility-extra-large"
  "filing-buyback-en-ax|filing=$hyundai|$buyback|en|light|accessibility-extra-large"
)

for shot in "${shots[@]}"; do
  IFS='|' read -r -a fields <<<"$shot"
  name="${fields[0]}"
  # A filing route holds its own '|' (company|filing), so the fields shift by one.
  if [ "${#fields[@]}" -eq 6 ]; then
    route="${fields[1]}|${fields[2]}"; language="${fields[3]}"; appearance="${fields[4]}"; size="${fields[5]}"
  else
    route="${fields[1]}"; language="${fields[2]}"; appearance="${fields[3]}"; size="${fields[4]}"
  fi
  xcrun simctl ui "$udid" appearance "$appearance"
  xcrun simctl ui "$udid" content_size "$size"
  xcrun simctl terminate "$udid" "$bundle_id" 2>/dev/null || true
  args=(-language "$language")
  if [ "$route" != "-" ]; then args+=(-FootnoteOpen "$route"); fi
  xcrun simctl launch "$udid" "$bundle_id" "${args[@]}" >/dev/null
  sleep 6
  xcrun simctl io "$udid" screenshot --type=png "$out/$name.png" >/dev/null 2>&1
  echo "$out/$name.png"
done

xcrun simctl ui "$udid" content_size large
xcrun simctl ui "$udid" appearance light
xcrun simctl status_bar "$udid" clear
