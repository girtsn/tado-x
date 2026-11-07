/* Integration-managed tado X Heating panel.
 * Registered in HA's sidebar by panel_custom, no Lovelace YAML or
 * manual JS Resources configuration needed. Bundled JS cards are loaded
 * from the same integration's static routes on each HACS update.
 */
import "./x-settings-history-card.js";
import "./x-schedule-card.js";
import "./x-heating-energy-card.js";

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
  }
  set hass(value){
    this._hass=value;
    if(!this._initialized && value){
      this._render();
    }else{
      const enabled=this._energyEnabled();
      if(enabled!==this._lastEnergy && this._tab==="overview"){
        this._render();
      }else{
        for(const card of this._cards)card.hass=value;
      }
    }
  }
  set panel(value){
    const oldId=this._panel?.config?.config_entry;
    this._panel=value;
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
    if(this._hass && !this._initialized)this._render();
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
    el.setConfig({title,config_entry:this._panel?.config?.config_entry});
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
    const enabled=this._energyEnabled();
    this._lastEnergy=enabled;
    this._initialized=true;
    this._cards=[];
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

    if(this._tab==="overview"){
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
