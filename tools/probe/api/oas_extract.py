"""Extract the OpenAPI path items the elasticgitops provider needs, with every referenced
component schema resolved into the same file.

    curl -sSo kibana.serverless.yaml https://raw.githubusercontent.com/elastic/kibana/main/oas_docs/output/kibana.serverless.yaml
    python3 oas_extract.py kibana.serverless.yaml     # needs PyYAML

    # The Dashboards API schemas are published separately (the serverless spec only links to them):
    curl -sSo dash.yaml https://raw.githubusercontent.com/elastic/dashboards-api-spec/HEAD/openapi/kibana-openapi.yaml
    python3 oas_extract.py dash.yaml dashboards dashboards_full <source-url>

Writes fixtures/openapi/<group or output name>.json.
"""
import json
import re
import sys
from pathlib import Path

import yaml

GROUPS = {
    "alerting_v2_rules": [r"^/api/alerting/v2/rules/\{id\}", r"^/api/alerting/v2/rules$"],
    "alerting_v2_action_policies": [r"^/api/alerting/v2/action_policies/\{id\}", r"^/api/alerting/v2/action_policies$"],
    "dashboards": [r"^/api/dashboards"],
    "workflows": [r"^/api/workflows/workflow(/\{id\})?$", r"^/api/workflows/workflow/\{id\}/run$", r"^/api/workflows$"],
    "agent_builder_converse": [r"^/api/agent_builder/converse$"],
    "actions_connector_types": [r"^/api/actions/connector_types$"],
    "settings": [r"settings", r"global_settings"],
}


def refs(node, found):
    if isinstance(node, dict):
        r = node.get("$ref")
        if isinstance(r, str) and r.startswith("#/components/"):
            found.add(r)
        for v in node.values():
            refs(v, found)
    elif isinstance(node, list):
        for v in node:
            refs(v, found)


def resolve(spec, ref):
    node = spec
    for part in ref[2:].split("/"):
        node = node[part.replace("~1", "/").replace("~0", "~")]
    return node


def main():
    src = Path(sys.argv[1])
    only = sys.argv[2] if len(sys.argv) > 2 else None
    out_name = sys.argv[3] if len(sys.argv) > 3 else None
    source_url = sys.argv[4] if len(sys.argv) > 4 else None
    spec = yaml.safe_load(src.read_text())
    out_dir = Path(__file__).resolve().parent.parent / "fixtures" / "openapi"
    out_dir.mkdir(parents=True, exist_ok=True)
    for group, patterns in GROUPS.items():
        if only and group != only:
            continue
        paths = {p: item for p, item in spec["paths"].items() if any(re.search(x, p) for x in patterns)}
        if group == "settings":
            # Only Kibana UI settings (advanced settings) belong here, not APM/Fleet settings.
            paths = {p: v for p, v in paths.items() if "/kibana/" in p}
        seen, queue, components = set(), set(), {}
        refs(paths, queue)
        while queue:
            ref = queue.pop()
            if ref in seen:
                continue
            seen.add(ref)
            node = resolve(spec, ref)
            components[ref] = node
            refs(node, queue)
        doc = {
            "source": source_url or "https://raw.githubusercontent.com/elastic/kibana/main/oas_docs/output/kibana.serverless.yaml",
            "openapi_info_version": spec.get("info", {}).get("version"),
            "paths": paths,
            "components": dict(sorted(components.items())),
        }
        (out_dir / f"{out_name or group}.json").write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n")
        print(group, "paths:", len(paths), "components:", len(components))


if __name__ == "__main__":
    main()
