#!/usr/bin/env bash
# Captures the app's screens on one booted iOS simulator, in Korean and English, light and
# dark, and at an accessibility text size. Debug builds open each screen from the
# -FootnoteOpen launch argument and scroll long pages with -FootnoteScroll
# (ios/Footnote/App/LaunchRoute.swift).
#
#   ios/scripts/screenshots.sh <simulator-udid> <path/to/Footnote.app> <output-dir> [name-filter]
#
# With a name filter (a substring such as `annual-`), only matching shots are taken.
#
# Build the app first, for example:
#   xcodebuild build -project ios/Footnote.xcodeproj -scheme Footnote \
#     -destination 'platform=iOS Simulator,id=<udid>' -derivedDataPath build/dd CODE_SIGNING_ALLOWED=NO
set -euo pipefail

udid="$1"
app="$2"
out="$3"
filter="${4:-}"
bundle_id="com.filingfootnote.footnote"
mkdir -p "$out"

xcrun simctl boot "$udid" 2>/dev/null || true
xcrun simctl bootstatus "$udid" -b >/dev/null
xcrun simctl install "$udid" "$app"
xcrun simctl status_bar "$udid" override --time 9:41 --batteryState charged --batteryLevel 100 \
  --cellularBars 4 --wifiBars 3

hyundai="dart:00164742"
apple="sec:0000320193"
samsung="dart:00126380"
lgchem="dart:00356361"
biologics="dart:00877059"
buyback="dart:20261029000247"
results="dart:20261029800228"
dividend="dart:20261029800269"
outlook="dart:20261029800240"
clarification="dart:20261030800867"
units="dart:20261102800520"
corrected="dart:20261105000355"
samsung_annual="dart:20260310002820"
lgchem_annual="dart:20260313001195"
apple_annual="sec:0000320193-26-000026"

# name ; route ; language ; appearance ; content size ; scroll (top, center or bottom; filing
# and annual pages only). A filing route is <company id>|<filing id>.
shots=(
  "companies-ko-light;-;ko;light;large;top"
  "companies-en-dark;-;en;dark;large;top"
  "company-hyundai-ko-light;company=$hyundai;ko;light;large;top"
  "company-hyundai-en-light;company=$hyundai;en;light;large;top"
  "company-hyundai-ko-dark;company=$hyundai;ko;dark;large;top"
  "company-apple-ko-light;company=$apple;ko;light;large;top"
  "company-apple-en-dark;company=$apple;en;dark;large;top"
  "company-lgchem-ko-light;company=$lgchem;ko;light;large;top"
  "company-lgchem-en-dark;company=$lgchem;en;dark;large;top"
  "notices-hyundai-ko-light;notices=$hyundai;ko;light;large;top"
  "notices-hyundai-en-dark;notices=$hyundai;en;dark;large;top"
  "news-ko-light;news;ko;light;large;top"
  "company-hyundai-ko-ax;company=$hyundai;ko;light;accessibility-extra-large;top"
  "filing-results-hyundai-ko-light;filing=$hyundai|$results;ko;light;large;top"
  "filing-results-hyundai-ko-light-bottom;filing=$hyundai|$results;ko;light;large;bottom"
  "filing-results-hyundai-en-dark;filing=$hyundai|$results;en;dark;large;top"
  "filing-results-hyundai-en-dark-bottom;filing=$hyundai|$results;en;dark;large;bottom"
  "filing-results-hyundai-en-ax;filing=$hyundai|$results;en;light;accessibility-extra-large;center"
  "filing-buyback-ko-light;filing=$hyundai|$buyback;ko;light;large;top"
  "filing-buyback-en-dark;filing=$hyundai|$buyback;en;dark;large;bottom"
  "filing-buyback-en-ax;filing=$hyundai|$buyback;en;light;accessibility-extra-large;center"
  "filing-dividend-hyundai-ko-light;filing=$hyundai|$dividend;ko;light;large;center"
  "filing-outlook-hyundai-ko-light;filing=$hyundai|$outlook;ko;light;large;top"
  "filing-outlook-hyundai-en-dark;filing=$hyundai|$outlook;en;dark;large;center"
  "filing-clarification-hyundai-ko-light;filing=$hyundai|$clarification;ko;light;large;top"
  "filing-units-hyundai-ko-light;filing=$hyundai|$units;ko;light;large;center"
  "filing-corrected-biologics-ko-light;filing=$biologics|$corrected;ko;light;large;top"
  "annual-samsung-ko-light;filing=$samsung|$samsung_annual;ko;light;large;top"
  "annual-samsung-ko-light-bottom;filing=$samsung|$samsung_annual;ko;light;large;bottom"
  "annual-samsung-en-dark;filing=$samsung|$samsung_annual;en;dark;large;center"
  "annual-samsung-ko-ax;filing=$samsung|$samsung_annual;ko;light;accessibility-extra-large;center"
  "annual-lgchem-ko-light;filing=$lgchem|$lgchem_annual;ko;light;large;center"
  "annual-apple-en-light;filing=$apple|$apple_annual;en;light;large;center"
)

for shot in "${shots[@]}"; do
  IFS=';' read -r name route language appearance size scroll <<<"$shot"
  if [ -n "$filter" ] && [[ "$name" != *"$filter"* ]]; then continue; fi
  xcrun simctl ui "$udid" appearance "$appearance"
  xcrun simctl ui "$udid" content_size "$size"
  xcrun simctl terminate "$udid" "$bundle_id" 2>/dev/null || true
  args=(-language "$language" -FootnoteScroll "$scroll")
  if [ "$route" != "-" ]; then args+=(-FootnoteOpen "$route"); fi
  xcrun simctl launch "$udid" "$bundle_id" "${args[@]}" >/dev/null
  sleep 6
  xcrun simctl io "$udid" screenshot --type=png "$out/$name.png" >/dev/null 2>&1
  echo "$out/$name.png"
done

xcrun simctl ui "$udid" content_size large
xcrun simctl ui "$udid" appearance light
xcrun simctl status_bar "$udid" clear
