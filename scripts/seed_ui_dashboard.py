#!/usr/bin/env python3
"""Demo staging: put the "Grid dispatch triage" dashboard back in dev as if a developer had built it in the UI.

Usage: python3 scripts/with_env.py dev -- python3 scripts/seed_ui_dashboard.py [--force]

This is the one documented exception to "only Terraform writes configuration" (docs/DECISIONS.md): it stands in for
a person clicking Save in Kibana, which calls the same Dashboards API. It only ever touches this one dashboard, only
in the dev space, and only while the dashboard is not captured into Git (modules/bundle/bespoke/dashboards). With
--force it resets the dashboard's content to this starting point.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kibana  # noqa: E402

DASHBOARD_ID = "7f3c9a52-4e1b-4d8a-9c6e-2b5f8d1a0e47"
TITLE = "Grid dispatch triage"
REPO = Path(__file__).resolve().parent.parent

SERVER = 'service.name == "grid-dispatch" AND kind == "Server"'
WINDOW = "@timestamp <= ?_tend AND @timestamp > ?_tstart"


def dashboard():
    return {
        "title": TITLE,
        "description": "On-call starting point for grid-dispatch: request volume, failures and error ratio.",
        "time_range": {"from": "now-1h", "to": "now"},
        "panels": [
            {
                "type": "markdown",
                "id": "triage-notes",
                "grid": {"x": 0, "y": 0, "w": 16, "h": 8},
                "config": {
                    "content": "## Grid dispatch triage\n"
                               "Start here when dispatch errors rise.\n\n"
                               "1. Is it every route or one?\n2. Did a release just go out?\n"
                               "3. Is the error ratio above the 2% release objective?",
                    "settings": {"open_links_in_new_tab": True},
                },
            },
            {
                "type": "vis",
                "id": "failed-requests",
                "grid": {"x": 16, "y": 0, "w": 16, "h": 8},
                "config": {
                    "type": "metric",
                    "title": "Failed requests",
                    "data_source": {"type": "esql", "query":
                                    f'FROM traces-* | WHERE {WINDOW} AND {SERVER} AND status.code == "Error" '
                                    "| STATS failed = COUNT(*)"},
                    "metrics": [{"type": "primary", "column": "failed"}],
                },
            },
            {
                "type": "vis",
                "id": "error-ratio",
                "grid": {"x": 32, "y": 0, "w": 16, "h": 8},
                "config": {
                    "type": "metric",
                    "title": "Error ratio (%)",
                    "data_source": {"type": "esql", "query":
                                    f"FROM traces-* | WHERE {WINDOW} AND {SERVER} "
                                    '| EVAL failed = CASE(status.code == "Error", 1, 0) '
                                    "| STATS error_ratio_pct = ROUND(AVG(failed) * 100, 2)"},
                    "metrics": [{"type": "primary", "column": "error_ratio_pct"}],
                },
            },
            {
                "type": "vis",
                "id": "requests-over-time",
                "grid": {"x": 0, "y": 8, "w": 24, "h": 12},
                "config": {
                    "type": "xy",
                    "title": "Requests over time",
                    "axis": {"x": {"scale": "temporal", "domain": {"type": "fit", "rounding": False}}},
                    "layers": [{
                        "type": "line",
                        "data_source": {"type": "esql", "query":
                                        f"FROM traces-* | WHERE {WINDOW} AND {SERVER} "
                                        "| STATS requests = COUNT(*) BY bucket = BUCKET(@timestamp, 75, ?_tstart, ?_tend)"},
                        "x": {"column": "bucket"},
                        "y": [{"column": "requests"}],
                    }],
                },
            },
            {
                "type": "vis",
                "id": "failures-over-time",
                "grid": {"x": 24, "y": 8, "w": 24, "h": 12},
                "config": {
                    "type": "xy",
                    "title": "Failed requests over time",
                    "axis": {"x": {"scale": "temporal", "domain": {"type": "fit", "rounding": False}}},
                    "layers": [{
                        "type": "line",
                        "data_source": {"type": "esql", "query":
                                        f'FROM traces-* | WHERE {WINDOW} AND {SERVER} AND status.code == "Error" '
                                        "| STATS failed = COUNT(*) BY bucket = BUCKET(@timestamp, 75, ?_tstart, ?_tend)"},
                        "x": {"column": "bucket"},
                        "y": [{"column": "failed"}],
                    }],
                },
            },
        ],
    }


def captured():
    folder = REPO / "modules/bundle/bespoke/dashboards"
    return any(DASHBOARD_ID in f.read_text() for f in folder.glob("*.json")) if folder.exists() else False


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--force", action="store_true", help="reset the content even if the dashboard exists")
    args = p.parse_args()

    if kibana.space() != "gitops-dev":
        sys.exit("seed: dev space only (KIBANA_SPACE must be gitops-dev)")
    if captured():
        sys.exit("seed: this dashboard is captured into Git; Terraform owns it now")

    try:
        kibana.kibana("GET", f"/api/dashboards/{DASHBOARD_ID}")
        exists = True
    except kibana.HTTPError as e:
        if e.status != 404:
            raise
        exists = False

    if exists and not args.force:
        print(f"seed: {TITLE} already exists ({DASHBOARD_ID}); use --force to reset it")
        return
    kibana.kibana("PUT", f"/api/dashboards/{DASHBOARD_ID}", dashboard())
    print(f"seed: {'reset' if exists else 'created'} {TITLE} ({DASHBOARD_ID}) in {kibana.space()}")


if __name__ == "__main__":
    main()
