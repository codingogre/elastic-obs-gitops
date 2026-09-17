# Release risk assessment

Use this skill to decide whether an error spike or latency regression in a service was caused by a release, and
whether rolling back is the right call. You advise; a human approves any rollback.

## Gather the evidence

Call the tools in this order. Never state a number that did not come from a tool result.

1. `gitops-error-ratio-by-version` with the service name. One row per `service.version` running in the last 30
   minutes: `requests`, `errors`, `error_ratio`, `p95_ms`, and `first_seen` / `last_seen` (when that version first and
   last served a request in the window).
2. `gitops-recent-deploys` with the service name. Pipeline events from the last 24 hours, newest first:
   - `release_started`, `release_succeeded`, `rollback` and `gate_evaluated` carry `gitops.service_version`,
     `gitops.baseline_version`, `gitops.verdict` and `gitops.reasons`;
   - `apply` and `promotion` with `scope = bundle` are observability configuration changes (dashboards, rules, SLOs).
     They do not change application code and cannot cause application errors on their own.
3. `gitops-svc-<service>-health` when it exists for the service: current requests, error ratio and p95 by version,
   with the release gate limits in its description.
4. Optional, when the cause is still unclear: `observability.get_log_groups` for the service over the spike window,
   to see which error messages grew and whether they belong to one version or to a dependency.

## Weigh it

A version is **implicated** when all of these hold:

- **Version-specific:** its `error_ratio` is well above the other version or the baseline (at least 3 times higher,
  or above the release gate maximum while the baseline is below it), or its `p95_ms` is well above the baseline.
- **Enough traffic:** it served at least 100 requests in the window. Fewer requests means low confidence.
- **Time-correlated:** it was released (`release_started`) or first seen (`first_seen`) before the spike, typically
  within the last few hours. A latent bug can surface minutes after the release, even after the gate passed during
  the soak: an earlier `gate_evaluated` pass does not clear a version.

The release is **not** the likely cause when:

- all versions show a similar error ratio: the problem is shared, for example a dependency, infrastructure or data;
- there was no release of the service in the last 24 hours;
- errors are timeouts or connection resets to a dependency, spread over every version;
- the only recent change is a bundle `apply` or `promotion`.

## Recommend

- **Roll back** only when one version is clearly implicated. Name the version to remove and the version to return
  to: the `gitops.baseline_version` of its release event, or else the other version still serving healthy traffic.
- **Do not roll back** when the release is not implicated. Say where to look instead.
- **Investigate** when the evidence is mixed or thin (little traffic, no deploy events, one version only with no
  baseline to compare with).
- A rollback is never urgent enough to skip the human approval.

## Confidence

- **High:** implicated version, at least 3 times the baseline error ratio or above the gate maximum, at least 100
  requests, and a matching release event.
- **Medium:** two of those three.
- **Low:** one or none, or less than 100 requests.

## Output

When the caller asks for a specific output schema, fill that schema exactly. Otherwise answer in Markdown:

```
**Service:** <service>  **Recommendation:** <rollback | do not roll back | investigate>  **Confidence:** <high | medium | low>

**Likely cause:** <one sentence>

**Evidence**
| Version | Requests | Errors | Error ratio | p95 ms | First seen |
|---|---|---|---|---|---|

- Deploys: <the release and gate events that matter, with times>
- <any other fact that decided it>

**Next step:** <roll back <bad> to <good>, or what to check>
```
