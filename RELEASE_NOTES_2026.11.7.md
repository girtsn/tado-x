# tado X v2026.11.7

HACS-installable release of `girtsn/tado-x`, keeping the `tado` integration
domain and PyTado 0.18.15 token-persistence behavior.

- Read and safely edit native tado X room weekly schedules using the included
  Vipera-derived Lovelace editor.
- Expose home DHW manual setpoint, DHW boost/off/auto, maximum flow temperature,
  automatic flow adaptation and calculated optimised flow limit.
- Use existing tado room-demand (%) sensors and the myPyllant Gas Heating
  *hourly Recorder statistics* to estimate a per-room share of heating gas input.
- Provide locally adjustable rated radiator capacity weights, a separate
  unallocated fraction, long-term monthly histories and a heating dashboard.
- Keep existing historical Vaillant statistics untouched. The hourly allocation
  is local Recorder-only, no additional boiler or tado cloud polling.
- Include readback verification, update safety checks and explicit control
  commands; no heating configuration writes at startup.

**Install** via HACS/Marketplace as a custom integration using
`https://github.com/girtsn/tado-x`. Select **v2026.11.7** and restart HA.

**Dashboard resources** (manual one-time registration):

- `/tado/x-schedule-card.js?v=2026.11.7` — JavaScript module
- `/tado/x-heating-energy-card.js?v=2026.11.7` — JavaScript module

See README.md for card examples, actions and the consumption model.

**Caution:** HOPS write endpoints have automated offline test coverage but
haven't been live-tested on this installation. Existing 404 DHW schedule is
not exposed as an editor. The 49°C optimisation value is **not** a live
boiler flow temperature. Heating gas attributed to rooms remains a *modelled
allocation*, not a radiator heat meter.
