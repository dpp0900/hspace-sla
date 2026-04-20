#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD_DIR="$ROOT_DIR/build"
SRC_DIR="$ROOT_DIR/src"
MANIFEST_PATH="$ROOT_DIR/AndroidManifest.xml"

ANDROID_SDK_ROOT="${ANDROID_SDK_ROOT:-${ANDROID_HOME:-$HOME/Library/Android/sdk}}"
BUILD_TOOLS_VERSION="${BUILD_TOOLS_VERSION:-35.0.0}"
ANDROID_PLATFORM="${ANDROID_PLATFORM:-35}"
JAVA_HOME="${JAVA_HOME:-/Applications/Android Studio.app/Contents/jbr/Contents/Home}"

ANDROID_JAR="$ANDROID_SDK_ROOT/platforms/android-$ANDROID_PLATFORM/android.jar"
BUILD_TOOLS_DIR="$ANDROID_SDK_ROOT/build-tools/$BUILD_TOOLS_VERSION"
AAPT="$BUILD_TOOLS_DIR/aapt"
D8="$BUILD_TOOLS_DIR/d8"
ZIPALIGN="$BUILD_TOOLS_DIR/zipalign"
APKSIGNER="$BUILD_TOOLS_DIR/apksigner"
JAVAC="$JAVA_HOME/bin/javac"

UNSIGNED_APK="$BUILD_DIR/hspace-test-app-unsigned.apk"
UNALIGNED_APK="$BUILD_DIR/hspace-test-app-unaligned.apk"
ALIGNED_APK="$BUILD_DIR/hspace-test-app-aligned.apk"
FINAL_APK="$BUILD_DIR/hspace-test-app-debug.apk"

DEBUG_KEYSTORE="${DEBUG_KEYSTORE:-$HOME/.android/debug.keystore}"
DEBUG_ALIAS="${DEBUG_ALIAS:-androiddebugkey}"
DEBUG_PASSWORD="${DEBUG_PASSWORD:-android}"

for path in "$ANDROID_JAR" "$AAPT" "$D8" "$ZIPALIGN" "$APKSIGNER" "$JAVAC" "$MANIFEST_PATH"; do
    if [[ ! -e "$path" ]]; then
        echo "Missing required file: $path" >&2
        exit 1
    fi
done

mkdir -p "$BUILD_DIR/classes" "$BUILD_DIR/dex"
rm -f "$UNSIGNED_APK" "$UNALIGNED_APK" "$ALIGNED_APK" "$FINAL_APK"
find "$BUILD_DIR/classes" -type f -delete 2>/dev/null || true
find "$BUILD_DIR/dex" -type f -delete 2>/dev/null || true

JAVA_SOURCES=$(find "$SRC_DIR" -name '*.java' | sort)
if [[ -z "$JAVA_SOURCES" ]]; then
    echo "No Java sources found under $SRC_DIR" >&2
    exit 1
fi

echo "[1/6] Compiling Java sources"
"$JAVAC" \
  --release 11 \
  -cp "$ANDROID_JAR" \
  -d "$BUILD_DIR/classes" \
  $JAVA_SOURCES

echo "[2/6] Converting class files to dex"
"$D8" \
  --lib "$ANDROID_JAR" \
  --min-api 26 \
  --output "$BUILD_DIR/dex" \
  $(find "$BUILD_DIR/classes" -name '*.class' | sort)

echo "[3/6] Packaging Android manifest"
"$AAPT" package \
  -f \
  -M "$MANIFEST_PATH" \
  -I "$ANDROID_JAR" \
  -F "$UNSIGNED_APK"

echo "[4/6] Adding classes.dex"
cp "$UNSIGNED_APK" "$UNALIGNED_APK"
(
  cd "$BUILD_DIR/dex"
  zip -q -u "$UNALIGNED_APK" classes.dex
)

echo "[5/6] Aligning APK"
"$ZIPALIGN" -f 4 "$UNALIGNED_APK" "$ALIGNED_APK"

echo "[6/6] Signing APK"
"$APKSIGNER" sign \
  --ks "$DEBUG_KEYSTORE" \
  --ks-key-alias "$DEBUG_ALIAS" \
  --ks-pass "pass:$DEBUG_PASSWORD" \
  --key-pass "pass:$DEBUG_PASSWORD" \
  --out "$FINAL_APK" \
  "$ALIGNED_APK"

"$APKSIGNER" verify "$FINAL_APK"
echo "Built APK: $FINAL_APK"
