/* Integration-managed tado X Heating panel.
 * Registered in HA's sidebar by panel_custom, no Lovelace YAML or
 * manual JS Resources configuration needed. Bundled JS cards are loaded
 * from the same integration's static routes on each HACS update.
 */
/* Each dependency must use the panel's manifest-version cache key.
 * Versioning only the entry module leaves its static imports cached.
 */
const XH_ASSET_VERSION=new URL(import.meta.url).searchParams.get("v")||"dev";
// Register the panel synchronously: asynchronous assets must never blank the sidebar.
let xhPresetRange=null;

class TadoXManagedHeatingPanel extends HTMLElement {
  constructor(){
    super();
    this.attachShadow({mode:"open"});
    this._hass=null;
    this._panel=null;
    this._narrow=false;
    this._tab="overview";
    this._cards=[];
    this._lastEnergy=null;
    this._initialized=false;
    this._dateRange=null;
    this._assetsReady=false;
    this._assetsError="";
    this._assetPromise=null;
    this._assetRetries=0;
    this._connectionStatus=null;
  }
  set hass(value){
    this._hass=value;
    if(!this._assetsReady){
      this._ensureAssets();
      this._render();
      return;
    }
    if(!this._initialized && value){
      this._render();
    }else{
      const enabled=this._energyEnabled();
      if(enabled!==this._lastEnergy && this._tab==="overview"){
        this._render();
      }else{
        for(const card of this._cards)card.hass=value;
        if(this._connectionStatus)this._connectionStatus.hass=value;
      }
    }
  }
  set panel(value){
    const oldId=this._panel?.config?.config_entry;
    const oldVersion=this._panel?.config?.integration_version;
    this._panel=value;
    // When the HA frontend delivers a newly registered panel after a restart,
    // reload once so the new manifest-versioned JS is loaded automatically.
    if(oldVersion && value?.config?.integration_version &&
       oldVersion!==value.config.integration_version){
      // Reload only once per installed version, not on each HA panel refresh.
      const key="tado-x-panel-reload-"+value.config.integration_version;
      try{
        if(window.sessionStorage.getItem(key)!=="1"){
          window.sessionStorage.setItem(key,"1");
          window.location.reload();return;
        }
      }catch(_err){/* Avoid a loop if session storage is restricted. */}
      this._assetsError="Heating panel updated. Reopen this tab if the old panel persists.";
    }
    if(this._hass && oldId!==value?.config?.config_entry)this._render();
  }
  set narrow(value){this._narrow=Boolean(value);}
  set route(value){
    const requested=(value?.path||"").split("/").filter(Boolean)[0];
    const tab=requested==="schedules"?"schedules":"overview";
    if(tab!==this._tab){
      this._tab=tab;
      if(this._hass)this._render();
    }
  }
  connectedCallback(){
    this._ensureAssets();
    if(this._hass && !this._initialized)this._render();
  }
  _ensureAssets(){
    if(this._assetsReady||this._assetPromise||!this.isConnected)return;
    this._assetsError="";
    const version=encodeURIComponent(XH_ASSET_VERSION);
    const retry=this._assetRetries?"&retry="+this._assetRetries:"";
    this._assetPromise=(async()=>{
      // The component has already been defined, so failed modules show an
      // actionable loading error instead of leaving the page empty.
      const picker=await import("./x-date-range-picker.js?v="+version+retry);
      await Promise.all([
        import("./x-connectivity-status.js?v="+version+retry),
        import("./x-settings-history-card.js?v="+version+retry),
        import("./x-schedule-card.js?v="+version+retry),
        import("./x-heating-energy-card.js?v="+version+retry),
      ]);
      xhPresetRange=picker.xhPresetRange;
      if(typeof xhPresetRange!=="function")
        throw new Error("Date picker did not export xhPresetRange");
      this._dateRange??=xhPresetRange("week");
      this._assetsReady=true;
    })().catch(err=>{
      this._assetsError="Could not load Heating dashboard modules (version "+
        XH_ASSET_VERSION+"): "+(err?.message||String(err));
    }).finally(()=>{
      this._assetPromise=null;
      if(this.isConnected&&this._hass)this._render();
    });
  }
  _renderAssetStatus(){
    const root=this.shadowRoot;
    root.replaceChildren();
    const container=this._element("div");
    container.style.cssText="padding:24px;font:inherit;color:var(--primary-text-color)";
    container.append(this._element("h2","tado X Heating"));
    container.append(this._element("p",this._assetsError||
      "Loading Heating dashboard modules…"));
    if(this._assetsError){
      const retry=this._element("button","Retry loading");
      retry.type="button";
      retry.addEventListener("click",()=>{
        this._assetRetries++;
        this._ensureAssets();
        this._renderAssetStatus();
      });
      container.append(retry);
    }
    root.append(container);
  }
  _energyEnabled(){
    if(!this._hass)return false;
    // Detect the integration option's read-only binary sensor by its
    // attributes, not by a changeable Home Assistant entity_id.
    return Object.entries(this._hass.states).some(([id,state])=>
      id.startsWith("binary_sensor.") &&
      state.attributes?.feature==="household_vaillant_mypyllant_gas_allocation" &&
      (!this._panel?.config?.home_id ||
       String(state.attributes?.tado_home_id)===String(this._panel.config.home_id)) &&
      state.state==="on"
    );
  }
  _element(tag,text,cls){
    const el=document.createElement(tag);
    if(text!==undefined && text!==null)el.textContent=text;
    if(cls)el.className=cls;
    return el;
  }
  _card(type,title){
    const el=document.createElement(type);
    el.setConfig({title,config_entry:this._panel?.config?.config_entry,
      shared_date_range:this._tab==="overview",
      shared_connection_status:true});
    if(this._tab==="overview")el.dateRange=this._dateRange;
    el.hass=this._hass;
    this._cards.push(el);
    return el;
  }
  _navigate(tab){
    if(tab===this._tab)return;
    this._tab=tab;
    window.history.pushState(null,"",tab==="overview"
      ?"/tado-x-heating":"/tado-x-heating/schedules");
    this._render();
  }
  _render(){
    if(!this._hass || !this.isConnected)return;
    if(!this._assetsReady){this._renderAssetStatus();return;}
    const enabled=this._energyEnabled();
    this._lastEnergy=enabled;
    this._initialized=true;
    this._cards=[];
    this._connectionStatus=null;
    const root=this.shadowRoot;root.replaceChildren();
    const style=this._element("style");
    style.textContent=[
      ":host{display:block;box-sizing:border-box;font-family:var(--primary-font-family,Roboto,Arial,sans-serif);color:var(--primary-text-color)}",
      "*{box-sizing:border-box}",
      ".shell{max-width:1300px;margin:0 auto;padding:16px 18px 30px}",
      ".header{display:flex;gap:14px;align-items:center;justify-content:space-between;flex-wrap:wrap;margin:0 0 15px}",
      ".title{font-size:24px;font-weight:600;margin:0}",
      ".subtitle{font-size:13px;color:var(--secondary-text-color,#777);margin:5px 0 0}",
      ".tabs{display:flex;gap:7px;border-bottom:1px solid var(--divider-color,#ddd);padding-bottom:10px}",
      ".tab{background:transparent;color:var(--primary-text-color);padding:10px 15px;border-radius:9px;border:1px solid var(--divider-color,#ccc);cursor:pointer;font:inherit}",
      ".tab.selected{background:var(--primary-color,#1976d2);color:white;border-color:var(--primary-color,#1976d2)}",
      ".layout{display:grid;grid-template-columns:minmax(0,2fr) minmax(270px,1fr);gap:15px;margin-top:16px;align-items:start}",
      ".layout.single{grid-template-columns:minmax(0,1fr)}",
      ".stack{display:grid;gap:15px;min-width:0}",
      ".text-card{background:var(--card-background-color,var(--ha-card-background,#fff));border:1px solid var(--divider-color,#ddd);padding:18px;border-radius:12px;line-height:1.55}",
      ".text-card h2{font-size:17px;font-weight:600;margin:0 0 10px}",
      ".text-card p{font-size:13px;margin:8px 0;color:var(--secondary-text-color,#666)}",
      ".text-card ul{margin:8px 0 0;padding-left:20px;font-size:13px}",
      ".foot{font-size:12px;color:var(--secondary-text-color,#777);margin-top:15px}",
      "@media(max-width:850px){.layout{grid-template-columns:minmax(0,1fr)}.shell{padding:12px}}"
    ].join("\n");
    root.append(style);
    const shell=this._element("div",null,"shell");
    const header=this._element("header",null,"header");
    const title=this._element("div");
    title.append(this._element("h1","Heating","title"));
    title.append(this._element("p","tado X · Integration-managed view","subtitle"));
    header.append(title);
    shell.append(header);
    const tabs=this._element("nav",null,"tabs");
    for(const [name,key] of [["Overview","overview"],["Schedules","schedules"]]){
      const button=this._element("button",name,"tab"+(this._tab===key?" selected":""));
      button.type="button";
      button.setAttribute("aria-current",this._tab===key?"page":"false");
      button.addEventListener("click",()=>this._navigate(key));
      tabs.append(button);
    }
    shell.append(tabs);
    this._connectionStatus=this._element("tado-x-connectivity-status");
    this._connectionStatus.homeId=this._panel?.config?.home_id;
    this._connectionStatus.hass=this._hass;
    shell.append(this._connectionStatus);

    if(this._tab==="overview"){
      const picker=this._element("tado-x-date-range-picker");
      picker.range=this._dateRange;
      picker.addEventListener("date-range-changed",event=>{
        this._dateRange=event.detail;
        for(const card of this._cards){
          if("dateRange" in card)card.dateRange=this._dateRange;
        }
      });
      shell.append(picker);
      const layout=this._element("main",null,"layout");
      const main=this._element("div",null,"stack");
      main.append(this._card("tado-x-settings-history-card",
        "Heating flow, hot water and outside temperature"));
      if(enabled){
        main.append(this._card("tado-x-heating-energy-card",
          "Estimated Vaillant heating-gas allocation by room"));
      }
      layout.append(main);
      const aside=this._element("aside",null,"stack");
      const info=this._element("div",null,"text-card");
      info.append(this._element("h2","Whole-home heating controls"));
      info.append(this._element("p",
        "Use the heating card for Heating Off, Resume Schedules, Eco Boost and Top Boost. Each action requests confirmation. Boost recovery remains scheduled after a Home Assistant restart."));
      const more=this._element("ul");
      for(const item of [
        "Flow adaptation and hot-water temperature are tado X features",
        "Room override status comes from tado room state readback",
        "Heating setpoint charts use Home Assistant Recorder"
      ])more.append(this._element("li",item));
      info.append(more);
      aside.append(info);
      if(enabled){
        const note=this._element("div",null,"text-card");
        note.append(this._element("h2","Optional Vaillant comparison"));
        note.append(this._element("p",
          "The gas-input allocation is specific to installations with configured myPyllant data and radiator capacities. Historical hours reconstructed from daily totals are provisional estimates."));
        aside.append(note);
      }
      layout.append(aside);
      shell.append(layout);
    }else{
      const layout=this._element("main",null,"layout single");
      layout.append(this._card("tado-x-schedule-card",
        "tado X weekly room heating programmes"));
      shell.append(layout);
    }
    shell.append(this._element("p",
      "This sidebar panel updates with HACS. It does not modify existing user-created dashboards, automations or helpers.",
      "foot"));
    root.append(shell);
  }
}
if(!customElements.get("tado-x-managed-heating-panel")){
  customElements.define("tado-x-managed-heating-panel",
    TadoXManagedHeatingPanel);
}
