# Sourced by release scripts from the repository root. Contains no credentials.
SIGNING_CONFIG="$(python3 tools/release/prepare_signing.py)" || exit 1
CODESIGN_IDENTITY="$(printf '%s\n' "$SIGNING_CONFIG" | sed -n '1p')"
CODESIGN_KEYCHAIN="$(printf '%s\n' "$SIGNING_CONFIG" | sed -n '2p')"
export AISUBPRO_CODESIGN_IDENTITY="$CODESIGN_IDENTITY"
export AISUBPRO_CODESIGN_KEYCHAIN="$CODESIGN_KEYCHAIN"
unset SIGNING_CONFIG
