/* Shared Energy-style date picker: managed panel and standalone cards. */
const xhMidnight=date=>new Date(date.getFullYear(),date.getMonth(),date.getDate());
const xhAddDays=(date,n)=>{
  const result=new Date(date.getFullYear(),date.getMonth(),date.getDate());
  result.setDate(result.getDate()+n);
  return result;
};
const xhDaySpan=(a,b)=>Math.round(
  (Date.UTC(b.getFullYear(),b.getMonth(),b.getDate())-
   Date.UTC(a.getFullYear(),a.getMonth(),a.getDate()))/86400000
);
const xhDateText=date=>date.toLocaleDateString(undefined,{month:"short",day:"numeric",year:"numeric"});
const xhFirstWeekday=()=>{
  try{return new Intl.Locale(navigator.language).weekInfo.firstDay%7;}
  catch(_){return 0;}
};
const xhPresetRange=(preset,base=new Date())=>{
  const now=xhMidnight(base),tomorrow=xhAddDays(now,1);
  const weekOffset=(now.getDay()-xhFirstWeekday()+7)%7;
  let start,end=tomorrow;
  switch(preset){
    case "today":start=now;break;
    case "yesterday":start=xhAddDays(now,-1);end=now;break;
    case "week":start=xhAddDays(now,-weekOffset);break;
    case "month":start=new Date(now.getFullYear(),now.getMonth(),1);break;
    case "quarter":start=new Date(now.getFullYear(),Math.floor(now.getMonth()/3)*3,1);break;
    case "year":start=new Date(now.getFullYear(),0,1);break;
    case "last7":start=xhAddDays(now,-6);break;
    case "last30":start=xhAddDays(now,-29);break;
    case "last365":start=xhAddDays(now,-364);break;
    case "last12months":start=new Date(now.getFullYear(),now.getMonth()-11,1);break;
    case "last3years":start=xhAddDays(new Date(now.getFullYear()-3,now.getMonth(),now.getDate()),1);break;
    default:start=xhAddDays(now,-6);preset="last7";
  }
  return {start:start.toISOString(),end:end.toISOString(),preset};
};

/* Energy-dashboard-style date selector, shared by all historic cards.
 * Dates use local midnights; end is exclusive to avoid DST / partial-day bugs.
 */
