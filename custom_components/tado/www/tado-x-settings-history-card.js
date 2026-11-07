/* Long-term tado X settings chart, using locally recorded HA statistics.
 * Detects entities from their unique suffixes, no hard-coded home-specific IDs.
 * Built-in number/switch/select more-info dialog provides editing controls.
 */
const XH_SOURCES = [
 {id:"maxflow",title:"Maximum flow",match:"Maximum flow temperature history",control:"Maximum heating flow temperature",domain:"number",unit:"°C",color:"#0968ae"},
 {id:"optimised",title:"tado optimised flow",match:"Optimised heating flow limit",control:null,domain:"sensor",unit:"°C",color:"#16a087"},
 {id:"dhw",title:"Hot-water target",match:"DHW target temperature history",control:"DHW target temperature",domain:"number",unit:"°C",color:"#d5841f"},
 {id:"adapted",title:"Automatic flow adaptation",match:"Flow adaptation enabled percentage",control:"Automatic flow temperature adaptation",domain:"switch",unit:"%"}
];
const XH_OUTDOOR={id:"outdoor",title:"Outside temperature",domain:"sensor",unit:"°C",color:"#8363b9"};
const XH_EXTRA=[{title:"DHW mode",match:"DHW operating mode",domain:"select"}];
const XH_PERIODS=[
  {key:"day",label:"24h",days:1,period:"hour"},
  {key:"week",label:"7 days",days:7,period:"hour"},
  {key:"month",label:"90 days",days:90,period:"day"},
  {key:"year",label:"1 year",days:366,period:"month"},
  {key:"3years",label:"3 years",days:1097,period:"month"},
];
class TadoXSettingsHistoryCard extends HTMLElement {
  constructor(){
    super();this.attachShadow({mode:"open"});this._cfg={};
    this._hass=null;this._once=false;this._period="week";
    this._series={};this._busy=false;this._message="";
    this._hidden=new Set();
  }
  setConfig(cfg){this._cfg=cfg||{};this._render();}
  set hass(hass){
    this._hass=hass;
    if(!this._once && hass){this._once=true;this._load();}
    else if(!this._busy){this._render();}
  }
  getCardSize(){return 9;}
  static getStubConfig(){return {title:"Flow, hot water and outside temperature history"};}
  _find(name,domain){
    if(!this._hass)return null;
    const candidates=Object.entries(this._hass.states)
      .filter(([eid,s])=>!domain||eid.startsWith(domain+"."))
      .filter(([eid,s])=>{
        const title=(s.attributes?.friendly_name||"").toLowerCase().trim();
        return title.endsWith(name.toLowerCase()) ||
          eid.split(".")[1]?.endsWith(name.toLowerCase().replace(/[^a-z0-9]+/g,"_"));
      });
    return candidates.length===1?candidates[0][0]:null;
  }
  _state(name,domain){return this._find(name,domain);}
  _showMore(id){
    if(!id)return;
    this.dispatchEvent(new CustomEvent("hass-more-info",{
      bubbles:true,composed:true,detail:{entityId:id},
    }));
  }
  async _load(){
    if(this._busy||!this._hass)return;
    this._busy=true;this._render();
    try{
      const ids=[...new Set([
        ...XH_SOURCES.map(x=>this._state(x.match,"sensor")).filter(Boolean),
        this._outdoorId(),
      ].filter(Boolean))];
      if(!ids.length)throw Error("No historical temperature sensors found. Update the tado X integration and restart Home Assistant.");
      const range=XH_PERIODS.find(x=>x.key===this._period);
      const end=new Date(),start=new Date(end.getTime()-range.days*86400000);
      const result=await this._hass.callWS({
        type:"recorder/statistics_during_period",
        start_time:start.toISOString(),end_time:end.toISOString(),
        statistic_ids:ids,period:range.period,
        types:["mean","min","max"],
      });
      this._series=result||{};this._message="";
    }catch(e){this._message="History unavailable: "+(e?.message||e);this._series={};}
    finally{this._busy=false;this._render();}
  }
  _el(tag,text,cls){
    const node=document.createElement(tag);
    if(text!=null)node.textContent=text;
    if(cls)node.className=cls;
    return node;
  }
  _button(label,fn,active=false){
    const b=this._el("button",label,active?"active":"");b.disabled=this._busy;
    b.addEventListener("click",fn);return b;
  }
  _round(v){return Number.isFinite(v)?Number(v).toLocaleString(undefined,{maximumFractionDigits:1}):"—";}

