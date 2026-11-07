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
  _chart(source){
    const id=this._state(source.match,"sensor");
    const data=(id&&this._series[id]||[]).filter(p=>Number.isFinite(p.mean) && Number.isFinite(p.start));
    const outer=this._el("div",null,"plot");
    const title=this._el("div",source.title,"plot-title");outer.append(title);
    const current=id?this._hass.states[id]?.state:null;
    outer.append(this._el("div",(current!=null&&Number.isFinite(+current)?this._round(+current)+" "+source.unit:"—"),"value"));
    if(!data.length){
      outer.append(this._el("p",id?"No recorded statistics in selected period.":"History sensor not found; check tado X integration.","note"));
      return outer;
    }
    const xs=data.map(r=>Number(r.start));
    const ys=data.map(r=>Number(r.mean));
    let min=Math.min(...ys),max=Math.max(...ys);
    if(Math.abs(max-min)<.1){min-=1;max+=1;}
    else {const d=(max-min)*.12;min-=d;max+=d;}
    if(source.id==="adapted"){min=Math.max(0,min);max=Math.min(100,Math.max(1,max));}
    const xMin=Math.min(...xs),xMax=Math.max(...xs);
    const w=340,h=132,l=32,r=8,t=9,b=22;
    const xp=x=>l+((x-xMin)/(xMax-xMin||1))*(w-l-r);
    const yp=y=>t+(max-y)/(max-min||1)*(h-t-b);
    const uri="http://www.w3.org/2000/svg";
    const svg=document.createElementNS(uri,"svg");
    svg.setAttribute("viewBox",`0 0 ${w} ${h}`);
    svg.setAttribute("role","img");
    svg.setAttribute("aria-label",source.title+" recorded history");
    for(let k=0;k<3;k++){
      const value=min+(max-min)*k/2, y=yp(value);
      const line=document.createElementNS(uri,"line");
      Object.entries({x1:l,x2:w-r,y1:y,y2:y,stroke:"var(--divider-color,#ddd)","stroke-width":"1"}).forEach(([a,v])=>line.setAttribute(a,String(v)));
      svg.append(line);
      const label=document.createElementNS(uri,"text");
      label.textContent=this._round(value);
      label.setAttribute("x",l-4);label.setAttribute("y",y+3);label.setAttribute("text-anchor","end");
      label.setAttribute("fill","var(--secondary-text-color,#777)");
      label.setAttribute("font-size","9");svg.append(label);
    }
    const points=xs.map((x,i)=>`${xp(x)},${yp(ys[i])}`).join(" ");
    if(data.length>1){
      const poly=document.createElementNS(uri,"polyline");
      poly.setAttribute("points",points);poly.setAttribute("fill","none");
      poly.setAttribute("stroke","var(--primary-color,#1976d2)");
      poly.setAttribute("stroke-width","2");poly.setAttribute("stroke-linejoin","round");
      svg.append(poly);
    }
    if(data.length<=90){
      xs.forEach((x,i)=>{
        const circle=document.createElementNS(uri,"circle");
        circle.setAttribute("cx",xp(x));circle.setAttribute("cy",yp(ys[i]));
        circle.setAttribute("r",data.length<=45?"2.2":"1.2");
        circle.setAttribute("fill","var(--primary-color,#1976d2)");
        const caption=document.createElementNS(uri,"title");
        caption.textContent=new Date(x).toLocaleDateString()+" — "+this._round(ys[i])+" "+source.unit;
        circle.append(caption);svg.append(circle);
      });
    }
    const startLabel=document.createElementNS(uri,"text"),endLabel=document.createElementNS(uri,"text");
    startLabel.textContent=new Date(xMin).toLocaleDateString();
    endLabel.textContent=new Date(xMax).toLocaleDateString();
    for(const [node,x,anchor] of [[startLabel,l,"start"],[endLabel,w-r,"end"]]){
      node.setAttribute("x",x);node.setAttribute("y",h-2);node.setAttribute("font-size","10");
      node.setAttribute("text-anchor",anchor);
      node.setAttribute("fill","var(--secondary-text-color,#777)");
      svg.append(node);
    }
    outer.append(svg);
    outer.append(this._el("div","Period average "+this._round(ys.reduce((a,b)=>a+b,0)/ys.length)+" "+source.unit,"note"));
    return outer;
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
