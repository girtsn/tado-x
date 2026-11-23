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
const scheduleMocks={...mocks};
vm.runInNewContext(scheduleCode+"\nthis.Schedule=TadoXScheduleCard;",scheduleMocks,{filename:scheduleFile});
const card=new scheduleMocks.Schedule();
card._hass=profile("sunday");
assert.equal(Array.from(card._displayDays()).join(","),
  "SUNDAY,MONDAY,TUESDAY,WEDNESDAY,THURSDAY,FRIDAY,SATURDAY");
card._hass=profile("monday");
assert.equal(Array.from(card._displayDays()).join(","),
  "MONDAY,TUESDAY,WEDNESDAY,THURSDAY,FRIDAY,SATURDAY,SUNDAY");

// Date boundaries must follow Home Assistant's configured timezone regardless
// of the viewing phone's timezone, including 23/25-hour DST days.
const brussels={config:{time_zone:"Europe/Brussels"},
  locale:{first_weekday:"monday",language:"en-GB"}};
const nearMidnight=new Date("2026-11-22T23:30:00.000Z"); // Nov 23 in Brussels
const previous= presetRange("yesterday",nearMidnight,brussels);
assert.equal(previous.start,"2026-11-21T23:00:00.000Z");
assert.equal(previous.end,"2026-11-22T23:00:00.000Z");
const spring=presetRange("today",new Date("2026-03-29T12:00:00.000Z"),brussels);
assert.equal(spring.start,"2026-03-28T23:00:00.000Z");
assert.equal(spring.end,"2026-03-29T22:00:00.000Z"); // 23h DST
const autumn=presetRange("today",new Date("2026-10-25T12:00:00.000Z"),brussels);
assert.equal(autumn.start,"2026-10-24T22:00:00.000Z");
assert.equal(autumn.end,"2026-10-25T23:00:00.000Z"); // 25h DST
const specificDay=new Picker();
specificDay.hass=brussels;
specificDay._dayClick(new Date(Date.UTC(2026,10,22)));
assert.equal(specificDay._draftEnd.toISOString(),"2026-11-23T00:00:00.000Z",
  "First click should already select one complete calendar day");
specificDay._apply(specificDay._draftStart,specificDay._draftEnd,"custom");
assert.equal(specificDay.range.start,previous.start);
assert.equal(specificDay.range.end,previous.end);
const york={config:{time_zone:"America/New_York"},locale:{first_weekday:"sunday"}};
const yorkToday=presetRange("today",nearMidnight,york);
assert.equal(yorkToday.start,"2026-11-22T05:00:00.000Z");
assert.equal(yorkToday.end,"2026-11-23T05:00:00.000Z");

console.log("Home Assistant first-weekday regression tests passed");
