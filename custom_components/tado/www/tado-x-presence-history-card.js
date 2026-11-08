/* Read-only whole-home presence comparison.
 * Uses HA Recorder state history, not numerical long-term statistics.
 * Shared Tado X date range is passed by the managed Heating dashboard.
 */
const XHP_VERSION=(new URL(import.meta.url).searchParams.get("v")||"dev");
const XHP_TAG="tado-x-presence-history-card-v"+XHP_VERSION.replace(/\./g,"-");
const {xhPresetRange}=await import("./x-date-range-picker.js?v="+encodeURIComponent(XHP_VERSION));

const XHP_COLORS={home:"#218657",away:"#d38221",auto:"#5371b8",
  unknown:"#949ba4",unavailable:"#949ba4"};
const xhpLabel=value=>(value==="home"?"Home":value==="away"?"Away":
  value==="auto"?"Auto":value==="unavailable"?"Unavailable":"Unknown");
const xhpState=value=>{
  const v=String(value??"unknown").toLowerCase();
  return Object.hasOwn(XHP_COLORS,v)?v:"unknown";
};
const xhpEpoch=entry=>{
  const value=entry.lu??entry.lc??entry.last_changed??entry.last_updated;
  if(typeof value==="number")return value<1e11?value*1000:value;
  const ts=Date.parse(value);
  return Number.isFinite(ts)?ts:NaN;
};

