#!/usr/bin/env python3
"""Apply the checked-in Datadog config (synthetics, monitors, log pipeline,
log index) to the live account. The JSON files in this directory are the
source of truth, mirroring the prod/digitalocean/app.yaml pattern.

Usage:
    python prod/datadog/apply.py diff    # show drift, change nothing
    python prod/datadog/apply.py apply   # create/update live resources

Reads DATADOG_API_KEY and DATADOG_APP_KEY from the environment (.env is
loaded automatically). Resources are matched to live counterparts by name;
comparison only considers keys present in the local definition, so
server-added fields (ids, timestamps, defaults) don't count as drift.

Deletion is manual: removing a file here does not delete the live resource.
Facets and saved views have no public API and are documented in README.md.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import dotenv

ROOT = Path(__file__).resolve().parent
BASE = "https://api.datadoghq.com"


def _request(
    method: str, path: str, body: dict | None = None, none_on_404: bool = False
) -> Any:
    req = urllib.request.Request(BASE + path, method=method)
    req.add_header("DD-API-KEY", os.environ["DATADOG_API_KEY"])
    req.add_header("DD-APPLICATION-KEY", os.environ["DATADOG_APP_KEY"])
    data = None
    if body is not None:
        req.add_header("Content-Type", "application/json")
        data = json.dumps(body).encode()
    try:
        with urllib.request.urlopen(req, data=data, timeout=60) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        if e.code == 404 and none_on_404:
            return None
        detail = e.read().decode("utf-8", errors="replace")[:500]
        raise SystemExit(f"{method} {path} failed: HTTP {e.code}\n{detail}") from e


def _subset_diff(local: Any, live: Any, path: str = "") -> list[str]:
    """Paths where local differs from live, ignoring live-only dict keys."""
    if isinstance(local, dict) and isinstance(live, dict):
        diffs: list[str] = []
        for k, v in local.items():
            if k not in live:
                diffs.append(f"{path}.{k} (missing live)")
            else:
                diffs.extend(_subset_diff(v, live[k], f"{path}.{k}"))
        return diffs
    if isinstance(local, list) and isinstance(live, list):
        if len(local) != len(live):
            return [f"{path} (length {len(live)} -> {len(local)})"]
        diffs = []
        for i, (lo, li) in enumerate(zip(local, live)):
            diffs.extend(_subset_diff(lo, li, f"{path}[{i}]"))
        return diffs
    if isinstance(local, (int, float)) and isinstance(live, (int, float)):
        return (
            [] if float(local) == float(live) else [f"{path} ({live!r} -> {local!r})"]
        )
    return [] if local == live else [f"{path} ({live!r} -> {local!r})"]


class Resource:
    """One local definition file plus the API calls to sync it."""

    kind: str = ""
    name_key: str = "name"

    def __init__(self, file: Path) -> None:
        self.file = file
        self.local: dict = json.loads(file.read_text())
        self.name: str = self.local[self.name_key]

    def fetch_live(self) -> dict | None:
        raise NotImplementedError

    def create(self) -> None:
        raise NotImplementedError

    def update(self, live: dict) -> None:
        raise NotImplementedError

    def label(self) -> str:
        return f"{self.kind} {self.file.relative_to(ROOT)} ({self.name!r})"


class SyntheticsTest(Resource):
    kind = "synthetics"

    def fetch_live(self) -> dict | None:
        tests = _request("GET", "/api/v1/synthetics/tests")["tests"]
        matches = [t for t in tests if t["name"] == self.name]
        if not matches:
            return None
        return _request(
            "GET", f"/api/v1/synthetics/tests/api/{matches[0]['public_id']}"
        )

    def create(self) -> None:
        _request("POST", "/api/v1/synthetics/tests/api", self.local)

    def update(self, live: dict) -> None:
        _request("PUT", f"/api/v1/synthetics/tests/api/{live['public_id']}", self.local)


class Monitor(Resource):
    kind = "monitor"

    def fetch_live(self) -> dict | None:
        q = urllib.parse.quote(self.name)
        matches = [
            m
            for m in _request("GET", f"/api/v1/monitor?name={q}")
            if m["name"] == self.name
        ]
        return matches[0] if matches else None

    def create(self) -> None:
        _request("POST", "/api/v1/monitor", self.local)

    def update(self, live: dict) -> None:
        _request("PUT", f"/api/v1/monitor/{live['id']}", self.local)


class LogsPipeline(Resource):
    kind = "pipeline"

    def fetch_live(self) -> dict | None:
        matches = [
            p
            for p in _request("GET", "/api/v1/logs/config/pipelines")
            if p["name"] == self.name
        ]
        return matches[0] if matches else None

    def create(self) -> None:
        _request("POST", "/api/v1/logs/config/pipelines", self.local)

    def update(self, live: dict) -> None:
        _request("PUT", f"/api/v1/logs/config/pipelines/{live['id']}", self.local)


class LogsIndex(Resource):
    kind = "index"

    def fetch_live(self) -> dict | None:
        return _request("GET", f"/api/v1/logs/config/indexes/{self.name}")

    def create(self) -> None:
        raise SystemExit(
            f"index {self.name!r} does not exist; indexes are not auto-created"
        )

    def update(self, live: dict) -> None:
        body = {k: v for k, v in self.local.items() if k != "name"}
        _request("PUT", f"/api/v1/logs/config/indexes/{self.name}", body)


class LogsMetric(Resource):
    """Log-based metric. `id` is the metric name; compute is immutable after
    creation, so only filter/group_by changes can be applied in place."""

    kind = "logs-metric"
    name_key = "id"

    def fetch_live(self) -> dict | None:
        resp = _request(
            "GET", f"/api/v2/logs/config/metrics/{self.name}", none_on_404=True
        )
        if not resp:
            return None
        return {"id": resp["data"]["id"], "attributes": resp["data"]["attributes"]}

    def create(self) -> None:
        body = {
            "data": {
                "type": "logs_metrics",
                "id": self.name,
                "attributes": self.local["attributes"],
            }
        }
        _request("POST", "/api/v2/logs/config/metrics", body)

    def update(self, live: dict) -> None:
        attrs = {k: v for k, v in self.local["attributes"].items() if k != "compute"}
        body = {"data": {"type": "logs_metrics", "id": self.name, "attributes": attrs}}
        _request("PATCH", f"/api/v2/logs/config/metrics/{self.name}", body)


class Dashboard(Resource):
    kind = "dashboard"
    name_key = "title"

    def fetch_live(self) -> dict | None:
        boards = _request("GET", "/api/v1/dashboard")["dashboards"]
        matches = [b for b in boards if b["title"] == self.name]
        if not matches:
            return None
        return _request("GET", f"/api/v1/dashboard/{matches[0]['id']}")

    def create(self) -> None:
        _request("POST", "/api/v1/dashboard", self.local)

    def update(self, live: dict) -> None:
        _request("PUT", f"/api/v1/dashboard/{live['id']}", self.local)


def load_resources() -> list[Resource]:
    resources: list[Resource] = []
    for f in sorted((ROOT / "synthetics").glob("*.json")):
        resources.append(SyntheticsTest(f))
    for f in sorted((ROOT / "monitors").glob("*.json")):
        resources.append(Monitor(f))
    for f in sorted((ROOT / "logs").glob("pipeline*.json")):
        resources.append(LogsPipeline(f))
    for f in sorted((ROOT / "logs").glob("index_*.json")):
        resources.append(LogsIndex(f))
    for f in sorted((ROOT / "logs" / "metrics").glob("*.json")):
        resources.append(LogsMetric(f))
    for f in sorted((ROOT / "dashboards").glob("*.json")):
        resources.append(Dashboard(f))
    return resources


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["diff", "apply"])
    args = parser.parse_args()

    dotenv.load_dotenv(ROOT.parent.parent / ".env")
    for var in ("DATADOG_API_KEY", "DATADOG_APP_KEY"):
        if not os.environ.get(var):
            print(f"{var} is not set", file=sys.stderr)
            return 1

    drift = 0
    for res in load_resources():
        live = res.fetch_live()
        if live is None:
            drift += 1
            if args.command == "apply":
                res.create()
                print(f"{res.label()}: created")
            else:
                print(f"{res.label()}: MISSING (apply would create)")
            continue
        diffs = _subset_diff(res.local, live)
        if not diffs:
            print(f"{res.label()}: in sync")
            continue
        drift += 1
        if args.command == "apply":
            res.update(live)
            print(f"{res.label()}: updated ({len(diffs)} changes)")
        else:
            print(f"{res.label()}: DRIFT")
        for d in diffs:
            print(f"    {d}")
    if args.command == "diff" and drift:
        print(f"\n{drift} resource(s) out of sync")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
