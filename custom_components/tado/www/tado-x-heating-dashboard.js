/* Auto-managed, versioned tado X Heating dashboard strategy.
 * Works with native Home Assistant Lovelace dashboard strategies (2026.5+).
 * General tado X features are standard; Vaillant tab is controlled by
 * a read-only config-entry option sensor, not home-specific entity names.
 */
class TadoXHeatingDashboardStrategy extends HTMLElement {
  static registryDependencies = ["entities"];

  static getCreateSuggestions() {
    return {title: "tado X Heating", icon: "mdi:radiator"};
  }

  static _energyEnabled(hass) {
    return Object.values(hass?.states || {}).some(st =>
      st?.entity_id?.startsWith("binary_sensor.") &&
      st.attributes?.feature === "household_vaillant_mypyllant_gas_allocation" &&
      st.state === "on"
    );
  }

  static shouldRegenerate(config, oldHass, newHass) {
    return this._energyEnabled(oldHass) !== this._energyEnabled(newHass);
  }

  static async generate(config, hass) {
    const overview = {
      title: "Overview",
      path: "overview",
      icon: "mdi:home-thermometer",
      type: "sections",
      max_columns: 2,
      sections: [
        {
          type: "grid",
          cards: [
            {type: "heading", heading: "Heating flow and hot water",
              heading_style: "title", icon: "mdi:heating-coil"},
            {
              type: "custom:tado-x-settings-history-card",
              title: "Heating flow, hot water and outside temperature",
              grid_options: {columns: "full"}
            }
          ]
        },
        {
          type: "grid",
          cards: [
            {type: "heading", heading: "Whole-home heating",
              heading_style: "title", icon: "mdi:radiator"},
            {
              type: "markdown",
              content: [
                "**Available for all tado X installations**",
                "",
                "Heating Off, Resume Schedules, Eco Boost and Top Boost",
                "are integrated above, with restart-safe 30-minute",
                "recovery and a live room schedule/manual-override indicator.",
                "",
                "Eco Boost keeps automatic flow adaptation enabled.",
                "Top Boost temporarily disables it and restores it",
                "when schedules resume."
              ].join("\n"),
              grid_options: {columns: "full"}
            }
          ]
        }
      ]
    };
    const schedules = {
      title: "Schedules", path: "schedules", icon: "mdi:calendar-clock",
      type: "sections", max_columns: 1,
      sections: [{
        type: "grid",
        cards: [
          {type:"heading",heading:"Room heating schedules",
            heading_style:"title",icon:"mdi:calendar-clock"},
          {type:"custom:tado-x-schedule-card",title:"Weekly room schedule editor",
            grid_options:{columns:"full"}}
        ]
      }]
    };
    const views = [overview];

    // Feature detection is based on the installed integration's read-only
    // binary sensor: no hard-coded home ID or Vaillant entity IDs.
    if (this._energyEnabled(hass)) {
      views.push({
        title:"Consumption",path:"consumption",icon:"mdi:chart-line",
        type:"sections",max_columns:1,
        sections:[{
          type:"grid",
          cards:[
            {type:"heading",heading:"Heating gas input by room",
              heading_style:"title",icon:"mdi:fire"},
            {type:"custom:tado-x-heating-energy-card",
              title:"Estimated Vaillant heating gas by room",
              grid_options:{columns:"full"}},
            {type:"markdown",content:[
              "**Optional Vaillant/myPyllant extension.**",
              "The estimates allocate measured heating-gas INPUT using",
              "room heating demand and configured radiator capacities.",
              "Historical gas totals reconstructed from daily readings",
              "do not represent observed hourly burner operation."
            ].join(" ")}
          ]
        }]
      });
    }
    // Always last as requested. No empty Consumption tab for other users.
    views.push(schedules);
    return {title: config.title || "tado X Heating", views};
  }
}

if (!customElements.get("ll-strategy-dashboard-tado-x-heating")) {
  customElements.define(
    "ll-strategy-dashboard-tado-x-heating",
    TadoXHeatingDashboardStrategy
  );
}
window.customStrategies = window.customStrategies || [];
if (!window.customStrategies.some(item => item.type === "tado-x-heating"
    && item.strategyType === "dashboard")) {
  window.customStrategies.push({
    type:"tado-x-heating", strategyType:"dashboard",
    name:"tado X Heating (managed)",
    description:"Always-current heating flow, room schedules and optional Vaillant consumption",
    documentationURL:"https://github.com/girtsn/tado-x"
  });
}
