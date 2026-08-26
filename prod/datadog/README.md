# Datadog configuration

Source of truth for the Datadog resources used by explainshell, applied with
`apply.py` (mirrors the `prod/digitalocean/app.yaml` + `doctl` pattern).
Datadog access comes from the [Datadog for Open Source](https://www.datadoghq.com/partner/open-source/)
program; log forwarding itself is configured in `prod/digitalocean/app.yaml`
(`log_destinations`, US1 intake).

## Managed resources

- `synthetics/` — uptime checks: homepage status, `/explain?cmd=ls` keyword
  check, and TLS certificate expiry. Probe URLs carry `?_uptime=1` (marks
  probe traffic in logs, busts caches) and the `X-First-Party` header, which
  matches the Cloudflare "trusted internal probes" skip rule so probes bypass
  WAF/rate limiting/bot checks.
- `monitors/` — log-based alerts (5xx spike).
- `logs/pipeline.json` — processing pipeline for the Caddy JSON access logs:
  URL parsing, standard-attribute remapping, User-Agent parsing (headers are
  flattened first — Caddy logs them as arrays), `country` from
  `Cf-Ipcountry`, URL-decoded `cmd`, `duration_ms`.
- `logs/index_main.json` — retention and exclusion filters (Synthetics
  probes, DO `/health` checks are ingested but not indexed).

## Usage

```bash
source .venv/bin/activate
python prod/datadog/apply.py diff    # show drift against the live account
python prod/datadog/apply.py apply   # create/update live resources
```

Requires `DATADOG_API_KEY` and `DATADOG_APP_KEY` in `.env`. The app key is
scoped: `synthetics_read/write`, `monitors_read/write`, `logs_read_data`,
`logs_read_config`, `logs_write_pipelines`, `logs_write_exclusion_filters`,
`logs_modify_indexes`, `user_app_keys`.

Resources are matched by name — renaming a resource in a JSON file makes
`apply` create a new one rather than rename the old. Deletion is manual:
removing a file does not delete the live resource.

## Not managed here (no public API)

Facets and saved views are UI-only. To rebuild by hand in Log Explorer:

- Facets: `@http.url_details.path`, `@http.status_code`,
  `@http.useragent_details.browser.family`, `@country`, `@cmd`, and
  `@duration_ms` as a measure (double, milliseconds).
- Saved view: columns for status code, path, `cmd`, country, browser,
  duration; saved as the default view.

Alert emails go to `idan+alerts@explainshell.com` (set in each resource's
`message` field).
