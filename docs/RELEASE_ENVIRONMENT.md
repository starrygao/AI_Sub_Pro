# Repeatable macOS releases

The release target is macOS arm64, Python 3.14.4 (`.python-version`), Node 25.4.0
(`.node-version`) and FFmpeg 8.1.1 with the subtitles filter. Native dependencies
are version-gated; their executable hash and the installed Python versions are
recorded in `release-environment.json`. OS updates, SDKs and signing timestamps
mean this is a repeatable dependency/runtime contract, not a byte-identical DMG
promise. Intel macOS and Windows require separate tested lockfiles.

Run `bash tools/release/build_release.sh`. It creates `.release-venv`, installs
hashed bootstrap dependencies and the 79-package release lock, runs `pip check`
and `npm ci`, builds/signs the app and DMG, and then starts that exact executable
against temporary data. Ordinary development requirements remain flexible;
release builds refuse version drift. ASR support is MLX Whisper on this target;
`requirements-asr.txt` remains the optional faster-whisper development/other-
platform input.

The smoke test verifies version, frontend model module, catalog parity, project
preservation, legacy plaintext-to-Keychain migration, credential reads after a
process restart and explicit deletion. It creates only synthetic credentials,
bypasses HTTP proxies for loopback, uses a separate port/data directory, and makes
no inference requests. A failed smoke check prevents the release wrapper and CI
publish job from succeeding. The signed installed bundle can be tested with the
same `--bundle` command. The app uses the normal macOS Keychain (not the sandbox
access-group API); its signing identity must remain consistent across updates.
Set `AISUBPRO_CODESIGN_IDENTITY` for a stable distribution identity. Local builds
use ad-hoc signing, so macOS may require renewed Keychain access after replacement.

To change dependencies: edit `requirements-release.in`, resolve in a fresh pinned
virtual environment, download the exact distributions, regenerate both lockfiles
with SHA-256 hashes, run the full suite in that environment and the packaged smoke
test, and review the manifest diff. Do not regenerate locks during a normal build.
The lock includes an sdist for proxy_tools; the pinned setuptools bootstrap and
`--no-build-isolation` prevent an unpinned build environment from being fetched.
