# Model catalog

`app/model_catalog.json` is the only editable model catalog. The backend reads it
through `app.engines.model_catalog`; `/api/model-catalog.js` supplies the same data
to the UI before `app.js` runs. Packaging already includes the entire `app` tree.

Each provider has an ordered `models` mapping. Entries record context tokens,
reasoning efforts supported by this app's adapter, temperature compatibility,
the connection-test token limit parameter, and evidence source. API and CLI
entries remain separate: Codex CLI's observed default context budget can be lower
than the corresponding API model's documented maximum. These are conservative
local budgets, not an assurance about every account or CLI configuration.

Unknown context sizes use the catalog's conservative 32,000-token fallback and
are visibly marked unverified. Only exact IDs and OpenAI date-suffixed snapshots
inherit known capabilities; arbitrary substring matches never do. Unknown
sampling capabilities omit optional sampling parameters. The adapter exposes a
supported subset of reasoning options; it does not infer API support from CLI
options (for example, CLI `ultra` is not sent to the OpenAI API).

`GET /api/models/{provider}` retains its `models` string array and `fallback`
compatibility field, adding `source`, `reason`, `verified_at`, and `capabilities`.
A remote listing means the server lists a model, not that an inference request
has succeeded. CLI catalogs are static and do not imply account authorization.

Refreshing preserves the selected model, including a model missing from the
remote response. Explicitly changing providers resets that stage's selection;
disabling polishing clears its selection. Translation and polishing retain
independent selections and request guards, sharing an in-flight provider fetch.
Fallback responses are retryable; the refresh button bypasses successful caches.

To update: change the JSON, cite the capability source, and run the catalog,
provider, frontend settings, and full-document translation tests. Use an isolated
`AI_SUB_PRO_DATA_DIR` for tests to avoid importing a user's large local phrase
library. No real credentials or paid API calls are needed for these tests.
