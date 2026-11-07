/* Node regression tests for the Recorder categorical-timeline parser. */
"use strict";
const fs=require("node:fs");
const vm=require("node:vm");
const assert=require("node:assert/strict");
const path=require("node:path");
const sourcePath=path.resolve(__dirname,
  "../custom_components/tado/www/tado-x-presence-history-card.js");
const code=fs.readFileSync(sourcePath,"utf8")
  .replaceAll("import.meta.url",JSON.stringify("https://example.test/x-presence-history-card.js?v=test"))
  .replace(/^const \{xhPresetRange\}=await import\([^\n]+\);$/m,
    'const xhPresetRange=()=>({start:"2020-01-02T00:00:00Z",end:"2020-01-03T00:00:00Z"});')
  +"\n;globalThis.presenceTest={Card:TadoXPresenceHistoryCard,xhpState,xhpEpoch};";
const ctx={
  URL,Date,JSON,Object,Number,String,Array,Set,Math,
  HTMLElement:class{attachShadow(){return {replaceChildren(){}};}},
  customElements:{get(){return false;},define(){}}
};
vm.runInNewContext(code,ctx,{filename:sourcePath});
const {Card,xhpState,xhpEpoch}=ctx.presenceTest;
assert.equal(xhpState("HOME"),"home");
assert.equal(xhpState("away"),"away");
assert.equal(xhpState("Auto"),"auto");
assert.equal(xhpState(""),"unknown");
assert.equal(xhpEpoch({s:"Home",lu:1577923200}),1577923200000);
assert.equal(xhpEpoch({state:"Home",last_changed:"2020-01-02T00:00:00Z"}),1577923200000);

const card=new Card();
card._range={start:"2020-01-02T00:00:00Z",end:"2020-01-03T00:00:00Z"};
card._history={
  "sensor.effective":[
    {s:"Home",lu:Date.parse("2020-01-01T22:00:00Z")/1000},
    {s:"Home",lu:Date.parse("2020-01-02T03:00:00Z")/1000},
    {s:"Away",lu:Date.parse("2020-01-02T12:00:00Z")/1000}
  ]
};
const segments=card._segments({id:"sensor.effective"});
assert.equal(segments.length,2);
assert.equal(segments[0].state,"home");
assert.equal(segments[0].start,Date.parse("2020-01-02T00:00:00Z"));
assert.equal(segments[0].end,Date.parse("2020-01-02T12:00:00Z"));
assert.equal(segments[1].state,"away");
assert.equal(segments[1].end,Date.parse("2020-01-03T00:00:00Z"));

card._cfg={home_id:"123"};
card._hass={states:{
  "select.x_presence":{state:"Auto",attributes:{
    presence_scope:"selected",tado_home_id:"123",options:["Home","Away","Auto"]}},
  "sensor.tado_x_effective_presence":{state:"Away",attributes:{
    presence_scope:"effective",tado_home_id:"123"}},
  "sensor.home_presence":{state:"home",attributes:{}},
  "select.other_home":{state:"Home",attributes:{
    presence_scope:"selected",tado_home_id:"456",options:["Home","Away","Auto"]}}
}};
const s=card._sources();
assert.equal(s[0].id,"select.x_presence");
assert.equal(s[1].id,"sensor.tado_x_effective_presence");
assert.equal(s[2].id,"sensor.home_presence");
console.log("Tado presence timeline parsing and entity selection tests passed");
