/* tado X weekly schedule editor. Adapted from the interaction model of the
 * Vipera NEX HOME editor in girtsn/tuya-local; it uses native HOPS schedule
 * operations, not Tuya DP26/Base64. No API writes without confirmation.
 */
const X_DAYS = ["MONDAY","TUESDAY","WEDNESDAY","THURSDAY","FRIDAY","SATURDAY","SUNDAY"];
const labelTime = m => m === 1440 ? "24:00" : String(Math.floor(m/60)).padStart(2,"0")+":"+String(m%60).padStart(2,"0");
const minutes = s => s === "24:00" ? 1440 : (+s.slice(0,2))*60 + (+s.slice(3,5));
const clone = x => JSON.parse(JSON.stringify(x));
const signatureValue = x => JSON.stringify(x);

class TadoXScheduleCard extends HTMLElement {
  constructor(){
    super();this.attachShadow({mode:"open"});
    this._cfg={};this._hass=null;this._rooms=[];this._room=null;this._day="MONDAY";
    this._data=null;this._baseline=null;this._dirty=new Set();
    this._busy=false;this._notice="";this._initialized=false;
    this._copyTargetDay="MONDAY";this._copyRoom="";
  }
  setConfig(config){this._cfg=config||{};this._render();}
  set hass(hass){
    const oldStart=this._weekStart();
    this._hass=hass;
    if(!this._initialized && hass){this._initialized=true;this._init();}
    else if(oldStart!==this._weekStart() && this.isConnected)this._render();
  }
  _weekStart(){
    const weekdays=["sunday","monday","tuesday","wednesday","thursday","friday","saturday"];
    const selected=weekdays.indexOf(this._hass?.locale?.first_weekday);
    if(selected>=0)return selected;
    const lang=this._hass?.locale?.language||this._hass?.language||"en-GB";
    try{return new Intl.Locale(lang).weekInfo.firstDay%7;}
    catch(_){return 1;}
  }
  _displayDays(){
    const first=this._weekStart();
    return Array.from({length:7},(_,i)=>X_DAYS[(first+6+i)%7]);
  }
  getCardSize(){return 7;}
  static getStubConfig(){return {title:"tado X weekly heating schedules"};}
  async _call(service, data={}){
    const payload={...data};
    if(this._cfg.config_entry) payload.config_entry=this._cfg.config_entry;
    const result=await this._hass.callWS({
      type:"call_service",domain:"tado",service,
      service_data:payload,return_response:true,
    });
    return result?.response ?? result;
  }
  async _init(){
    this._busy=true;this._render();
    try{
      const response=await this._call("x_list_rooms");
      this._rooms=response.rooms||[];
      if(!this._rooms.length)throw Error("No tado X rooms found");
      this._room=this._rooms[0].room_id;
      this._copyRoom=String(this._room);
      await this._load();
    }catch(e){this._notice="Unable to load rooms: "+(e?.message||e);}
    finally{this._busy=false;this._render();}
  }
  async _load(){
    if(this._room==null)return;
    const response=await this._call("x_get_schedule",{room_id:Number(this._room)});
    if(!response?.days)throw Error("Schedule response missing days");
    this._data=clone(response.days);
    this._baseline=clone(response.days);
    this._dirty.clear();
    this._notice="Schedule loaded. Changes are local until explicitly saved.";
    this._render();
  }
  _state(){return this._data?.[this._day]||null;}
  _mark(day){
    const cur=this._data?.[day]?.blocks,old=this._baseline?.[day]?.blocks;
    if(signatureValue(cur)===signatureValue(old))this._dirty.delete(day);
    else this._dirty.add(day);
  }
  _mutate(day,blockIndex,key,value){
    if(this._busy)return;
    const blocks=this._data[day].blocks;
    if(key==="end"){
      if(blockIndex===blocks.length-1)return;
      const t=minutes(value);
      if(!Number.isInteger(t)||t<=minutes(blocks[blockIndex].start)||t>=minutes(blocks[blockIndex+1].end)){
        this._notice="Block boundary must remain between the adjacent boundaries.";this._render();return;
      }
      blocks[blockIndex].end=value;blocks[blockIndex+1].start=value;
    }else if(key==="temperature"){
      const t=Number(value);
      if(!Number.isFinite(t)||t<5||t>30||Math.round(t*2)!==t*2){
        this._notice="Temperature must be 5–30°C in 0.5°C increments.";this._render();return;
      }
      blocks[blockIndex].temperature=t;
    }else if(key==="power"){
      blocks[blockIndex].power=value;
      if(value==="ON" && blocks[blockIndex].temperature==null) blocks[blockIndex].temperature=20;
      if(value==="OFF")blocks[blockIndex].temperature=null;
    }
    this._mark(day);this._render();
  }
  _split(index){
    const blocks=this._state().blocks;
    const first=blocks[index],a=minutes(first.start),b=minutes(first.end);
    const split=Math.round(((a+b)/2)/5)*5;
    if(split<=a||split>=b){this._notice="Block too short to split.";this._render();return;}
    const second={...first,start:labelTime(split),end:first.end};
    first.end=labelTime(split);blocks.splice(index+1,0,second);
    this._mark(this._day);this._render();
  }
  _remove(index){
    const blocks=this._state().blocks;
    if(blocks.length<=1)return;
    if(index===0)blocks[1].start=blocks[0].start;
    else blocks[index-1].end=blocks[index].end;
    blocks.splice(index,1);this._mark(this._day);this._render();
  }
  _copyDay(){
    if(this._busy||!this._state())return;
    const to=this._copyTargetDay;
    if(to===this._day)return;
    this._data[to].blocks=clone(this._state().blocks);
    this._mark(to);
    this._notice="Copied "+this._day+" → "+to+" in local draft; save that day to apply.";
    this._render();
  }
  async _saveDay(day=this._day){
    if(this._busy||!this._dirty.has(day))return;
    const name=this._rooms.find(r=>r.room_id==this._room)?.name||this._room;
    if(!confirm("Replace "+day+"'s tado schedule in "+name+"?"))return;
    this._busy=true;this._notice="Saving and verifying "+day+"…";this._render();
    try{
      const result=await this._call("x_save_day",{
        room_id:Number(this._room),day,blocks:this._data[day].blocks,
        expected_signature:this._baseline[day].signature,
      });
      if(!result.confirmed)throw Error("Write sent, but readback differed: check the tado app before retrying.");
      const remaining = X_DAYS.filter(d=>d!==day && this._dirty.has(d)).map(d=>[d,clone(this._data[d].blocks)]);
      await this._load();
      for(const [d,blocks] of remaining){this._data[d].blocks=blocks;this._mark(d);}
      this._notice="Saved and verified "+day+" in tado. Other unsaved days retained as drafts.";
    }catch(e){this._notice="Not verified: "+(e?.message||e)+". Reload before retrying.";}
    finally{this._busy=false;this._render();}
  }
  async _saveWeek(){
    const changed=X_DAYS.filter(d=>this._dirty.has(d));
    if(!changed.length)return;
    if(!confirm("Write "+changed.length+" changed day(s) to tado? Each day is saved separately; partial results are possible."))return;
    const snapshot=clone(this._data),baseline=clone(this._baseline);
    this._busy=true;this._render();let count=0;
    try{
      for(const day of changed){
        this._notice="Saving "+day+" ("+(count+1)+"/"+changed.length+")…";this._render();
        const res=await this._call("x_save_day",{
          room_id:Number(this._room),day,blocks:snapshot[day].blocks,
          expected_signature:baseline[day].signature,
        });
        if(!res.confirmed)throw Error(day+" did not match after readback");
        count++;
      }
      await this._load();
      this._notice="Saved and verified "+count+" day(s).";
    }catch(e){
      this._notice="Saved "+count+" day(s), then stopped: "+(e?.message||e)+". Reload to reconcile.";
    }finally{this._busy=false;this._render();}
  }
  async _copyToRoom(allDays=false){
    if(this._busy||this._dirty.size){
      this._notice="Save or discard unsaved edits before copying to another room.";this._render();return;
    }
    const target=Number(this._copyRoom);
    if(target===Number(this._room))return;
    const sourceName=this._rooms.find(r=>r.room_id==this._room)?.name||this._room;
    const destName=this._rooms.find(r=>r.room_id===target)?.name||target;
    const days=allDays?X_DAYS:[this._day];
    if(!confirm("REPLACE "+days.join(", ")+" on "+destName+" with schedules from "+sourceName+"? This changes another room."))return;
    this._busy=true;this._render();let saved=0;
    try{
      const dest=await this._call("x_get_schedule",{room_id:target});
      for(const day of days){
        this._notice="Writing "+destName+" / "+day+"…";this._render();
        const res=await this._call("x_save_day",{
          room_id:target,day,blocks:this._data[day].blocks,
          expected_signature:dest.days[day].signature,
        });
        if(!res.confirmed)throw Error(day+" did not match after readback");
        saved++;
      }
      this._notice="Verified "+saved+" day(s) copied to "+destName+".";
    }catch(e){this._notice="Copied "+saved+" day(s), then stopped: "+(e?.message||e);}
    finally{this._busy=false;this._render();}
  }
  async _changeRoom(id){
    if(this._busy)return;
    if(this._dirty.size&&!confirm("Discard unsaved edits and change room?"))return;
    this._room=Number(id);this._data=null;this._baseline=null;this._busy=true;this._render();
    try{await this._load();}catch(e){this._notice="Load failed: "+(e?.message||e);}
    finally{this._busy=false;this._render();}
  }
  _node(tag,text,cls){
    const el=document.createElement(tag);
    if(text!=null)el.textContent=text;
    if(cls)el.className=cls;
    return el;
  }
  _button(text,fn,cls){
    const b=this._node("button",text,cls);
    b.disabled=this._busy;b.addEventListener("click",fn);return b;
  }
  _select(options,current,change){
    const s=this._node("select");
    for(const [val,label] of options){
      const opt=this._node("option",label);opt.value=String(val);
      opt.selected=String(current)===String(val);s.append(opt);
    }
    s.disabled=this._busy;s.addEventListener("change",e=>change(e.target.value));
    return s;
  }
  _render(){
    if(!this.shadowRoot)return;
    const root=this.shadowRoot;root.replaceChildren();
    const style=this._node("style");
    style.textContent=`
      :host{display:block;font-family:var(--primary-font-family,Roboto,Arial,sans-serif);color:var(--primary-text-color)}
      ha-card{display:block;border-radius:12px;background:var(--card-background-color,var(--ha-card-background,#fff));padding:18px;border:1px solid var(--divider-color,#ddd)}
      h2{font-size:19px;font-weight:500;margin:0 0 14px}
      .row{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin:9px 0}
      .group{padding:12px;border-radius:8px;border:1px solid var(--divider-color,#ddd);margin:12px 0}
      .days{display:flex;flex-wrap:wrap;gap:5px;margin:12px 0}
      button,select,input{font:inherit;border:1px solid var(--divider-color,#aaa);border-radius:6px;padding:7px 9px;background:var(--card-background-color,#fff);color:var(--primary-text-color)}
      button{cursor:pointer}button:hover:enabled{background:var(--secondary-background-color,#ddd)}
      button:disabled,select:disabled{opacity:.5;cursor:not-allowed}
      button.active,button.primary{background:var(--primary-color,#1976d2);color:white;border-color:var(--primary-color,#1976d2)}
      button.dirty{border:2px solid var(--warning-color,#d89b20)}
      .blocks{display:grid;grid-template-columns:1fr 1fr 1fr 1fr auto;gap:6px;align-items:center}
      .hdr{font-size:12px;color:var(--secondary-text-color,#888)}
      .blocks input,.blocks select{width:100%;min-width:0;box-sizing:border-box}
      .note{font-size:12px;color:var(--secondary-text-color,#888);line-height:1.5}
      .notice{background:var(--secondary-background-color,#eee);padding:8px;border-radius:6px;white-space:pre-wrap;font-size:13px}
      .short{font-size:12px} .spacer{flex:1}
      @media(max-width:540px){ha-card{padding:12px}.blocks{gap:3px}.blocks input,.blocks select{padding:5px 2px;font-size:12px}}
    `;
    root.append(style);const card=this._node("ha-card");
    card.append(this._node("h2",this._cfg.title||"tado X weekly heating schedules"));
    if(!this._hass){card.append(this._node("p","Waiting for Home Assistant…"));root.append(card);return;}
    if(this._rooms.length){
      const row=this._node("div",null,"row");
      row.append(this._node("span","Room"));
      row.append(this._select(this._rooms.map(r=>[r.room_id,r.name]),this._room,id=>this._changeRoom(id)));
      row.append(this._button("Reload",async()=>{
        if(this._dirty.size&&!confirm("Discard unsaved edits?"))return;
        this._busy=true;this._render();
        try{await this._load();}catch(e){this._notice="Reload failed: "+(e?.message||e);}
        finally{this._busy=false;this._render();}
      }));
      card.append(row);
    }
    if(this._data){
      const tabs=this._node("div",null,"days");
      for(const d of this._displayDays())tabs.append(this._button(d.slice(0,3)+(this._dirty.has(d)?" *":""),()=>{
        this._day=d;this._render();
      },(this._day===d?"active ":"")+(this._dirty.has(d)?"dirty":"")));
      card.append(tabs);
      const day=this._state();
      const form=this._node("div",null,"group");
      form.append(this._node("div","Time blocks for "+this._day+" — changes stay local until saved.","note"));
      const header=this._node("div",null,"blocks");
      ["Start","End","Mode","Target °C",""].forEach(t=>header.append(this._node("span",t,"hdr")));
      form.append(header);
      day.blocks.forEach((b,i)=>{
        const div=this._node("div",null,"blocks");
        const start=this._node("input");start.type="time";start.value=b.start;start.disabled=true;div.append(start);
        if(i===day.blocks.length-1){div.append(this._node("span","24:00"));}
        else {
          const end=this._node("input");end.type="time";end.step=300;end.value=b.end;
          end.disabled=this._busy;end.addEventListener("change",e=>this._mutate(this._day,i,"end",e.target.value));
          div.append(end);
        }
        div.append(this._select([["ON","Heating"],["OFF","Off"]],b.power,v=>this._mutate(this._day,i,"power",v)));
        const temp=this._node("input");temp.type="number";temp.min="5";temp.max="30";temp.step="0.5";
        temp.value=b.temperature??"";temp.disabled=this._busy||b.power==="OFF";
        temp.addEventListener("change",e=>this._mutate(this._day,i,"temperature",e.target.value));
        div.append(temp);
        const buttons=this._node("span",null,"row");
        buttons.append(this._button("+",()=>this._split(i),"short"));
        if(day.blocks.length>1)buttons.append(this._button("×",()=>this._remove(i),"short"));
        div.append(buttons);form.append(div);
      });card.append(form);
      const save=this._node("div",null,"row");
      save.append(this._button("Save selected day",()=>this._saveDay(),this._dirty.has(this._day)?"primary":""));
      save.append(this._button("Save changed days ("+this._dirty.size+")",()=>this._saveWeek(),this._dirty.size?"primary":""));
      card.append(save);
      const cp=this._node("div",null,"group");
      cp.append(this._node("strong","Copy schedules"));
      const cprow=this._node("div",null,"row");
      cprow.append(this._node("span","Copy "+this._day+" to"));
      cprow.append(this._select(this._displayDays().map(d=>[d,d.slice(0,3)]),this._copyTargetDay,v=>{this._copyTargetDay=v;}));
      cprow.append(this._button("Copy to draft",()=>this._copyDay()));
      cp.append(cprow);
      const dst=this._node("div",null,"row");
      dst.append(this._node("span","Copy to room"));
      dst.append(this._select(this._rooms.map(r=>[r.room_id,r.name]),this._copyRoom,v=>{this._copyRoom=v;}));
      dst.append(this._button("Copy selected day",()=>this._copyToRoom(false)));
      dst.append(this._button("Copy full week",()=>this._copyToRoom(true)));
      cp.append(dst);card.append(cp);
      card.append(this._node("p","Saving sends real changes to tado. Every day is read and checked before the update; an API success is verified by reading it back. A multi-day copy may stop partway through if an error occurs.","note"));
    }
    if(this._notice)card.append(this._node("p",this._notice,"notice"));
    if(this._busy)card.append(this._node("p","Working…","note"));
    root.append(card);
  }
}
// Managed dashboard uses release-scoped component tags; stable names remain
// available to existing user-authored Lovelace cards.
const XH_COMPONENT_VERSION=(new URL(import.meta.url).searchParams.get("v")||"dev").replace(/\./g,"-");
const XH_COMPONENT_TAG="tado-x-schedule-card-v"+XH_COMPONENT_VERSION;
if(!customElements.get(XH_COMPONENT_TAG))
  customElements.define(XH_COMPONENT_TAG,class extends TadoXScheduleCard {});

if(!customElements.get("tado-x-schedule-card")) customElements.define("tado-x-schedule-card",TadoXScheduleCard);
window.customCards=window.customCards||[];
window.customCards.push({type:"tado-x-schedule-card",name:"tado X weekly schedules",
  description:"Review, copy and safely edit room heating time blocks"});