class TadoXDateRangePicker extends HTMLElement {
  constructor(){
    super();this.attachShadow({mode:"open"});
    this._range=xhPresetRange("week");this._open=false;
    this._month=xhMidnight(new Date());
    this._draftStart=null;this._draftEnd=null;
  }
  set range(value){if(value){this._range=value;this._render();}}
  get range(){return this._range;}
  connectedCallback(){this._render();}
  _el(tag,text,cls){
    const e=document.createElement(tag);
    if(text!=null)e.textContent=text;
    if(cls)e.className=cls;
    return e;
  }
  _btn(label,handler,cls,disabled=false){
    const el=this._el("button",label,cls);el.type="button";el.disabled=disabled;
    el.addEventListener("click",handler);return el;
  }
  _limits(start,end){
    const today=xhAddDays(xhMidnight(new Date()),1);
    return start<end && end<=today && xhDaySpan(start,end)<=1099;
  }
  _apply(start,end,preset="custom"){
    if(!this._limits(start,end))return;
    this._range={start:start.toISOString(),end:end.toISOString(),preset};
    this._open=false;this._draftStart=null;this._draftEnd=null;
    this._render();
    this.dispatchEvent(new CustomEvent("date-range-changed",{
      detail:this._range,bubbles:true,composed:true
    }));
  }
  _shift(direction){
    const start=xhMidnight(new Date(this._range.start));
    const end=xhMidnight(new Date(this._range.end));
    const preset=this._range.preset;
    let nextStart,nextEnd;
    const months=({month:1,quarter:3,year:12})[preset];
    if(months){
      nextStart=new Date(start.getFullYear(),start.getMonth()+months*direction,1);
      nextEnd=new Date(start.getFullYear(),start.getMonth()+months*(direction+1),1);
      const tomorrow=xhAddDays(xhMidnight(new Date()),1);
      if(nextEnd>tomorrow)nextEnd=tomorrow;
    }else if(preset==="last12months"||preset==="last3years"){
      const monthsBack=preset==="last3years"?36:12;
      nextStart=new Date(start.getFullYear(),start.getMonth()+monthsBack*direction,start.getDate());
      nextEnd=new Date(start.getFullYear(),start.getMonth()+monthsBack*(direction+1),start.getDate());
      const tomorrow=xhAddDays(xhMidnight(new Date()),1);
      if(nextEnd>tomorrow)nextEnd=tomorrow;
    }else{
      const diff=xhDaySpan(start,end);
      nextStart=xhAddDays(start,diff*direction);
      nextEnd=xhAddDays(end,diff*direction);
    }
    if(this._limits(nextStart,nextEnd))this._apply(nextStart,nextEnd,preset);
  }
  _dayClick(date){
    if(!this._draftStart||this._draftEnd){
      this._draftStart=date;this._draftEnd=null;
    }else if(date<this._draftStart){
      this._draftEnd=xhAddDays(this._draftStart,1);
      this._draftStart=date;
    }else this._draftEnd=xhAddDays(date,1);
    this._render();
  }
  _render(){
    if(!this.isConnected)return;
    const root=this.shadowRoot;root.replaceChildren();
    const style=this._el("style");
    style.textContent=[
      ":host{display:block;color:var(--primary-text-color);font:inherit;position:relative;z-index:5}",
      "*{box-sizing:border-box}",
      ".toolbar{display:flex;gap:8px;align-items:center;flex-wrap:wrap}",
      "button{font:inherit;background:var(--card-background-color,var(--ha-card-background,#fff));border:1px solid var(--divider-color,#ddd);color:inherit;border-radius:8px;cursor:pointer;padding:8px 11px}",
      "button:disabled{opacity:.4;cursor:default}",
      ".label{font-weight:600;font-size:14px;display:flex;align-items:center;gap:8px}",
      ".chevron{padding:7px 12px;font-size:18px;min-width:36px}",
      ".now{color:var(--primary-color,#039bc6)}",
      ".popup{position:absolute;top:calc(100% + 8px);left:0;z-index:100;display:grid;grid-template-columns:170px minmax(265px,320px);background:var(--card-background-color,var(--ha-card-background,#fff));box-shadow:0 8px 28px #0003;border:1px solid var(--divider-color,#ddd);border-radius:16px;overflow:hidden;max-width:calc(100vw - 30px)}",
      ".presets{border-right:1px solid var(--divider-color,#ddd);max-height:420px;overflow-y:auto;padding:8px}",
      ".preset{display:block;width:100%;border:0;background:transparent;text-align:left;padding:10px 12px;border-radius:6px;font-size:13px}",
      ".preset.selected,.preset:hover{background:var(--secondary-background-color,#eee)}",
      ".right{padding:12px;min-width:0}",
      ".month-head{display:flex;align-items:center;justify-content:space-between;font-weight:600;font-size:14px;margin-bottom:12px}",
      ".calendar{display:grid;grid-template-columns:repeat(7,minmax(0,1fr));gap:1px}",
      ".weekday{text-align:center;font-size:11px;color:var(--secondary-text-color,#888);padding:8px 0}",
      ".day{border:0;border-radius:6px;padding:9px 0;min-width:0;background:transparent;font-size:12px}",
      ".day.inrange{background:var(--primary-color,#039bc6);color:#fff}",
      ".day.outside{color:var(--disabled-text-color,#aaa)}",
      ".day.today{outline:1px solid var(--primary-color,#039bc6)}",
      ".footer{display:flex;justify-content:flex-end;gap:8px;margin-top:14px}",
      ".choose{background:var(--primary-color,#039bc6);color:var(--text-primary-color,#fff)}",
      "@media(max-width:570px){.popup{grid-template-columns:minmax(0,1fr);width:min(360px,calc(100vw - 30px))}.presets{display:grid;grid-template-columns:1fr 1fr;max-height:140px;border-right:0;border-bottom:1px solid var(--divider-color,#ddd)}.preset{padding:7px 8px}}"
    ].join("\n");root.append(style);
    const start=xhMidnight(new Date(this._range.start));
    const end=xhMidnight(new Date(this._range.end));
    const bar=this._el("div",null,"toolbar");
    const label=xhDateText(start)+" – "+xhDateText(xhAddDays(end,-1));
    bar.append(this._btn("▣  "+label,()=>{this._open=!this._open;this._render();},"label"));
    bar.append(this._btn("Now",()=>{const r=xhPresetRange(this._range.preset==="custom"?"week":this._range.preset);this._apply(xhMidnight(new Date(r.start)),xhMidnight(new Date(r.end)),r.preset);},"now"));
    bar.append(this._btn("‹",()=>this._shift(-1),"chevron"));
    bar.append(this._btn("›",()=>this._shift(1),"chevron",end>=xhAddDays(xhMidnight(new Date()),1)));
    root.append(bar);
    if(!this._open)return;
    const popup=this._el("div",null,"popup");
    const presets=this._el("div",null,"presets");
    for(const [key,title] of [
      ["today","Today"],["yesterday","Yesterday"],["week","This week"],
      ["month","This month"],["quarter","This quarter"],["year","This year"],
      ["last7","Last 7 days"],["last30","Last 30 days"],
      ["last365","Last 365 days"],["last12months","Last 12 months"],
      ["last3years","Last 3 years"]
    ]){
      presets.append(this._btn(title,()=>{
        const r=xhPresetRange(key);this._apply(xhMidnight(new Date(r.start)),xhMidnight(new Date(r.end)),key);
      },"preset"+(this._range.preset===key?" selected":"")));
    }
    popup.append(presets);
    const right=this._el("div",null,"right");
    const head=this._el("div",null,"month-head");
    head.append(this._btn("‹",()=>{this._month=new Date(this._month.getFullYear(),this._month.getMonth()-1,1);this._render();},"chevron"));
    head.append(this._el("span",this._month.toLocaleDateString(undefined,{month:"long",year:"numeric"})));
    head.append(this._btn("›",()=>{this._month=new Date(this._month.getFullYear(),this._month.getMonth()+1,1);this._render();},"chevron"));
    right.append(head);
    const cal=this._el("div",null,"calendar");
    const first=xhFirstWeekday();
    for(let i=0;i<7;i++){
      const d=new Date(2026,10,1+((first+i)%7));
      cal.append(this._el("span",d.toLocaleDateString(undefined,{weekday:"narrow"}),"weekday"));
    }
    const monthStart=new Date(this._month.getFullYear(),this._month.getMonth(),1);
    const offset=(monthStart.getDay()-first+7)%7;
    const draftStart=this._draftStart||start,draftEnd=this._draftEnd||(!this._draftStart?end:null);
    for(let i=0;i<42;i++){
      const date=xhAddDays(monthStart,i-offset);
      const future=date>xhMidnight(new Date());
      const inRange=draftEnd ? date>=draftStart&&date<draftEnd :
        this._draftStart&&xhDaySpan(date,draftStart)===0;
      const cls="day"+(date.getMonth()!==this._month.getMonth()?" outside":"")+
        (inRange?" inrange":"")+(xhDaySpan(date,xhMidnight(new Date()))===0?" today":"");
      cal.append(this._btn(String(date.getDate()),()=>this._dayClick(date),cls,future));
    }
    right.append(cal);
    const footer=this._el("div",null,"footer");
    footer.append(this._btn("Cancel",()=>{this._open=false;this._draftStart=null;this._draftEnd=null;this._render();}));
    footer.append(this._btn("Select",()=>{
      const a=this._draftStart||start,b=this._draftEnd||(!this._draftStart?end:null);
      if(b)this._apply(a,b,"custom");
    },"choose",Boolean(this._draftStart&&!this._draftEnd)));
    right.append(footer);popup.append(right);root.append(popup);
  }
}
if(!customElements.get("tado-x-date-range-picker"))
  customElements.define("tado-x-date-range-picker",TadoXDateRangePicker);

export { xhPresetRange };
