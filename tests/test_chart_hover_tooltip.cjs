/* Browser-free hover, touch and keyboard checks for the shared SVG tooltip. */
const assert=require("node:assert/strict");
const fs=require("node:fs");
const path=require("node:path");
const vm=require("node:vm");
const name=process.argv[2];
if(!name)throw Error("Pass a path to the tooltip module");
const source=fs.readFileSync(path.resolve(name),"utf8").replace(
  "export function attachRecorderChartTooltip","function attachRecorderChartTooltip"
);
class Element{
  constructor(tag){this.tag=tag;this.attrs={};this.children=[];this.style={};
    this.handlers={};this.className="";this.textContent="";}
  setAttribute(k,v){this.attrs[k]=String(v);}
  append(...nodes){this.children.push(...nodes);}
  replaceChildren(...nodes){this.children=nodes;}
  addEventListener(k,fn){this.handlers[k]=fn;}
  getBoundingClientRect(){return{left:10,top:20,width:400,height:230};}
  get offsetWidth(){return 180;}
  get offsetHeight(){return 90;}
}
const document={createElement:tag=>new Element(tag),
  createElementNS:(_ns,tag)=>new Element(tag)};
const context=vm.createContext({document,console});
vm.runInContext(source+"\nthis.attachRecorderChartTooltip=attachRecorderChartTooltip;",context);
const start=1700000000000,hour=3600000,end=start+4*hour;
const host=new Element("section"),svg=new Element("svg");
host.append(svg);
context.attachRecorderChartTooltip(host,svg,[
  {label:"Actual",color:"#008888",points:[{x:start+hour,y:21},{x:start+2*hour,y:22}]},
  {label:"Target",color:"#cc7700",points:[{x:start+hour,y:23}]}
],{start,end,width:400,height:230,left:40,right:20,top:10,bottom:30,
    yFor:v=>230-v*8,period:"hour",unit:"°C"});
const hit=svg.children.find(x=>x.tag==="rect"&&x.attrs["pointer-events"]==="all");
const tip=host.children.find(x=>x.className==="recorder-hover-tooltip");
assert.ok(hit&&tip,"Must attach an interactive plot and tooltip");
const clientX=t=>10+40+(t-start)/(end-start)*340;
hit.handlers.pointermove({clientX:clientX(start+hour),clientY:95,pointerType:"mouse"});
assert.equal(tip.style.display,"block");
assert.equal(tip.children[1].children.at(-1).textContent,"21 °C");
assert.equal(tip.children[2].children.at(-1).textContent,"23 °C");
hit.handlers.pointermove({clientX:clientX(start+2*hour),clientY:95,pointerType:"mouse"});
assert.equal(tip.children[1].children.at(-1).textContent,"22 °C");
assert.equal(tip.children[2].children.at(-1).textContent,"—",
  "Missing Target bucket must not be filled in");
hit.handlers.pointermove({clientX:clientX(start+3.25*hour),clientY:95,pointerType:"mouse"});
assert.equal(tip.style.display,"none","No tooltip in long unrecorded gaps");
hit.handlers.pointerdown({clientX:clientX(start+hour),clientY:95,pointerType:"touch"});
assert.equal(tip.style.display,"block","Touch must select the sample");
hit.handlers.pointerleave({pointerType:"touch"});
assert.equal(tip.style.display,"block","Touch should keep selected tooltip visible");
svg.handlers.keydown({key:"Escape",preventDefault(){}});
assert.equal(tip.style.display,"none");
svg.handlers.keydown({key:"ArrowRight",preventDefault(){}});
assert.equal(tip.style.display,"block","Keyboard should select the first sample");
svg.handlers.blur();
assert.equal(tip.style.display,"none");
console.log("Recorder hover, touch, keyboard and missing-data tests passed");
