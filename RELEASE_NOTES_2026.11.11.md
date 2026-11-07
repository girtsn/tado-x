# tado X v2026.11.11 — clarify consumption dashboard calculation

Maintenance release for the custom Lovelace heating consumption card.

- Corrects an **obsolete footer** in `tado-x-heating-energy-card.js`
  that still said room capacity defaults to 1 kW per radiator.
- Clearly identifies the actual model: 11 installed physical radiators
  in 10 tado heating rooms, rated nominal **25.748 kW** at EN442
  75/65/20°C (Delta-T50).
- Explains that estimated per-room Vaillant heating-gas **input** is weighted
  by tado room heating demand and each room's aggregate rated radiator output,
  not actual measured heat delivered at a lower boiler flow temperature.
- Keeps the explanation of Unallocated gas, which arises where no room
  demanded heating or demand measurements were incomplete.
- No calculation change, no additional tado cloud requests, no boiler
  settings changed, no prior Recorder statistics modified.

Installation: Update HACS to `2026.11.11`, restart Home Assistant and
refresh the browser or mobile app. Resource cache busting is recommended:

`/tado/x-heating-energy-card.js?v=2026.11.11`

The other two existing custom JavaScript card resources remain compatible.
