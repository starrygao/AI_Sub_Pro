# Quality, release, architecture and credentials

Accepted scope: improvement items 2, 3, 4 and 5 from the project review.

- Quality: run the production subtitle translator on a corpus rather than only scoring stored candidates; include run timing, provider batch submissions, rework rate, model identity and an auditable manual-review packet. Keep offline fixtures and actual model runs explicitly distinct. Add discourse, condition, slang, name and sound-description cases from existing regression patterns, with provenance. Do not claim better model quality from mock tests.
- Release: pin Python and release dependency closure, build in an isolated environment, verify the packaged process (version, catalog and legacy configuration migration) automatically. Exercise synthetic credential write/read/delete in that actual executable. Preserve user data when replacing the app.
- Architecture: establish a translation-task service entry point used by HTTP routes, scheduler and trailer workflows; extract frontend model settings from the main app module. Preserve cancellation, task registration and quality-gate behavior with regression tests.
- Credentials: explicitly select native OS stores; never use null/plaintext fallback. Persist references only after write/read verification. Leave original configuration intact on migration failure. Return configured booleans, accept write-only replacements, distinguish blank/unchanged from explicit removal. Keep unit tests isolated from real credentials.

Delivery: relevant/full tests, final diff, commit on main, build/install new version, verify installed UI, remove prior app and old generated package. Existing codebase-memory index changes remain outside the commit.
