const xhTag=name=>name+"-v"+(new URL(import.meta.url).searchParams.get("v")||"dev").replace(/\./g,"-");
const XH_CARD_ASSET_VERSION=encodeURIComponent(new URL(import.meta.url).searchParams.get("v")||"dev");
const {xhPresetRange}=await import("./x-date-range-picker.js?v="+XH_CARD_ASSET_VERSION);
await import("./x-connectivity-status.js?v="+XH_CARD_ASSET_VERSION);
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

class TadoXSettingsHistoryCard extends HTMLElement {
  constructor(){
    super();this.attachShadow({mode:"open"});this._cfg={};
    this._hass=null;this._once=false;
    this._dateRange=xhPresetRange("week");this._requestId=0;
    this._series={};this._busy=false;this._message="";
    this._hidden=new Set();this._actionBusy=false;this._actionMessage="";
    this._statusTicker=null;
  }
  setConfig(cfg){this._cfg=cfg||{};this._render();}
  set dateRange(range){
    if(!range || (this._dateRange?.start===range.start &&
                   this._dateRange?.end===range.end))return;
    this._dateRange=range;
    if(this._once)this._load();
  }
  set hass(hass){
    this._hass=hass;
    if(!this._once && hass){this._once=true;this._load();}
    else if(!this._busy){this._render();}
  }
  connectedCallback(){
    if(this._statusTicker===null){
      this._statusTicker=window.setInterval(()=>{
        if(this.isConnected && this._hass && !this._busy && !this._actionBusy)
          this._render();
      },30000);
    }
  }
  disconnectedCallback(){
    if(this._statusTicker!==null){
      window.clearInterval(this._statusTicker);
      this._statusTicker=null;
    }
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
    if(!this._hass)return;
    const request=++this._requestId;
    this._busy=true;this._render();
    try{
      const ids=[...new Set([
        ...XH_SOURCES.map(x=>this._state(x.match,"sensor")).filter(Boolean),
        this._outdoorId(),
      ].filter(Boolean))];
      if(!ids.length)throw Error("No historical temperature sensors found. Update the tado X integration and restart Home Assistant.");
      const end=new Date(this._dateRange.end);
      const start=new Date(this._dateRange.start);
      const days=(end-start)/86400000;
      const granularity=days<=2?"hour":days<=92?"day":"month";
      const result=await this._hass.callWS({
        type:"recorder/statistics_during_period",
        start_time:start.toISOString(),end_time:end.toISOString(),
        statistic_ids:ids,period:granularity,
        types:["mean","min","max"],
      });
      if(request===this._requestId){this._series=result||{};this._message="";}
    }catch(e){if(request===this._requestId){
      this._message="History unavailable: "+(e?.message||e);this._series={};
    }}finally{if(request===this._requestId){this._busy=false;this._render();}}
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
      .filter(row=>row.start!=null && row.mean!=null &&
        Number.isFinite(Number(row.start)) && Number.isFinite(Number(row.mean)))
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
    const days=(new Date(this._dateRange.end)-new Date(this._dateRange.start))/86400000;
    const opts=days<=2?{hour:"2-digit",minute:"2-digit"}:
      days>92?{month:"short",year:"2-digit"}:{day:"numeric",month:"short"};
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
    const maxTime=new Date(this._dateRange.end).getTime();
    const minTime=new Date(this._dateRange.start).getTime();
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
      const days=(maxTime-minTime)/86400000;
      const grouping=days<=2?"hour":days<=92?"day":"month";
      const maxGap=grouping==="hour"?4*3600000:
        grouping==="day"?4*86400000:65*86400000;
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


  _modeStatus(){
    const id=this._state("Heating home mode","sensor");
    const entity=id?this._hass?.states?.[id]:null;
    if(!entity)return {
      label:"Unknown", note:"Heating home mode sensor unavailable. Restart Home Assistant after updating tado X.",
      resumeNeeded:null, manual:null
    };
    const a=entity.attributes||{};
    const ts=a.due_utc?Date.parse(a.due_utc):NaN;
    const seconds=Number.isFinite(ts)?Math.max(0,Math.ceil((ts-Date.now())/1000)):null;
    const boostActive=a.boost_timer_active===true;
    const boostPending=a.pending===true && a.kind==="resume_and_adapt" &&
      (a.mode==="eco_boost" || a.mode==="top_boost");
    const remaining=seconds===null?"deadline unknown":
      seconds>0?Math.ceil(seconds/60)+" min":"recovery due";
    const countdown=boostActive?" — "+remaining:
      a.kind==="adapt_only"?" — re-enabling adaptation":"";
    const pendingNote=boostPending && !boostActive
      ?(a.mode_label||"Boost")+" recovery timer still pending: "+remaining+
        ". Room states currently indicate "+(a.observed_mode_label||"unknown")+"."
      :null;
    const manual=typeof a.manual_override_count==="number"?a.manual_override_count:null;
    const following=typeof a.rooms_following_schedule==="number"?a.rooms_following_schedule:null;
    const unknown=typeof a.rooms_unknown==="number"?a.rooms_unknown:null;
    const observed=a.observed_mode_label||"Status unavailable";
    const label=(entity.state||"Unknown")+countdown;
    return {
      label, observed,
      manual, following, unknown,
      manualRooms:Array.isArray(a.manual_override_rooms)?a.manual_override_rooms:[],
      unknownRooms:Array.isArray(a.unknown_room_names)?a.unknown_room_names:[],
      adaptation:a.adaptive_flow_enabled,
      // Explicit true/false prevents unknown observations from being taken
      // as proof that a manual override was detected.
      resumeNeeded:typeof a.resume_needed==="boolean"?a.resume_needed:null,
      note:boostActive
        ?"Boost initiated through Home Assistant; room override status is reported by tado."
        :"Schedule/override status comes from tado room polling (normally every 5 minutes).",
      recoveryError:a.last_recovery_error||null,
      pendingNote
    };
  }
  async _quickAction(action){
    const options={
      off:{
        prompt:"Turn heating OFF in every room? Frost protection remains active until schedules are resumed or individual rooms are changed.",
        label:"Heating Off"
      },
      resume:{
        prompt:"Resume schedules in every heating room and ensure automatic flow adaptation is enabled? Any manual room overrides will be cancelled.",
        label:"Resume schedules"
      },
      eco_boost:{
        prompt:"Start Eco Boost for 30 minutes? All rooms request maximum temperatures while automatic flow adaptation stays enabled. The recovery deadline survives Home Assistant restarts.",
        label:"Eco Boost"
      },
      top_boost:{
        prompt:"Start TOP Boost for 30 minutes? All rooms request maximum temperatures and automatic flow adaptation is temporarily DISABLED, allowing up to your configured maximum flow limit. After 30 minutes, Home Assistant will resume schedules and re-enable adaptation, including after a restart.",
        label:"Top Boost"
      }
    };
    const selected=options[action];
    if(!selected||this._actionBusy||!this._hass)return;
    if(!window.confirm(selected.prompt))return;
    this._actionBusy=true;this._actionMessage="Sending "+selected.label+"…";
    this._render();
    try{
      const answer=await this._hass.callWS({
        type:"call_service",domain:"tado",
        service:"x_heating_quick_action",
        service_data:{action},return_response:true
      });
      if(answer?.response?.accepted===false)
        throw new Error("tado did not accept the action");
      this._actionMessage=selected.label+" request accepted. Scheduled recovery, if applicable, is persisted in Home Assistant. The tado heating rooms will reflect the change on their normal poll.";
    }catch(err){
      this._actionMessage=selected.label+" failed: "+(err?.message||err);
    }finally{
      this._actionBusy=false;this._render();
    }
  }
  _render(){
    const root=this.shadowRoot;root.replaceChildren();
    const style=this._el("style");
    style.textContent=[
      ":host{display:block;font-family:var(--primary-font-family,Roboto,Arial,sans-serif);color:var(--primary-text-color)}",
      "ha-card{display:block;background:var(--card-background-color,var(--ha-card-background,#fff));border:1px solid var(--divider-color,#ddd);border-radius:12px;padding:16px}",
      "h2{font-size:19px;font-weight:500;margin:0 0 12px}",
      "h3{font-size:15px;font-weight:600;margin:12px 0 6px}",
      ".section-head{font-size:13px;font-weight:600;letter-spacing:.02em;margin-top:14px}",
      ".controls{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:8px;margin:8px 0 16px}",
      "button{border:1px solid var(--divider-color,#aaa);background:transparent;color:inherit;border-radius:8px;padding:9px;cursor:pointer;font:inherit}",
      "button:disabled{opacity:.6;cursor:not-allowed}",
      ".setting-tile{text-align:left;min-height:76px;padding:12px;border:1px solid var(--divider-color,#ddd)}",
      ".tile-label{display:block;font-size:13px;font-weight:500}",
      ".tile-value{display:block;font-size:21px;font-variant-numeric:tabular-nums;margin-top:8px}",
      ".tile-note{display:block;font-size:11px;color:var(--secondary-text-color,#777);margin-top:5px}",
      ".tabs{display:flex;gap:6px;flex-wrap:wrap;margin:12px 0 16px}",
      ".tabs button{padding:8px 11px}",
      ".tabs button.active{background:var(--primary-color,#1976d2);color:white;border-color:var(--primary-color,#1976d2)}",
      ".plot{border:1px solid var(--divider-color,#ddd);border-radius:8px;padding:10px 8px;margin:8px 0 14px}",
      ".plot svg{display:block;width:100%;height:auto;overflow:visible}",
      ".plot-title{margin:0 0 8px 4px}",
      ".legend{display:flex;gap:5px;flex-wrap:wrap;margin-bottom:10px}",
      ".legend-item{display:flex;align-items:center;gap:6px;border-radius:999px;font-size:11px;padding:6px 8px;opacity:.5}",
      ".legend-item.selected{opacity:1;background:var(--secondary-background-color,#eee)}",
      ".legend-dot{display:inline-block;width:10px;height:10px;border-radius:50%;flex-shrink:0}",
      ".note{font-size:12px;color:var(--secondary-text-color,#777);line-height:1.5;margin:8px 2px}",
      ".mode-indicator{border:1px solid var(--divider-color,#ddd);background:var(--secondary-background-color,#f5f5f5);border-radius:8px;padding:12px;margin:9px 0}",
      ".mode-caption{display:block;font-size:12px;color:var(--secondary-text-color,#666)}",
      ".mode-value{display:block;font-size:20px;margin-top:5px}",
      ".mode-detail{display:block;font-size:11px;color:var(--secondary-text-color,#777);margin-top:5px}",
      ".mode-warning{display:block;font-size:12px;color:var(--error-color,#a33);margin-top:6px}",
      ".quick-actions{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:7px;margin:9px 0}",
      ".quick-action{font-size:12px;font-weight:600;padding:12px 4px;line-height:1.25}",
      ".off-action{border-color:var(--error-color,#b73830)}",
      ".resume-action{border-color:var(--success-color,#22936c)}",
      ".boost-action{border-color:var(--warning-color,#e59c28)}",
      ".top-action{border-color:var(--error-color,#b73830)}",
      ".message{padding:8px;background:var(--secondary-background-color,#eee);border-radius:6px;font-size:13px}"
    ].join("\n");
    root.append(style);
    const card=this._el("ha-card");
    card.append(this._el("h2",this._cfg.title||"Heating flow and hot water"));
    if(!this._cfg.shared_connection_status && this._hass){
      const health=this._el(xhTag("tado-x-connectivity-status"));
      health.hass=this._hass;
      card.append(health);
    }
    card.append(this._el("div","Heating flow optimisation","section-head"));
    const flow=this._el("div",null,"controls");
    const maxflow=XH_SOURCES.find(x=>x.id==="maxflow");
    const optimised=XH_SOURCES.find(x=>x.id==="optimised");
    const adapted=XH_SOURCES.find(x=>x.id==="adapted");
    const enabledRows=this._rows(adapted);
    const avg=enabledRows.length
      ? enabledRows.reduce((acc,p)=>acc+p.y,0)/enabledRows.length:null;
    flow.append(this._tile("Maximum flow temperature",
      this._state(maxflow.control,"number"),"°C","Configured upper limit"));
    flow.append(this._tile("tado optimised flow",
      this._sensorId(optimised),"°C","Calculated limit, not measured flow"));
    flow.append(this._tile("Automatic flow adaptation",
      this._state(adapted.control,"switch"),"",
      avg!==null?"Recorded mean: "+this._round(avg)+"% On":"Setting: On / Off"));
    flow.append(this._tile("Outside temperature",
      this._outdoorId(),"°C","Weather estimate or selected sensor"));
    card.append(flow);
    card.append(this._el("div","Whole-home heating controls","section-head"));
    const mode=this._modeStatus();
    const indicator=this._el("div",null,"mode-indicator");
    indicator.append(this._el("span","Current heating mode","mode-caption"));
    indicator.append(this._el("strong",mode.label,"mode-value"));
    indicator.append(this._el("small",mode.note,"mode-detail"));
    if(mode.manual!==null){
      indicator.append(this._el("div",
        "Rooms: "+(mode.following??"?")+" following schedules, "+mode.manual+
        " manual override"+(mode.manual===1?"":"s")+
        (mode.unknown?" · "+mode.unknown+" unknown":""),
        "mode-detail"));
      if(mode.observed!==mode.label&&!mode.label.startsWith(mode.observed)){
        indicator.append(this._el("small",
          "tado room status: "+mode.observed,"mode-detail"));
      }
      if(mode.manualRooms.length)
        indicator.append(this._el("small",
          "Interrupted: "+mode.manualRooms.join(", "),"mode-detail"));
      if(mode.unknownRooms.length)
        indicator.append(this._el("small",
          "Not confirmed: "+mode.unknownRooms.join(", "),"mode-detail"));
    }
    if(mode.adaptation===false)
      indicator.append(this._el("small",
        "Automatic flow adaptation is disabled","mode-warning"));
    if(mode.pendingNote)
      indicator.append(this._el("small",mode.pendingNote,"mode-warning"));
    if(mode.recoveryError)indicator.append(this._el(
      "small","Recovery warning: "+mode.recoveryError,"mode-warning"
    ));
    card.append(indicator);
    const actions=this._el("div",null,"quick-actions");
    for(const [label,action,klass] of [
      ["Heating Off","off","off-action"],
      ["Resume Schedules","resume","resume-action"],
      ["Eco Boost 30m","eco_boost","boost-action"],
      ["Top Boost 30m","top_boost","top-action"]
    ]){
      const b=this._button(label,()=>this._quickAction(action));
      b.className="quick-action "+klass;
      // Same principle as tado app: Resume is inactive when every room is
      // following schedule and adaptive flow is known enabled.
      b.disabled=this._actionBusy || (action==="resume" && mode.resumeNeeded===false);
      if(action==="resume" && mode.resumeNeeded===false)
        b.title="All rooms are on Smart Schedule and adaptive flow is enabled";
      actions.append(b);
    }
    card.append(actions);
    card.append(this._el("p","Resume Schedules is enabled when tado reports at least one room manually overridden, or adaptive flow is disabled. Boost timers survive Home Assistant restarts. Room schedule status is refreshed by tado polling and applies to rooms, not individual valves. Every action requires confirmation.","note"));
    if(this._actionMessage)card.append(this._el("p",this._actionMessage,"message"));
    card.append(this._el("div","Domestic hot water","section-head"));
    const dhw=this._el("div",null,"controls");
    const target=XH_SOURCES.find(x=>x.id==="dhw");
    dhw.append(this._tile("Hot-water target",
      this._state(target.control,"number"),"°C","Target, not measured tank temperature"));
    card.append(dhw);
    if(!this._cfg.shared_date_range){
      const picker=this._el(xhTag("tado-x-date-range-picker"));
      picker.range=this._dateRange;
      picker.addEventListener("date-range-changed",event=>{this.dateRange=event.detail;});
      card.append(picker);
    }
    const tabs=this._el("div",null,"tabs");
    tabs.append(this._button("Refresh",()=>this._load()));
    card.append(tabs);
    card.append(this._combinedChart());
    if(this._message)card.append(this._el("p",this._message,"message"));
    if(this._busy)card.append(this._el("p","Reading recorded temperatures…","note"));
    card.append(this._el("p",
      "Temperature history uses one Celsius scale. Maximum flow and DHW are target limits; optimised flow is calculated by tado; outside temperature is from the sensor named below the chart. No trace measures actual boiler outlet flow. Automatic flow adaptation is an On/Off setting; its historical mean percentage is shown in the tile. New setting histories cannot be reconstructed before installation.",
      "note"));
    root.append(card);
  }
}
// Managed dashboard uses release-scoped component tags; stable names remain
// available to existing user-authored Lovelace cards.
const XH_COMPONENT_VERSION=(new URL(import.meta.url).searchParams.get("v")||"dev").replace(/\./g,"-");
const XH_COMPONENT_TAG="tado-x-settings-history-card-v"+XH_COMPONENT_VERSION;
if(!customElements.get(XH_COMPONENT_TAG))
  customElements.define(XH_COMPONENT_TAG,class extends TadoXSettingsHistoryCard {});

if(!customElements.get("tado-x-settings-history-card")) customElements.define("tado-x-settings-history-card",TadoXSettingsHistoryCard);
window.customCards=window.customCards||[];
window.customCards.push({type:"tado-x-settings-history-card",
  name:"tado X hot-water and flow history",
  description:"Unified tado X heating flow, hot water and outdoor temperature history"});
