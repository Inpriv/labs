#!/usr/bin/env bash
# trns APK build script.
# Run from tools/trns/apk/ AFTER pointing trns.inpriv.xyz at the PWA.
#
#   cd tools/trns/apk
#   ./build.sh
#
# Produces: app-release-signed.apk (Android App Bundle → APK set).

set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"

PW=${KEYSTORE_PASS:-trnsdemo}
ALIAS=${KEY_ALIAS:-trns}

export JAVA_HOME="${JAVA_HOME:-C:/Program Files/Android/Android Studio/jbr}"
export PATH="$JAVA_HOME/bin:$PATH"

KEYSTORE="$HERE/trns.keystore"
if [[ ! -f "$KEYSTORE" ]]; then
  echo ">> generating debug keystore"
  keytool -genkey -v -keystore "$KEYSTORE" -alias "$ALIAS" \
    -keyalg RSA -keysize 2048 -validity 10000 \
    -storepass "$PW" -keypass "$PW" \
    -dname "CN=trns, OU=Inpriv Labs, O=Inpriv, L=Warsaw, ST=Mazovia, C=PL"
fi

# Generate android.keystore alias expected by bubblewrap (it expects
# `android.keystore` and `android` alias by default — alias can be
# overridden in twa-manifest.json; we'll keep our own trns.* here).

echo ">> bubblewrap build"
bubblewrap build \
  --manifest="$HERE/twa-manifest.json" \
  --keystore="$KEYSTORE" \
  --keystorePassword="$PW" \
  --keyPassword="$PW" \
  --keyalias="$ALIAS"

echo ">> done. APK in app/build/outputs/apk/"
ls -la "$HERE/app/build/outputs/apk/" 2>/dev/null || ls -la app-release-signed.apk 2>/dev/null || true
