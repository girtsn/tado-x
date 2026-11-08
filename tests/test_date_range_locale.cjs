/* Offline regression: Home Assistant user localization wins over browser locale. */
"use strict";
const assert=require("node:assert/strict");
const fs=require("node:fs");
const vm=require("node:vm");
const path=require("node:path");
const file=path.resolve(__dirname,"../custom_components/tado/www/tado-x-date-range-picker.js");
const mocks={
  HTMLElement:class{
    attachShadow(){return {addEventListener(){},replaceChildren(){}};}
    dispatchEvent(){}
    get isConnected(){return false;}
  },
  CustomEvent:class{constructor(type,options){this.type=type;this.detail=options?.detail;}},
  customElements:{get(){return null;},define(){}},
  navigator:{language:"en-US"},
  window:{customCards:[]},
  Intl,Date,URL,console,
};
const source=fs.readFileSync(file,"utf8")
  .replaceAll("import.meta.url",JSON.stringify("https://example.test/picker.js?v=1"))
  .replace(/^export\s*\{[^}]+\};?\s*$/gm,"");
vm.runInNewContext(source+`\nthis.firstWeekday=xhFirstWeekday;this.presetRange=xhPresetRange;this.Picker=TadoXDateRangePicker;`,mocks,{filename:file});
const {firstWeekday,presetRange,Picker}=mocks;
const profile=(day,language="en-US")=>({locale:{first_weekday:day,language}});
assert.equal(firstWeekday(profile("monday")),1);
assert.equal(firstWeekday(profile("sunday")),0);
assert.equal(firstWeekday(profile("saturday")),6);
assert.equal(firstWeekday(profile("language","en-GB")),1);
assert.equal(firstWeekday(profile("language","en-US")),0);
const sunday=new Date(2026,10,8,12);
const weekStart=(setting)=>new Date(presetRange("week",sunday,setting).start).toDateString();
assert.equal(weekStart(profile("monday")),new Date(2026,10,2).toDateString());
assert.equal(weekStart(profile("sunday")),new Date(2026,10,8).toDateString());
assert.equal(weekStart(profile("saturday")),new Date(2026,10,7).toDateString());
const picker=new Picker();
picker.range=presetRange("week",new Date(),profile("monday"));
picker.hass=profile("monday");
picker.hass=profile("sunday");
assert.equal(picker.range.start,presetRange("week",new Date(),profile("sunday")).start,
  "Live profile change recalculates this-week range");
const scheduleFile=path.resolve(__dirname,"../custom_components/tado/www/tado-x-schedule-card.js");
const scheduleCode=fs.readFileSync(scheduleFile,"utf8")
  .replaceAll("import.meta.url",JSON.stringify("https://example.test/schedule.js?v=1"));
vm.runInNewContext(scheduleCode+"\nthis.Schedule=TadoXScheduleCard;",mocks,{filename:scheduleFile});
const card=new mocks.Schedule();
card._hass=profile("sunday");
assert.equal(Array.from(card._displayDays()).join(","),
  "SUNDAY,MONDAY,TUESDAY,WEDNESDAY,THURSDAY,FRIDAY,SATURDAY");
card._hass=profile("monday");
assert.equal(Array.from(card._displayDays()).join(","),
  "MONDAY,TUESDAY,WEDNESDAY,THURSDAY,FRIDAY,SATURDAY,SUNDAY");
console.log("Home Assistant first-weekday regression tests passed");
