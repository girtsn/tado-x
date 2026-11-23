# Tado X v2026.11.33 — Vaillant hourly quality diagnostic action compatibility

Home Assistant's action/script runner previously rejected calls to `tado.x_scan_vaillant_hourly_quality` without a `response_variable` because the integration registered the action with `SupportsResponse.ONLY`. This generated errors in `homeassistant.helpers.script.websocket_api_script` and `homeassistant.components.websocket_api.http.connection`, even though Vaillant and Tado data were not modified.

The action is now registered with **`SupportsResponse.OPTIONAL`**. This allows both:
- Simple Developer Tools/script calls that do not need to capture a report;
- Diagnostic calls that capture the full read-only quality scan response in a `response_variable`.

No change to the scan's logic, thresholds, result shape, heating allocations, saved cutoff or Recorder data.

For a script that needs the diagnostic result:

```yaml
sequence:
  - action: tado.x_scan_vaillant_hourly_quality
    data:
      days: 120
      tolerance_wh: 1
      confirmation_days: 3
    response_variable: hourly_quality_report
```

**Note:** A previously recorded error will remain in Home Assistant logs until it is cleared/rotated. This change prevents new errors from the same response-variable omission after the integration reloads.

The separate `frontend.js...import_statistics...json_example_url` translation-formatting error is emitted by the `import_statistics` custom integration and is unrelated to the Tado scan.
