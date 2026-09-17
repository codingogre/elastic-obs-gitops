"""Phase 0 probe H: Elasticsearch document API shapes for elasticgitops_release_gate (dev only).

Uses a throwaway index gitops-probe-api-gates (never the real gitops-gates) and deletes it at the end.

    python3 scripts/with_env.py dev -- python3 tools/probe/api/probe_release_gate.py
"""
import kb

A = "release_gate"
IDX = "gitops-probe-api-gates"
GID = "gate-grid-dispatch"

MAPPINGS = {"mappings": {"dynamic": "strict", "properties": {
    "gate_id": {"type": "keyword"},
    "service": {"type": "keyword"},
    "window": {"type": "keyword"},
    "slo_ids": {"type": "keyword"},
    "noisy_rule_budget": {"type": "integer"},
    "objectives": {"properties": {
        "name": {"type": "keyword"}, "max": {"type": "double"}, "compare_to_base": {"type": "boolean"}}},
    "managed_by": {"type": "keyword"},
    "updated_at": {"type": "date"},
}}}

DOC = {
    "gate_id": GID,
    "service": "grid-dispatch",
    "window": "10m",
    "slo_ids": ["svc-grid-dispatch-availability", "svc-grid-dispatch-latency"],
    "objectives": [{"name": "error_ratio", "max": 0.02, "compare_to_base": True}, {"name": "p95_ms", "max": 800}],
    "noisy_rule_budget": 5,
    "managed_by": "terraform",
}


def main():
    try:
        # Would the real names be captured by an index template (data stream) on this project? Read-only simulation.
        for name in ("gitops-gates", IDX):
            kb.es_fire(A, f"00_simulate_index_{name}", "POST", f"/_index_template/_simulate_index/{name}", limit=800,
                       note="Read-only: which index template (if any) applies to this name")
        kb.es_fire(A, "01_create_index_with_mappings", "PUT", f"/{IDX}", body=MAPPINGS)
        kb.es_fire(A, "01b_create_index_again", "PUT", f"/{IDX}", body=MAPPINGS, limit=600)
        kb.es_fire(A, "02_get_missing_doc", "GET", f"/{IDX}/_doc/{GID}")
        kb.es_fire(A, "03_put_doc_create", "PUT", f"/{IDX}/_doc/{GID}?refresh=wait_for", body=DOC)
        st, got = kb.es_fire(A, "04_get_doc", "GET", f"/{IDX}/_doc/{GID}")
        kb.es_fire(A, "05_put_doc_identical", "PUT", f"/{IDX}/_doc/{GID}?refresh=wait_for", body=DOC,
                   note="Index API with an identical body: result and _version")
        kb.es_fire(A, "06_update_doc_identical_detect_noop", "POST", f"/{IDX}/_update/{GID}?refresh=wait_for", body={"doc": DOC},
                   note="_update with an identical partial doc (detect_noop default true)")
        st, cur = kb.es_call("GET", f"/{IDX}/_doc/{GID}")[:2]
        kb.es_fire(A, "07_put_doc_stale_seq_no", "PUT", f"/{IDX}/_doc/{GID}?if_seq_no=0&if_primary_term=999", body=DOC,
                   note="Optimistic concurrency with a stale if_seq_no/if_primary_term", limit=800)
        kb.es_fire(A, "08_put_doc_current_seq_no", "PUT",
                   f"/{IDX}/_doc/{GID}?if_seq_no={cur['_seq_no']}&if_primary_term={cur['_primary_term']}&refresh=wait_for",
                   body=dict(DOC, window="15m"), note="Optimistic concurrency with the current values")
        kb.es_fire(A, "09_create_op_type_existing", "PUT", f"/{IDX}/_create/{GID}", body=DOC,
                   note="_create on an existing id", limit=800)
        kb.es_fire(A, "10_put_doc_unknown_field_strict", "PUT", f"/{IDX}/_doc/{GID}", body=dict(DOC, bogus=1),
                   note="dynamic: strict rejects unknown fields", limit=800)
        kb.es_fire(A, "11_esql_read_by_id", "POST", "/_query?format=json",
                   body={"query": f'FROM {IDX} METADATA _id | WHERE _id == "{GID}" | KEEP _id, gate_id, service, window, slo_ids, noisy_rule_budget, objectives.name, objectives.max'},
                   note="How the release-gate workflow can read a gate by id (ES|QL flattens object arrays into multi-values)",
                   limit=1500)
        kb.es_fire(A, "12_get_doc_missing_index", "GET", "/gitops-probe-api-gates-missing/_doc/x", limit=600)
        kb.es_fire(A, "13_delete_doc", "DELETE", f"/{IDX}/_doc/{GID}?refresh=wait_for")
        kb.es_fire(A, "14_delete_doc_again", "DELETE", f"/{IDX}/_doc/{GID}")
        kb.es_fire(A, "15_get_doc_after_delete", "GET", f"/{IDX}/_doc/{GID}")
    finally:
        kb.es_fire(A, "90_delete_index", "DELETE", f"/{IDX}", limit=300)
        st = kb.es_call("HEAD", f"/{IDX}")[0]
        print("HEAD index after delete:", st)


if __name__ == "__main__":
    main()