  _outdoorId(){
    if(!this._hass)return null;
    if(this._cfg.outdoor_entity){
      return this._hass.states[this._cfg.outdoor_entity]
        ? this._cfg.outdoor_entity : null;
    }
    const ranked=Object.entries(this._hass.states)
      .filter(([id,st])=>id.startsWith("sensor.") &&
        Number.isFinite(Number(st.state)) &&
        (st.attributes?.device_class==="temperature" ||
         /°c|celsius/i.test(st.attributes?.unit_of_measurement||"")))
      .map(([id,st])=>{
        const label=(st.attributes?.friendly_name||id).toLowerCase();
        const key=id.toLowerCase();
        if(!/outdoor|outside|garden temperature|weather temperature/.test(label+" "+key))
          return null;
        const platform=this._hass.entities?.[id]?.platform;
        const score=(platform==="tado"?100:0)
          +(key.includes("tado")?80:0)
          +(label.includes("outdoor temperature")?30:0)
          +(label.includes("outside temperature")?25:0)
          +(key.includes("vaillant")?10:0);
        return {id,score};
      }).filter(Boolean).sort((a,b)=>b.score-a.score || a.id.localeCompare(b.id));
    return ranked[0]?.id||null;
  }
  _sensorId(source){
    return source.id==="outdoor"?this._outdoorId():this._state(source.match,"sensor");
  }
  _rows(source){
    const id=this._sensorId(source),rows=id?this._series[id]:null;
    return (Array.isArray(rows)?rows:[])
      .filter(row=>Number.isFinite(Number(row.start)) &&
        Number.isFinite(Number(row.mean)))
      .map(row=>({x:Number(row.start),y:Number(row.mean)}))
      .sort((a,b)=>a.x-b.x);
  }
  _formatValue(id,unit){
    const raw=id?this._hass?.states?.[id]?.state:null;
    if(raw==="on")return "On";
    if(raw==="off")return "Off";
    const val=raw!=null?Number(raw):NaN;
    return Number.isFinite(val)?this._round(val)+(unit?" "+unit:""):"Unavailable";
  }
  _tile(label,id,unit,detail){
    const tile=this._el("button",null,"setting-tile");
    tile.disabled=!id;
    tile.append(this._el("span",label,"tile-label"));
    tile.append(this._el("strong",this._formatValue(id,unit),"tile-value"));
    if(detail)tile.append(this._el("small",detail,"tile-note"));
    tile.addEventListener("click",()=>this._showMore(id));
    return tile;
  }
  _dateLabel(ts){
    const opts=this._period==="day"?{hour:"2-digit",minute:"2-digit"}:
      (this._period==="year"||this._period==="3years")
        ?{month:"short",year:"2-digit"}:{day:"numeric",month:"short"};
    return new Date(ts).toLocaleString(undefined,opts);
  }
  _combinedChart(){
    const wrap=this._el("section",null,"plot");
    wrap.append(this._el("h3","Temperature trends","plot-title"));
    const sources=[XH_SOURCES[0],XH_SOURCES[1],XH_SOURCES[2],XH_OUTDOOR];
    const legend=this._el("div",null,"legend");
    for(const src of sources){
      const id=this._sensorId(src),rows=this._rows(src);
      const active=!this._hidden.has(src.id);
      const btn=this._button(src.title,()=>{
        if(this._hidden.has(src.id))this._hidden.delete(src.id);
        else this._hidden.add(src.id);
        this._render();
      },active);
      btn.className="legend-item"+(active?" selected":"");
      btn.disabled=!id && !rows.length;
      btn.setAttribute("aria-pressed",String(active));
      const dot=this._el("i",null,"legend-dot");dot.style.background=src.color;
      btn.prepend(dot);legend.append(btn);
    }
    wrap.append(legend);
    const visible=sources.filter(src=>!this._hidden.has(src.id))
      .map(src=>({src,rows:this._rows(src)})).filter(item=>item.rows.length);
    if(!visible.length){
      wrap.append(this._el("p","No recorded temperatures for these lines yet. Historical settings begin when the sensors were installed.","note"));
      return wrap;
    }
    const period=XH_PERIODS.find(p=>p.key===this._period);
    const maxTime=Date.now(),minTime=maxTime-period.days*86400000;
    const values=visible.flatMap(i=>i.rows.map(p=>p.y));
    let low=Math.floor((Math.min(...values)-2)/5)*5;
    let high=Math.ceil((Math.max(...values)+2)/5)*5;
    if(high-low<10){low-=5;high+=5;}
    const width=460,height=230,left=38,right=12,top=14,bottom=32;
    const xp=ts=>left+Math.max(0,Math.min(1,(ts-minTime)/(maxTime-minTime)))*(width-left-right);
    const yp=val=>top+(high-val)/(high-low)*(height-top-bottom);
    const ns="http://www.w3.org/2000/svg";
    const svgElement=(tag,attrs={})=>{
      const node=document.createElementNS(ns,tag);
      for(const [key,value] of Object.entries(attrs))node.setAttribute(key,String(value));
      return node;
    };
    const svg=svgElement("svg",{viewBox:"0 0 "+width+" "+height,role:"img",
      "aria-label":"Historical maximum flow, optimised flow, hot-water and outside temperatures"});
    for(let step=0;step<=5;step++){
      const value=low+(high-low)*step/5,y=yp(value);
      svg.append(svgElement("line",{x1:left,x2:width-right,y1:y,y2:y,
        stroke:"var(--divider-color,#ddd)","stroke-width":1}));
      const lab=svgElement("text",{x:left-6,y:y+4,"text-anchor":"end",
        fill:"var(--secondary-text-color,#777)","font-size":12});
      lab.textContent=this._round(value);svg.append(lab);
    }
    for(const [when,anchor] of [
      [minTime,"start"],[(minTime+maxTime)/2,"middle"],[maxTime,"end"]
    ]){
      const label=svgElement("text",{x:xp(when),y:height-5,"text-anchor":anchor,
        fill:"var(--secondary-text-color,#777)","font-size":11});
      label.textContent=this._dateLabel(when);svg.append(label);
    }
    for(const item of visible){
      const maxGap=period.period==="hour"?4*3600000:
        period.period==="day"?4*86400000:65*86400000;
      let segment=[],previous=null;
      const segments=[];
      for(const p of item.rows){
        if(p.x<minTime||p.x>maxTime)continue;
        if(previous!==null&&p.x-previous>maxGap&&segment.length){
          segments.push(segment);segment=[];
        }
        segment.push(p);previous=p.x;
      }
      if(segment.length)segments.push(segment);
      for(const points of segments){
        if(points.length>1){
          svg.append(svgElement("polyline",{
            points:points.map(p=>xp(p.x)+","+yp(p.y)).join(" "),
            fill:"none",stroke:item.src.color,"stroke-width":2.8,
            "stroke-linecap":"round","stroke-linejoin":"round"
          }));
        }
        if(points.length<=95){
          for(const p of points){
            const circle=svgElement("circle",{
              cx:xp(p.x),cy:yp(p.y),r:2.8,fill:item.src.color
            });
            const title=svgElement("title");
            title.textContent=item.src.title+": "+this._round(p.y)+
              " °C — "+new Date(p.x).toLocaleString();
            circle.append(title);svg.append(circle);
          }
        }
      }
    }
    wrap.append(svg);
    const outside=this._outdoorId();
    const source=outside?
      (this._hass.states[outside]?.attributes?.friendly_name||outside)+" ("+outside+")":
      this._cfg.outdoor_entity?
        "Configured sensor "+this._cfg.outdoor_entity+" was not found":
        "No suitable outside temperature sensor found";
    wrap.append(this._el("p","Outside source: "+source+
      ". Tap a legend item to hide or show a temperature line.","note"));
    return wrap;
  }
  _render(){
    const root=this.shadowRoot;root.replaceChildren();
    const style=this._el("style");
    style.textContent=`
      :host{display:block;font-family:var(--primary-font-family,Roboto,Arial,sans-serif);color:var(--primary-text-color)}
      ha-card{display:block;background:var(--card-background-color,var(--ha-card-background,#fff));border:1px solid var(--divider-color,#ddd);border-radius:12px;padding:16px}
      h2{font-size:19px;font-weight:500;margin:0 0 10px}
      .tabs,.controls{display:flex;gap:6px;flex-wrap:wrap;margin:12px 0}
      button{border:1px solid var(--divider-color,#aaa);background:var(--card-background-color,#fff);color:inherit;border-radius:6px;padding:7px 10px;cursor:pointer}
      button.active{background:var(--primary-color,#1976d2);color:white;border-color:var(--primary-color,#1976d2)}
      button:disabled{opacity:.6}.controls button{flex:1 1 160px;text-align:left}
      .controls strong{display:block;margin-top:5px;font-size:18px;font-variant-numeric:tabular-nums}
      .graphs{display:grid;grid-template-columns:repeat(auto-fit,minmax(245px,1fr));gap:12px;margin:10px 0}
      .plot{border:1px solid var(--divider-color,#ddd);padding:10px;border-radius:8px;min-width:0}
      .plot-title{font-size:13px;font-weight:500}
      .value{font-size:20px;font-weight:600;margin:6px 0}
      .plot svg{width:100%;height:auto}
      .note{font-size:12px;color:var(--secondary-text-color,#888);line-height:1.5}
      .message{padding:8px;background:var(--secondary-background-color,#eee);border-radius:6px}
    `;
    root.append(style);const card=this._el("ha-card");
    card.append(this._el("h2",this._cfg.title||"Hot-water and heating optimisation"));
    const controls=this._el("div",null,"controls");
    for(const s of [...XH_SOURCES.filter(s=>s.control),...XH_EXTRA]){
      const domain=s.domain || (s.id==="adapted"?"switch":"number");
      const id=this._state(s.control||s.match,domain);
      const state=id?this._hass.states[id]?.state:null;
      const b=this._button(s.title||s.control,()=>this._showMore(id));
      b.disabled=this._busy||!id;
      const val=this._el("strong",state!=null?
        (state==="on"?"On":state==="off"?"Off":state+(s.unit?" "+s.unit:"")):"Unavailable");
      b.append(val);controls.append(b);
    }
    card.append(controls);
    const tabs=this._el("div",null,"tabs");
    for(const d of XH_PERIODS){
      tabs.append(this._button(d.label,()=>{this._period=d.key;this._load();},this._period===d.key));
    }
    tabs.append(this._button("Refresh",()=>this._load()));card.append(tabs);
    const charts=this._el("div",null,"graphs");
    for(const source of XH_SOURCES)charts.append(this._chart(source));
    card.append(charts);
    if(this._message)card.append(this._el("p",this._message,"message"));
    if(this._busy)card.append(this._el("p","Reading Home Assistant history…","note"));
    card.append(this._el("p","Tap a current-setting tile to open its native Home Assistant control. Graphs show historical hourly/daily/monthly average settings; DHW and flow values are targets, not actual water temperatures. The adaptation-enabled graph shows approximate percentage of time enabled. History starts only after the new sensors were installed and Recorder began collecting them.","note"));
    root.append(card);
  }
}
customElements.define("tado-x-settings-history-card",TadoXSettingsHistoryCard);
window.customCards=window.customCards||[];
window.customCards.push({type:"tado-x-settings-history-card",
  name:"tado X hot-water and flow history",
  description:"Automatic entity discovery and long-term HA Recorder charts for DHW and OpenTherm optimisation"});
