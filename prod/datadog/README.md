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
- `monitors/` — metric-based alerts (5xx error rate; the denominator is
  floored at 200 req/5min so low-traffic blips can't fake a spike). Note
  Datadog cannot change a monitor's `type` in place — replacing a monitor
  means a new file/name, apply, then manual deletion of the old one.
- `logs/pipeline.json` — processing pipeline for the Caddy JSON access logs:
  URL parsing, standard-attribute remapping, User-Agent parsing (headers are
  flattened first — Caddy logs them as arrays), `country` from
  `Cf-Ipcountry`, URL-decoded `cmd`, `duration_ms`.
- `logs/index_main.json` — retention and exclusion filters (Synthetics
  probes, DO `/health` checks are ingested but not indexed).
- `logs/metrics/` — log-based metrics (15-month retention vs 15 days of
  logs): `explainshell.requests` (by endpoint/status), `.requests_by_country`,
  and `.request.duration` (distribution of `duration_ms` with percentiles).
  The `endpoint` tag comes from the pipeline's category processor — never tag
  metrics by unbounded values like `cmd` or raw path. `compute` is immutable
  after creation; changing it requires delete + recreate in the UI/API.
- `dashboards/` — the "explainshell overview" dashboard (traffic, error rate,
  latency percentiles, country map, top commands, browsers/bots, probe
  response time).

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
