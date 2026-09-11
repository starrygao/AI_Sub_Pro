# Credential storage

API keys and the TMDB key are write-only settings. `GET /api/settings` returns
empty input values and `credentials_configured` booleans. A blank key in an update
means unchanged; `clear_credentials: ["openai", "tmdb"]` explicitly removes keys.
The UI supports replace, clear-on-save and testing an already saved credential.
Ordinary configuration never contains a usable secret after migration.

`Config` keeps resolved credentials in process memory for provider calls. Disk
JSON contains randomly generated references scoped to the configuration path.
The backend explicitly selects macOS Keychain, Windows Credential Manager or
Linux Secret Service through keyring; null/plaintext fallbacks are not accepted.
See https://keyring.readthedocs.io/en/latest/ for the underlying OS adapter API.

Migration writes and reads back every credential before replacing config.json.
A pre-commit failure preserves the old file, cleans new entries and propagates a
safe error. If a rename committed before a sync error, referenced entries are
retained. Keychain errors must not be interpreted as corrupt JSON or bad API
passwords. Unit tests use a memory adapter; release smoke tests exercise native
storage in the signed executable with synthetic values only.

Existing external backups are not silently edited or deleted. Malformed legacy
JSON still uses the existing invalid-file backup path and needs manual recovery;
it may contain old keys. Moving the data directory to another machine also needs
credential re-entry, because OS credentials are not portable with config.json.
Keys are not embedded in logs, command arguments or reports. Testing a saved key
performs a real provider request only when explicitly requested by the user.
