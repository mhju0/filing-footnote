#!/usr/bin/env bash
# Records the walkthrough video (roadmap P3) on one iOS simulator: WalkthroughUITests drives
# the app on its development bundle while simctl records the screen.
#
#   ios/scripts/walkthrough.sh <simulator-udid> <output.mp4>
#
# Needs the git-ignored development bundle at ios/Footnote/Resources/footnote.sqlite. The app
# is reinstalled first, so the run starts in Korean with nothing stored. Run it alone: it
# builds, then records only the test run.
set -euo pipefail

udid="$1"
out="$2"
bundle_id="com.filingfootnote.footnote"
root="$(cd "$(dirname "$0")/../.." && pwd)"
dd="$root/build/walkthrough-dd"

[ -f "$root/ios/Footnote/Resources/footnote.sqlite" ] || {
  echo "no development bundle at ios/Footnote/Resources/footnote.sqlite" >&2; exit 1; }

xcrun simctl boot "$udid" 2>/dev/null || true
xcrun simctl bootstatus "$udid" -b >/dev/null
xcrun simctl uninstall "$udid" "$bundle_id" 2>/dev/null || true
xcrun simctl status_bar "$udid" override --time 9:41 --batteryState charged --batteryLevel 100 \
  --cellularBars 4 --wifiBars 3

xcodebuild build-for-testing -project "$root/ios/Footnote.xcodeproj" -scheme FootnoteUITests \
  -destination "platform=iOS Simulator,id=$udid" -derivedDataPath "$dd" \
  CODE_SIGNING_ALLOWED=NO -quiet

xcrun simctl io "$udid" recordVideo --codec h264 --force "$out" &
recorder=$!
sleep 2
status=0
TEST_RUNNER_FOOTNOTE_WALKTHROUGH=1 xcodebuild test-without-building \
  -project "$root/ios/Footnote.xcodeproj" -scheme FootnoteUITests \
  -destination "platform=iOS Simulator,id=$udid" -derivedDataPath "$dd" \
  -only-testing:FootnoteUITests/WalkthroughUITests CODE_SIGNING_ALLOWED=NO -quiet || status=$?
kill -INT "$recorder"
wait "$recorder" || true
xcrun simctl status_bar "$udid" clear
[ "$status" -eq 0 ] || { echo "walkthrough test failed ($status); the video is incomplete" >&2; exit "$status"; }
echo "wrote $out"
