#!/usr/bin/env bash
# Archives the iOS app in the Release configuration and uploads it to App Store Connect for
# internal TestFlight testing (D90). It never submits for App Review.
#
#   FOOTNOTE_TEAM=<team id> ios/scripts/testflight.sh <path/to/footnote.sqlite>
#
# The bundle must be a release or preview bundle (`make data` / `make data-preview`); the
# Release build phase refuses a development bundle. Signing is automatic: Xcode must be signed
# in to the team's Apple ID (Settings > Accounts), and -allowProvisioningUpdates lets it create
# the distribution certificate and profile. The App Store Connect app record for
# com.filingfootnote.footnote must exist before the first upload. The team id is passed in,
# not committed. The build number is the UTC time, so every upload is new.
set -euo pipefail

team="${FOOTNOTE_TEAM:?set FOOTNOTE_TEAM to the Apple developer team id}"
bundle="${1:?usage: FOOTNOTE_TEAM=<team> ios/scripts/testflight.sh <footnote.sqlite>}"
bundle="$(cd "$(dirname "$bundle")" && pwd)/$(basename "$bundle")"
root="$(cd "$(dirname "$0")/../.." && pwd)"
work="$root/build/testflight"
build_number="$(date -u +%Y%m%d%H%M)"

rm -rf "$work"
mkdir -p "$work"
cat > "$work/ExportOptions.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>method</key><string>app-store-connect</string>
  <key>destination</key><string>upload</string>
  <key>teamID</key><string>${team}</string>
  <key>signingStyle</key><string>automatic</string>
  <key>testFlightInternalTestingOnly</key><true/>
  <key>manageAppVersionAndBuildNumber</key><false/>
</dict>
</plist>
PLIST

xcodebuild archive \
  -project "$root/ios/Footnote.xcodeproj" -scheme Footnote -configuration Release \
  -destination 'generic/platform=iOS' -archivePath "$work/Footnote.xcarchive" \
  -allowProvisioningUpdates \
  DEVELOPMENT_TEAM="$team" CODE_SIGN_STYLE=Automatic \
  CURRENT_PROJECT_VERSION="$build_number" FOOTNOTE_BUNDLE="$bundle"

xcodebuild -exportArchive \
  -archivePath "$work/Footnote.xcarchive" -exportPath "$work/export" \
  -exportOptionsPlist "$work/ExportOptions.plist" -allowProvisioningUpdates

echo "uploaded build $build_number; it appears in App Store Connect > TestFlight after processing"
