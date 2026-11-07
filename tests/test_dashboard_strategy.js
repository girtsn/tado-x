/* Offline Node smoke test for the auto-managed dashboard strategy. */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");
const file = path.join(__dirname, "..", "custom_components", "tado",
  "www", "tado-x-heating-dashboard.js");
const registry = new Map();
const context = {
  HTMLElement: class {},
  customElements: {
    get(name) {return registry.get(name);},
    define(name, cls) {registry.set(name, cls);}
  },
  window: {}
};
vm.runInNewContext(fs.readFileSync(file, "utf8"), context);
const Strategy = registry.get("ll-strategy-dashboard-tado-x-heating");
assert.ok(Strategy);
function fake(energy) {
  return {states:{
    "binary_sensor.tado_x_vaillant_energy_enabled":{
      entity_id:"binary_sensor.tado_x_vaillant_energy_enabled",
      state:energy?"on":"off",
      attributes:{feature:"household_vaillant_mypyllant_gas_allocation"}
    }
  }};
}
async function run() {
  const base=await Strategy.generate({},fake(false));
  assert.equal(base.views.length,2);
  assert.deepEqual(Array.from(base.views.map(x=>x.title)),["Overview","Schedules"]);
  assert.ok(!JSON.stringify(base).includes("tado-x-heating-energy-card"));
  const extended=await Strategy.generate({},fake(true));
  assert.deepEqual(
    Array.from(extended.views.map(x=>x.title)),
    ["Overview","Consumption","Schedules"]
  );
  assert.ok(JSON.stringify(extended).includes("tado-x-heating-energy-card"));
  assert.equal(Strategy.shouldRegenerate({},fake(false),fake(true)),true);
  assert.equal(Strategy.shouldRegenerate({},fake(true),fake(true)),false);
  assert.equal(Strategy.shouldRegenerate({},fake(true),fake(false)),true);
  assert.equal(context.window.customStrategies.length,1);
  assert.equal(context.window.customStrategies[0].strategyType,"dashboard");
}
run().catch(e=>{console.error(e);process.exitCode=1;});
