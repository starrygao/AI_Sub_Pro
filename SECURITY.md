# Security Policy

AI Sub Pro stores runtime data locally, including API keys configured through
the UI. Do not commit `data/`, logs, project media, generated subtitles, or
model caches.

## Reporting Issues

Please report security issues privately through GitHub Security Advisories if
available on the repository. If advisories are not enabled, open an issue with
minimal reproduction details and avoid including secrets, private media, or
personal data.

## Local API Surface

The app is designed for localhost use. By default, CORS accepts loopback
browser origins only. Review any changes to host binding, CORS, project file
paths, file upload handling, and media download behavior carefully.