class TadoXPresenceHistoryCard extends HTMLElement {
  constructor(){
    super();this.attachShadow({mode:"open"});
    this._cfg={};this._hass=null;this._range=xhPresetRange("week");
    this._history={};this._busy=false;this._error="";
    this._request=0;this._loadedIds="";this._liveKey="";
  }
  setConfig(config){this._cfg=config||{};this._render();}
  set dateRange(range){
    if(!range||(range.start===this._range.start&&range.end===this._range.end))return;
    this._range=range;
    if(this.isConnected)this._load();
  }
  set hass(value){
    const firstLocale=!this._hass && value;
    this._hass=value;
    if(firstLocale && !this._cfg.shared_date_range && this._range?.preset==="week")
      this._range=xhPresetRange("week",new Date(),value);
    if(this._picker?.isConnected)this._picker.hass=value;
    if(!this.isConnected||!value)return;
    const sources=this._sources();
    const ids=sources.filter(s=>s.id).map(s=>s.id).sort().join(",");
    const live=JSON.stringify(sources.map(s=>[s.id,value.states[s.id]?.state]));
    if(ids!==this._loadedIds){this._load();return;}
    if(live!==this._liveKey){this._liveKey=live;this._render();this._load();}
  }
  connectedCallback(){
    this._render();
    if(this._hass)this._load();
  }
  _el(tag,value,cls){
    const el=document.createElement(tag);
    if(value!==undefined&&value!==null)el.textContent=String(value);
    if(cls)el.className=cls;
    return el;
  }
  _entityInHome(state){
    const home=this._cfg.home_id;
    return !home||String(state?.attributes?.tado_home_id)===String(home);
  }
  _sources(){
    const states=this._hass?.states||{};
    let control=Object.entries(states).filter(([id,s])=>
      id.startsWith("select.") &&
      s.attributes?.presence_scope==="selected" && this._entityInHome(s));
    if(control.length!==1){
      // Older installed selectors may lack our new metadata.
      const candidates=Object.entries(states).filter(([id,s])=>
        id.startsWith("select.") &&
        JSON.stringify(s.attributes?.options||[])===
        JSON.stringify(["Home","Away","Auto"]) &&
        (!s.attributes?.tado_home_id||this._entityInHome(s)));
      control=candidates.length===1?candidates:[];
    }
    let effective=Object.entries(states).filter(([id,s])=>
      id.startsWith("sensor.") &&
      s.attributes?.presence_scope==="effective"&&this._entityInHome(s));
    if(effective.length!==1){
      effective=states["sensor.tado_x_effective_presence"]?
        [["sensor.tado_x_effective_presence",states["sensor.tado_x_effective_presence"]]]:[];
    }
    return [
      {key:"control",label:"Tado selected mode",id:control[0]?.[0]||null},
      {key:"effective",label:"Tado effective presence",id:effective[0]?.[0]||null},
      {key:"household",label:"HA Home Presence",
       id:states["sensor.home_presence"]?"sensor.home_presence":null},
    ];
  }
  _start(){return new Date(this._range.start).getTime();}
  _end(){return Math.min(new Date(this._range.end).getTime(),Date.now());}
  async _load(){
    if(!this._hass?.callWS||!this.isConnected)return;
    const req=++this._request;
    const sources=this._sources();
    const ids=[...new Set(sources.map(s=>s.id).filter(Boolean))];
    this._loadedIds=ids.slice().sort().join(",");
    this._liveKey=JSON.stringify(sources.map(s=>[s.id,this._hass.states[s.id]?.state]));
    if(!ids.length){this._history={};this._error="";this._render();return;}
    const start=this._start(),end=this._end();
    if(!Number.isFinite(start)||!Number.isFinite(end)||start>=end){
      this._history={};this._error="";this._render();return;
    }
    this._busy=true;this._render();
    try{
      const result=await this._hass.callWS({
        type:"history/history_during_period",
        start_time:new Date(start).toISOString(),
        end_time:new Date(end).toISOString(),
        entity_ids:ids,include_start_time_state:true,
        significant_changes_only:true,minimal_response:true,no_attributes:true
      });
      if(req!==this._request)return;
      this._history=result&&typeof result==="object"?result:{};
      this._error="";
    }catch(error){
      if(req!==this._request)return;
      this._history={};
      this._error="Recorder state history unavailable: "+(error?.message||String(error));
    }finally{
      if(req===this._request){this._busy=false;this._render();}
    }
  }
  _segments(source){
    if(!source.id)return [];
    const rows=this._history[source.id];
    if(!Array.isArray(rows)||!rows.length)return [];
    const start=this._start(),end=this._end();
    const events=rows.map(row=>({
      at:xhpEpoch(row),state:xhpState(row.s??row.state)
    })).filter(x=>Number.isFinite(x.at)&&x.at<=end)
      .sort((a,b)=>a.at-b.at);
    const changes=[];
    for(const entry of events){
      if(!changes.length||changes[changes.length-1].state!==entry.state)
        changes.push(entry);
    }
    const segments=[];
    for(let i=0;i<changes.length;i++){
      const event=changes[i];
      const from=Math.max(start,event.at);
      const to=Math.min(end,changes[i+1]?.at??end);
      if(to>from)segments.push({start:from,end:to,state:event.state});
    }
    return segments;
  }
  _showMore(id){
    if(!id)return;
    this.dispatchEvent(new CustomEvent("hass-more-info",{
      bubbles:true,composed:true,detail:{entityId:id}
    }));
  }
  _nowTile(source){
    const state=source.id?this._hass?.states[source.id]?.state:null;
    const tile=this._el("button",null,"now-tile");
    tile.type="button";tile.disabled=!source.id;
    tile.append(this._el("span",source.label,"tile-label"));
    const value=this._el("strong",source.id?xhpLabel(xhpState(state)):"Not available","tile-value");
    if(source.id)value.style.color=XHP_COLORS[xhpState(state)];
    tile.append(value);
    tile.append(this._el("small",source.id||"Entity not found","entity-id"));
    tile.addEventListener("click",()=>this._showMore(source.id));
    return tile;
  }
  _track(source,start,end){
    const row=this._el("div",null,"track-row");
    const head=this._el("div",null,"track-head");
    head.append(this._el("strong",source.label));
    head.append(this._el("small",source.id||"Not configured"));
    row.append(head);
    const track=this._el("div",null,"track");
    if(!source.id){
      track.append(this._el("span","Not available","track-empty"));
    }else{
      const segments=this._segments(source);
      if(!segments.length)track.append(this._el("span","No recorded states","track-empty"));
      for(const segment of segments){
        const piece=this._el("div",null,"segment");
        piece.style.left=((segment.start-start)/(end-start)*100)+"%";
        piece.style.width=((segment.end-segment.start)/(end-start)*100)+"%";
        piece.style.background=XHP_COLORS[segment.state];
        piece.title=xhpLabel(segment.state)+" · "+
          new Date(segment.start).toLocaleString()+" – "+
          new Date(segment.end).toLocaleString();
        piece.setAttribute("aria-label",piece.title);
        if((segment.end-segment.start)/(end-start)>0.13)
          piece.append(this._el("span",xhpLabel(segment.state)));
        track.append(piece);
      }
    }
    row.append(track);return row;
  }
  _events(sources){
    const start=this._start(),end=this._end();
    const entries=[];
    for(const source of sources){
      const rows=this._history[source.id];
      if(!Array.isArray(rows))continue;
      let prev=null;
      for(const item of rows.map(r=>({at:xhpEpoch(r),state:xhpState(r.s??r.state)}))
        .filter(r=>Number.isFinite(r.at)&&r.at<=end).sort((a,b)=>a.at-b.at)){
        if(prev?.state===item.state)continue;
        if(item.at>=start&&prev!==null)
          entries.push({at:item.at,label:source.label,from:prev.state,to:item.state});
        prev=item;
      }
    }
    entries.sort((a,b)=>b.at-a.at);
    const details=this._el("details",null,"events");
    const summary=this._el("summary","Transitions in selected period ("+entries.length+")");
    details.append(summary);
    if(!entries.length)details.append(this._el("p","No recorded transitions in this period.","note"));
    for(const event of entries.slice(0,100)){
      const row=this._el("div",null,"event");
      row.append(this._el("time",new Date(event.at).toLocaleString()));
      row.append(this._el("span",event.label));
      row.append(this._el("strong",xhpLabel(event.from)+" → "+xhpLabel(event.to)));
      details.append(row);
    }
    if(entries.length>100)
      details.append(this._el("p","Showing latest 100 transitions; use a shorter date range.","note"));
    return details;
  }
  _render(){
    if(!this.isConnected)return;
    const root=this.shadowRoot;root.replaceChildren();
    const style=this._el("style");
    style.textContent=`
:host{display:block;min-width:0;color:var(--primary-text-color);font:inherit}
*{box-sizing:border-box}
.card{background:var(--card-background-color,var(--ha-card-background,#fff));border:1px solid var(--divider-color,#ddd);border-radius:13px;padding:17px;min-width:0}
h2{font-size:19px;margin:0 0 4px}
.note{color:var(--secondary-text-color,#777);font-size:12px;line-height:1.5;margin:12px 0 0}
.status{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:9px;margin:14px 0}
.now-tile{background:var(--secondary-background-color,#f4f4f4);border:1px solid var(--divider-color,#ddd);border-radius:10px;padding:10px;text-align:left;cursor:pointer;font:inherit;color:inherit;min-width:0}
.now-tile:disabled{cursor:default;opacity:.7}
.tile-label,.entity-id{display:block;font-size:12px;color:var(--secondary-text-color,#666);overflow-wrap:anywhere}
.tile-value{display:block;margin:6px 0;font-size:20px}
.chart{margin:14px 0 0}
.track-row{display:grid;grid-template-columns:160px minmax(0,1fr);align-items:center;gap:10px;margin:11px 0}
.track-head{font-size:12px;min-width:0}
.track-head small{display:block;margin-top:3px;color:var(--secondary-text-color,#666);font-size:10px;overflow-wrap:anywhere}
.track{height:34px;background:var(--secondary-background-color,#eee);border-radius:6px;position:relative;overflow:hidden}
.segment{position:absolute;top:0;height:100%;color:#fff;min-width:1px;display:flex;align-items:center;justify-content:center;font-size:11px;white-space:nowrap;overflow:hidden;letter-spacing:.1px}
.track-empty{position:absolute;left:9px;top:9px;font-size:12px;color:var(--secondary-text-color,#666)}
.axis{display:flex;justify-content:space-between;gap:10px;margin:8px 0 0 170px;font-size:11px;color:var(--secondary-text-color,#777)}
.legend{display:flex;gap:14px;flex-wrap:wrap;margin-top:14px;font-size:12px}
.legend-item{display:inline-flex;align-items:center;gap:5px}
.swatch{width:10px;height:10px;border-radius:3px}
.events{margin:16px 0 0;border-top:1px solid var(--divider-color,#ddd);padding-top:12px;font-size:12px}
.events summary{cursor:pointer;font-weight:600}
.event{display:grid;grid-template-columns:minmax(110px,1fr) minmax(100px,1fr) auto;gap:8px;padding:8px 0;border-bottom:1px solid var(--divider-color,#ddd);align-items:center}
.event time{color:var(--secondary-text-color,#777)}
.alert{color:var(--error-color,#b33);font-size:12px;margin:10px 0}
@media(max-width:700px){.card{padding:12px}.status{grid-template-columns:1fr}.track-row{grid-template-columns:1fr;gap:4px}.track-head small{display:inline;margin-left:8px}.axis{margin-left:0}.event{grid-template-columns:1fr 1fr}.event strong{grid-column:1/-1}}
`;
    root.append(style);
    const card=this._el("section",null,"card");
    card.append(this._el("h2",this._cfg.title||"Home and Away presence history"));
    card.append(this._el("p","Tado's selected control mode, effective presence, and Home Assistant household presence side by side.","note"));
    if(!this._cfg.shared_date_range){
      const picker=this._el("tado-x-date-range-picker-v"+XHP_VERSION.replace(/\./g,"-"));
      picker.range=this._range;
      picker.hass=this._hass;
      this._picker=picker;
      picker.addEventListener("date-range-changed",e=>{this.dateRange=e.detail;});
      card.append(picker);
    }
    const sources=this._sources();
    const now=this._el("div",null,"status");
    for(const source of sources)now.append(this._nowTile(source));
    card.append(now);
    const control=this._hass?.states[sources[0].id]?.state;
    const actual=this._hass?.states[sources[1].id]?.state;
    const home=this._hass?.states[sources[2].id]?.state;
    if(xhpState(actual)!=="unknown"&&xhpState(home)!=="unknown"&&
       xhpState(actual)!==xhpState(home))
      card.append(this._el("p","Tado and Home Assistant currently disagree about household presence.","alert"));
    const start=this._start(),end=this._end();
    if(Number.isFinite(start)&&Number.isFinite(end)&&end>start){
      const chart=this._el("div",null,"chart");
      for(const source of sources)chart.append(this._track(source,start,end));
      const axis=this._el("div",null,"axis");
      axis.append(this._el("span",new Date(start).toLocaleString()));
      axis.append(this._el("span",new Date(end).toLocaleString()));
      chart.append(axis);card.append(chart);
    }
    const legend=this._el("div",null,"legend");
    for(const key of ["home","away","auto","unknown"]){
      const item=this._el("span",null,"legend-item");
      const swatch=this._el("i",null,"swatch");
      swatch.style.background=XHP_COLORS[key];
      item.append(swatch,this._el("span",xhpLabel(key)));
      legend.append(item);
    }
    card.append(legend);
    if(this._busy)card.append(this._el("p","Loading historical states…","note"));
    if(this._error)card.append(this._el("p",this._error,"alert"));
    card.append(this._events(sources));
    card.append(this._el("p","Read-only. Historical states come from Home Assistant Recorder; entities must not be excluded from Recorder. No history is backfilled before an entity was created. Unknown periods are not counted as Home or Away.","note"));
    root.append(card);
  }
}
if(!customElements.get(XHP_TAG))
  customElements.define(XHP_TAG,class extends TadoXPresenceHistoryCard{});
if(!customElements.get("tado-x-presence-history-card"))
  customElements.define("tado-x-presence-history-card",TadoXPresenceHistoryCard);
