/* tado X + Vaillant hourly gas-energy allocation dashboard card.
 * Entirely local Recorder reads; no new tado/Vaillant network polls.
 */
class TadoXHeatingEnergyCard extends HTMLElement {
  constructor(){
    super();this.attachShadow({mode:"open"});
    this._hass=null;this._cfg={};this._loaded=false;this._period="month";
    this._anchor=null;this._customStart=null;this._customEnd=null;
    this._busy=false;this._data=null;this._message="";
  }
  setConfig(config){this._cfg=config||{};this._restoreSelection();this._render();}
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
    if(this._busy)return;
    this._busy=true;this._render();
    try{
      const span=this._range();
      if(span.start>span.end)throw Error("The start date must be on or before the end date.");
      this._data=await this._call("x_heating_allocation_history",{
        period:this._period,start_date:span.start,end_date:span.end
      });
      this._message="";
    }catch(e){this._message="Unable to load statistics: "+(e?.message||e);}
    finally{this._busy=false;this._render();}
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

  _storageKey(){
    return "tado-x-consumption-date-range-v1:"+(
      this._cfg.config_entry||"default");
  }
  _today(){
    // Date belongs to the home's Brussels timezone, not the phone's
    // current roaming timezone. Calendar arithmetic below uses UTC
    // calendar dates only (not elapsed 24h intervals across DST).
    const parts=new Intl.DateTimeFormat("en-GB",{
      timeZone:this._hass?.config?.time_zone||"Europe/Brussels",
      year:"numeric",month:"2-digit",day:"2-digit"
    }).formatToParts(new Date());
    const read=k=>parts.find(p=>p.type===k)?.value;
    return read("year")+"-"+read("month")+"-"+read("day");
  }
  _dateParts(iso){return iso.split("-").map(Number);}
  _shiftDays(iso,days){
    const [y,m,d]=this._dateParts(iso);
    return new Date(Date.UTC(y,m-1,d+days)).toISOString().slice(0,10);
  }
  _shiftMonths(iso,months){
    const [y,m,d]=this._dateParts(iso);
    const first=new Date(Date.UTC(y,m-1+months,1));
    const last=new Date(Date.UTC(first.getUTCFullYear(),first.getUTCMonth()+1,0)).getUTCDate();
    return new Date(Date.UTC(first.getUTCFullYear(),first.getUTCMonth(),Math.min(d,last))).toISOString().slice(0,10);
  }
  _firstMonth(iso){
    return iso.slice(0,7)+"-01";
  }
  _endMonth(iso){
    return this._shiftDays(this._shiftMonths(this._firstMonth(iso),1),-1);
  }
  _range(){
    const anchor=this._anchor||this._today();
    let start,end;
    if(this._period==="custom"){
      start=this._customStart||this._firstMonth(anchor);
      end=this._customEnd||this._today();
    }else if(this._period==="day"){start=end=anchor;}
    else if(this._period==="week"){
      const [y,m,d]=this._dateParts(anchor);
      const weekday=new Date(Date.UTC(y,m-1,d)).getUTCDay();
      start=this._shiftDays(anchor,-((weekday+6)%7));
      end=this._shiftDays(start,6);
    }else if(this._period==="month"){
      start=this._firstMonth(anchor);end=this._endMonth(anchor);
    }else if(this._period==="year"){
      const year=anchor.slice(0,4);
      start=year+"-01-01";end=year+"-12-31";
    }else{
      // Trailing 36 calendar months, ending in the anchor month.
      start=this._shiftMonths(this._firstMonth(anchor),-35);
      end=this._endMonth(anchor);
    }
    return {start,end};
  }
  _restoreSelection(){
    try{
      const saved=JSON.parse(window.localStorage.getItem(this._storageKey())||"null");
      if(saved&&["day","week","month","year","3years","custom"].includes(saved.period)){
        this._period=saved.period;
        if(/^\d{4}-\d{2}-\d{2}$/.test(saved.anchor||""))
          this._anchor=saved.anchor;
        if(/^\d{4}-\d{2}-\d{2}$/.test(saved.customStart||""))
          this._customStart=saved.customStart;
        if(/^\d{4}-\d{2}-\d{2}$/.test(saved.customEnd||""))
          this._customEnd=saved.customEnd;
      }
    }catch(_err){/* Browser privacy mode may disable local storage. */}
  }
  _saveSelection(){
    try{
      window.localStorage.setItem(this._storageKey(),JSON.stringify({
        period:this._period,anchor:this._anchor||this._today(),
        customStart:this._customStart,customEnd:this._customEnd
      }));
    }catch(_err){/* Keep the card interactive without persistent storage. */}
  }
  _changePeriod(period){
    if(this._busy)return;
    this._period=period;this._anchor=this._anchor||this._today();
    if(period==="custom"){
      const span=this._range();
      this._customStart=this._customStart||this._firstMonth(this._anchor);
      this._customEnd=this._customEnd||this._today();
    }
    this._saveSelection();this._reload();
  }
  _movePeriod(direction){
    if(this._busy)return;
    const anchor=this._anchor||this._today();
    if(this._period==="custom"){
      const span=this._range();
      const [sy,sm,sd]=this._dateParts(span.start);
      const [ey,em,ed]=this._dateParts(span.end);
      const length=Math.round((
        Date.UTC(ey,em-1,ed)-Date.UTC(sy,sm-1,sd))/86400000)+1;
      this._customStart=this._shiftDays(span.start,direction*length);
      this._customEnd=this._shiftDays(span.end,direction*length);
    }else{
      const steps={
        day:()=>this._shiftDays(anchor,direction),
        week:()=>this._shiftDays(anchor,direction*7),
        month:()=>this._shiftMonths(anchor,direction),
        year:()=>this._shiftMonths(anchor,direction*12),
        "3years":()=>this._shiftMonths(anchor,direction*36)
      };
      this._anchor=steps[this._period]();
    }
    this._saveSelection();this._reload();
  }
  _jumpToDate(iso){
    if(!/^\d{4}-\d{2}-\d{2}$/.test(iso))return;
    this._anchor=iso;this._saveSelection();this._reload();
  }
  _customDate(which,iso){
    if(!/^\d{4}-\d{2}-\d{2}$/.test(iso))return;
    if(which==="start")this._customStart=iso;
    else this._customEnd=iso;
    this._saveSelection();
    if(this._range().start>this._range().end){
      this._message="Start date must be on or before end date.";
      this._render();return;
    }
    this._reload();
  }
  _dateNavigation(){
    const nav=this._el("div",null,"date-navigation");
    const span=this._range(),today=this._today();
    const prev=this._button("‹",()=>this._movePeriod(-1));
    prev.setAttribute("aria-label","Previous period");
    nav.append(prev);
    const title=this._el("strong",this._period==="day"?span.start:
      span.start+" — "+(span.end>today?today:span.end),"period-label");
    nav.append(title);
    const next=this._button("›",()=>this._movePeriod(1));
    next.setAttribute("aria-label","Next period");
    next.disabled=this._busy||span.end>=today;
    nav.append(next);
    const jump=this._el("div",null,"date-pickers");
    if(this._period==="custom"){
      for(const [text,key,value] of [
        ["From","start",span.start],["To","end",span.end]
      ]){
        const label=this._el("label",text);
        const input=this._el("input");
        input.type="date";input.value=value;input.max=today;
        input.disabled=this._busy;
        input.addEventListener("change",()=>this._customDate(key,input.value));
        label.append(input);jump.append(label);
      }
    }else{
      const label=this._el("label","Jump to date");
      const input=this._el("input");input.type="date";
      input.value=this._anchor||today;input.max=today;
      input.disabled=this._busy;
      input.addEventListener("change",()=>this._jumpToDate(input.value));
      label.append(input);jump.append(label);
    }
    const current=this._button("Current",()=>{
      if(this._period==="custom"){
        this._customEnd=today;
        this._customStart=this._firstMonth(today);
      }else this._anchor=today;
      this._saveSelection();this._reload();
    });
    jump.append(current);
    const wrap=this._el("div",null,"calendar-nav");
    wrap.append(nav,jump);
    return wrap;
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
    const actions=this._el("div",null,"actions");
    for(const [key,label] of [["day","24 hours"],["week","Week"],["month","Month"],["year","Year"],["3years","3 years"]]){
      actions.append(this._button(label,()=>{this._period=key;this._reload();},this._period===key));
    }
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
if(!customElements.get("tado-x-heating-energy-card")) customElements.define("tado-x-heating-energy-card",TadoXHeatingEnergyCard);
window.customCards=window.customCards||[];
window.customCards.push({type:"tado-x-heating-energy-card",
 name:"tado X heating gas allocation",description:"Estimated per-room gas input, using Vaillant and tado Recorder statistics"});
