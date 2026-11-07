const xhTag=name=>name+"-v"+(new URL(import.meta.url).searchParams.get("v")||"dev").replace(/\./g,"-");
const {xhPresetRange}=await import("./x-date-range-picker.js?v="+encodeURIComponent(new URL(import.meta.url).searchParams.get("v")||"dev"));
/* tado X + Vaillant hourly gas-energy allocation dashboard card.
 * Entirely local Recorder reads; no new tado/Vaillant network polls.
 */
class TadoXHeatingEnergyCard extends HTMLElement {
  constructor(){
    super();this.attachShadow({mode:"open"});
    this._hass=null;this._cfg={};this._loaded=false;
    this._busy=false;this._data=null;this._message="";
    this._dateRange=xhPresetRange("week");this._requestId=0;
  }
  setConfig(config){this._cfg=config||{};this._render();}
  set dateRange(range){
    if(!range || (this._dateRange?.start===range.start &&
                   this._dateRange?.end===range.end))return;
    this._dateRange=range;
    if(this._loaded)this._reload();
  }
  set hass(value){
    this._hass=value;
    if(!this._loaded&&value){this._loaded=true;this._reload();}
  }
  getCardSize(){return 6;}
  static getStubConfig(){return {title:"Estimated gas heating by room"};}
  async _call(service,data={}){
    const args={...data};
    if(this._cfg.config_entry)args.config_entry=this._cfg.config_entry;
    const result=await this._hass.callWS({type:"call_service",domain:"tado",
      service,service_data:args,return_response:true});
    return result?.response??result;
  }
  async _reload(){
    if(!this._hass)return;
    const request=++this._requestId;
    this._busy=true;this._render();
    try{
      const args={start_time:this._dateRange.start,end_time:this._dateRange.end};
      const data=await this._call("x_heating_allocation_history",args);
      if(request===this._requestId){this._data=data;this._message="";}
    }catch(e){if(request===this._requestId)
      this._message="Unable to load statistics: "+(e?.message||e);
    }finally{if(request===this._requestId){this._busy=false;this._render();}}
  }
  async _compute(){
    if(this._busy)return;
    this._busy=true;this._message="Checking the past three days of hourly data…";this._render();
    try{
      const result=await this._call("x_compute_heating_allocation",{days:3});
      this._message=(result?.status||"completed")+
        (result?.hours!=null?" — "+result.hours+" new complete hours":"");
    }catch(e){this._message="Recalculation failed: "+(e?.message||e);}
    finally{this._busy=false;this._render();await this._reload();}
  }
  _el(tag,txt,cls){
    const e=document.createElement(tag);if(txt!=null)e.textContent=txt;
    if(cls)e.className=cls;return e;
  }
  _button(text,fn,active){
    const b=this._el("button",text,active?"active":"");
    b.disabled=this._busy;b.addEventListener("click",fn);return b;
  }
  _fmt(n){return (Math.round(n*10)/10).toLocaleString(undefined,{maximumFractionDigits:1});}
  _render(){
    const root=this.shadowRoot;root.replaceChildren();
    const css=this._el("style");
    css.textContent=`
      :host{display:block;font-family:var(--primary-font-family,Roboto,Arial,sans-serif);color:var(--primary-text-color)}
      ha-card{display:block;background:var(--card-background-color,var(--ha-card-background,#fff));border:1px solid var(--divider-color,#ddd);border-radius:12px;padding:16px}
      h2{font-size:19px;font-weight:500;margin:0 0 12px}
      .actions{display:flex;gap:5px;flex-wrap:wrap;margin:8px 0 16px}
      button{background:var(--card-background-color,#fff);color:inherit;padding:7px 10px;border:1px solid var(--divider-color,#aaa);border-radius:6px;cursor:pointer}
      button.active{background:var(--primary-color,#1976d2);border-color:var(--primary-color,#1976d2);color:white}
      button:disabled{opacity:.5;cursor:not-allowed}
      .metric{display:flex;justify-content:space-between;gap:10px;margin:12px 0 18px}
      .metric div{background:var(--secondary-background-color,#eee);border-radius:8px;padding:12px;flex:1}
      .metric strong{display:block;font-size:22px;margin:5px 0}
      .muted{font-size:12px;color:var(--secondary-text-color,#888);line-height:1.5}
      .room{display:grid;grid-template-columns:minmax(95px,1fr) 2fr 74px;gap:8px;align-items:center;padding:6px 0;border-bottom:1px solid var(--divider-color,#eee);font-size:13px}
      .track{height:13px;background:var(--secondary-background-color,#eee);border-radius:9px;overflow:hidden}
      .bar{height:100%;background:var(--primary-color,#1976d2);border-radius:9px}
      .unallocated .bar{background:var(--warning-color,#c38a21)}
      .value{text-align:right;font-variant-numeric:tabular-nums}
      .trend{display:flex;align-items:flex-end;gap:2px;min-height:72px;margin-top:12px;overflow-x:auto}
      .trendbar{flex:1 0 5px;background:var(--primary-color,#1976d2);min-width:5px;border-radius:2px 2px 0 0;opacity:.75}
      .trendbar[title]{cursor:help}.head{margin-top:16px;font-weight:500;font-size:14px}
      .notice{font-size:12px;padding:8px;background:var(--secondary-background-color,#eee);border-radius:6px}
    `;
    root.append(css);const card=this._el("ha-card");
    card.append(this._el("h2",this._cfg.title||"Estimated gas heating by room"));
    if(!this._cfg.shared_date_range){
      const picker=this._el(xhTag("tado-x-date-range-picker"));
      picker.range=this._dateRange;
      picker.addEventListener("date-range-changed",event=>{this.dateRange=event.detail;});
      card.append(picker);
    }
    const actions=this._el("div",null,"actions");
    actions.append(this._button("Refresh",()=>this._reload()));
    actions.append(this._button("Update estimates",()=>this._compute()));
    card.append(actions);
    if(this._data?.series?.length){
      const map=new Map(this._data.rooms.map(name=>[name,0]));
      const periods=this._data.series;
      for(const row of periods){
        for(const name of this._data.rooms){
          map.set(name,map.get(name)+(Number(row[name])||0));
        }
      }
      const ordered=[...map.entries()].sort((a,b)=>b[1]-a[1]);
      const total=ordered.reduce((s,entry)=>s+entry[1],0);
      const unallocated=map.get("Unallocated")||0;
      const allocated=total-unallocated;
      const metric=this._el("div",null,"metric");
      const a=this._el("div");a.append(this._el("span","Allocated to rooms","muted"));
      a.append(this._el("strong",this._fmt(allocated)+" kWh"));metric.append(a);
      const b=this._el("div");b.append(this._el("span","Unallocated","muted"));
      b.append(this._el("strong",this._fmt(unallocated)+" kWh"));metric.append(b);card.append(metric);
      const max=Math.max(...ordered.map(x=>x[1]),1);
      for(const [name,value] of ordered){
        const row=this._el("div",null,"room"+(name==="Unallocated"?" unallocated":""));
        row.append(this._el("span",name));
        const track=this._el("div",null,"track"),bar=this._el("div",null,"bar");
        bar.style.width=Math.max(0,100*value/max)+"%";track.append(bar);row.append(track);
        row.append(this._el("span",this._fmt(value)+" kWh","value"));
        card.append(row);
      }
      card.append(this._el("div","Trends in estimated total heating-gas input","head"));
      const timeline=this._el("div",null,"trend");
      const vals=periods.map(row=>this._data.rooms.reduce((s,name)=>s+(Number(row[name])||0),0));
      const vmax=Math.max(...vals,1);
      periods.forEach((row,index)=>{
        const el=this._el("div",null,"trendbar");
        el.style.height=Math.max(2,72*vals[index]/vmax)+"px";
        el.title=row.period+": "+this._fmt(vals[index])+" kWh";
        timeline.append(el);
      });card.append(timeline);
      card.append(this._el("p",periods[0].period+" to "+periods[periods.length-1].period,"muted"));
    }else{
      card.append(this._el("p","No allocation history is available yet. The hourly job needs Vaillant Gas Heating statistics and Recorder history for all ten tado room demand sensors.","notice"));
    }
    if(this._message)card.append(this._el("p",this._message,"notice"));
    if(this._busy)card.append(this._el("p","Updating…","muted"));
    card.append(this._el("p","Estimated shares of Vaillant heating-gas INPUT, not measured heat delivered to each radiator. Allocation uses actual room heating demand weighted by the installed radiators' EN442 rated output at 75/65/20°C (11 radiators, 10 rooms, total 25.748 kW nominal). This rating is a reference capacity, not actual output at lower water temperatures. Unallocated represents gas input when demand data is missing or no room reports heating demand. Original Vaillant statistics remain unchanged.","muted"));
    root.append(card);
  }
}
// Managed dashboard uses release-scoped component tags; stable names remain
// available to existing user-authored Lovelace cards.
const XH_COMPONENT_VERSION=(new URL(import.meta.url).searchParams.get("v")||"dev").replace(/\./g,"-");
const XH_COMPONENT_TAG="tado-x-heating-energy-card-v"+XH_COMPONENT_VERSION;
if(!customElements.get(XH_COMPONENT_TAG))
  customElements.define(XH_COMPONENT_TAG,class extends TadoXHeatingEnergyCard {});

if(!customElements.get("tado-x-heating-energy-card")) customElements.define("tado-x-heating-energy-card",TadoXHeatingEnergyCard);
window.customCards=window.customCards||[];
window.customCards.push({type:"tado-x-heating-energy-card",
 name:"tado X heating gas allocation",description:"Estimated per-room gas input, using Vaillant and tado Recorder statistics"});
