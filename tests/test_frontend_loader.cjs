/* Browser-free test for manifest-driven frontend updates.
 * This test never connects to Home Assistant or controls equipment.
 */
const assert=require("node:assert/strict");
const fs=require("node:fs");
const path=require("node:path");
const vm=require("node:vm");

async function main(){
  let version="2026.11.22";
  let online=true;
  let timer=null;
  const tags=new Map(),events={},loaded=[];
  class Element {
    constructor(tag="div"){
      this.tagName=tag;this.children=[];this.textContent="";this.isConnected=true;
    }
    attachShadow(){this.shadowRoot=new Element("shadow");return this.shadowRoot;}
    append(...children){this.children.push(...children);}
    replaceChildren(...children){this.children=children;}
  }
  const window={
    setInterval:(handler,delay)=>{assert.equal(delay,60000);timer=handler;return 42;},
    clearInterval:id=>{assert.equal(id,42);timer=null;},
    addEventListener:(name,handler)=>{events["win-"+name]=handler;},
    removeEventListener:name=>{delete events["win-"+name];},
  };
  const document={
    hidden:false,
    createElement:name=>tags.has(name)?new (tags.get(name))():new Element(name),
    addEventListener:(name,handler)=>{events["doc-"+name]=handler;},
    removeEventListener:name=>{delete events["doc-"+name];},
  };
  const context={
    HTMLElement:Element,document,window,
    customElements:{get:name=>tags.get(name),define:(name,ctor)=>tags.set(name,ctor)},
    fetch:async(uri,options)=>{
      assert.ok(uri.startsWith("/tado/manifest.json?_="));
      assert.equal(options.cache,"no-store");
      if(!online)throw Error("Home Assistant restarting");
      return {ok:true,json:async()=>({version})};
    },
  };
  const loaderFile=path.join(__dirname,"..","custom_components","tado",
    "www","tado-x-heating-loader.js");
  vm.runInNewContext(fs.readFileSync(loaderFile,"utf8"),context,{filename:loaderFile});
  const Loader=tags.get("tado-x-heating-loader-panel");
  assert.ok(Loader,"Loader custom element should exist");
  const panel=new Loader();
  panel.hass={states:{sensor:{state:"25"}}};
  panel.panel={config:{integration_version:version,config_entry:"entry_a"}};
  panel.route={path:"schedules"};
  panel.narrow=true;
  panel._loadModule=async ver=>{
    if(!online)throw Error("404: HA has not registered new route");
    loaded.push(ver);
    class Child extends Element {
      constructor(){super("panel");this._busy=new Set();this._cards=[];}
    }
    tags.set(panel._tag(ver),Child);
  };
  await panel._check();
  assert.equal(panel._version,"2026.11.22");
  assert.equal(panel._mount.children.length,1);
  assert.equal(panel._active.hass,panel._hass);
  assert.equal(panel._active.panel,panel._panel);
  assert.equal(panel._active.route.path,"schedules");
  assert.equal(panel._active.narrow,true);
  const old=panel._active;
  version="2026.11.23";
  await panel._check();
  assert.equal(panel._version,"2026.11.23");
  assert.notEqual(panel._active,old,"A new version must replace old child");
  assert.deepEqual(loaded,["2026.11.22","2026.11.23"]);
  panel.hass={states:{sensor:{state:"26"}}};
  assert.equal(panel._active.hass,panel._hass);

  // Heating changes AND unsaved schedule edits prevent a hot swap.
  let inFlight=panel._active;
  inFlight._cards=[{_busy:true}];
  version="2026.11.24";
  await panel._check();
  assert.equal(panel._version,"2026.11.23");
  inFlight._cards=[{_dirty:new Set(["MONDAY"])}];
  await panel._check();
  assert.equal(panel._version,"2026.11.23");
  inFlight._cards=[];
  await panel._check();
  assert.equal(panel._version,"2026.11.24");

  // The previous panel stays visible when Home Assistant is restarting.
  const previous=panel._active;
  version="2026.11.25";
  online=false;
  await panel._check();
  assert.equal(panel._active,previous);
  assert.ok(panel._status.textContent.includes("current version"));
  online=true;
  await panel._check();
  assert.equal(panel._version,"2026.11.25");
  await panel._check();
  assert.equal(panel._version,"2026.11.25");
  // Callback routes allow hot swapping without a full page reload.
  panel.connectedCallback();
  await new Promise(resolve=>setImmediate(resolve));
  assert.ok(timer);
  assert.ok(events["win-focus"]);
  assert.ok(events["doc-visibilitychange"]);
  version="2026.11.26";
  await events["win-focus"]();
  assert.equal(panel._version,"2026.11.26");
  version="2026.11.27";
  await timer();
  assert.equal(panel._version,"2026.11.27");
  panel.disconnectedCallback();
  assert.equal(timer,null);
  console.log("Frontend loader tests passed");
}
main().catch(error=>{console.error(error);process.exitCode=1;});
