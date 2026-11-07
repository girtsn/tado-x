/* tado X connectivity status shared by managed Heating and Lovelace cards.
 * Reads only Home Assistant states; no browser-side API polling.
 */
class TadoXConnectivityStatus extends HTMLElement {
  constructor(){
    super();
    this.attachShadow({mode:"open"});
    this._hass=null;
    this._homeId=null;
    this._lastKey=null;
  }
  set hass(value){this._hass=value;this._render();}
  set homeId(value){this._homeId=value==null?null:String(value);this._lastKey=null;this._render();}
  connectedCallback(){this._render();}
  _lookup(scope){
    if(!this._hass)return null;
    return Object.entries(this._hass.states).find(([id,s])=>
      id.startsWith("binary_sensor.") &&
      s.attributes?.connectivity_scope===scope &&
      (!this._homeId||String(s.attributes?.tado_home_id)===this._homeId)
    )||null;
  }
  _el(tag,text,cls){
    const e=document.createElement(tag);
    if(text!=null)e.textContent=text;
    if(cls)e.className=cls;
    return e;
  }
  _render(){
    if(!this.isConnected || !this._hass)return;
    const main=this._lookup("main_api"),settings=this._lookup("settings_api");
    const key=JSON.stringify([main,settings].map(item=>item?[
      item[0],item[1].state,item[1].attributes?.failure_reason,
      item[1].attributes?.last_successful_update
    ]:null));
    if(key===this._lastKey)return;
    this._lastKey=key;
    const root=this.shadowRoot;
    root.replaceChildren();
    const style=this._el("style");
    style.textContent=`
      :host{display:block;font:inherit;color:var(--primary-text-color)}
      .wrap{display:flex;gap:10px;flex-wrap:wrap;align-items:center;
            padding:11px 14px;margin:12px 0;border:1px solid var(--divider-color,#ddd);
            border-radius:12px;background:var(--card-background-color,var(--ha-card-background,#fff))}
      .heading{font-size:13px;font-weight:600;margin-right:3px}
      .item{font:inherit;font-size:12px;background:transparent;color:inherit;
            border:1px solid var(--divider-color,#ddd);border-radius:8px;
            display:flex;align-items:center;gap:6px;padding:6px 9px;cursor:pointer}
      .item:disabled{cursor:default;opacity:.7}
      .dot{height:9px;width:9px;border-radius:100%;background:var(--disabled-text-color,#999)}
      .online .dot{background:var(--success-color,#2d996b)}
      .offline .dot{background:var(--error-color,#dc4444)}
      .age{font-size:12px;color:var(--secondary-text-color,#777)}
    `;
    root.append(style);
    const wrap=this._el("div",null,"wrap");
    wrap.append(this._el("span","Cloud connectivity","heading"));
    for(const [label,item] of [["Main API",main],["DHW/flow API",settings]]){
      const state=item?.[1].state||"missing";
      const labelState=state==="on"?"Connected":state==="off"?"Offline":"Unknown";
      const klass=state==="on"?"online":state==="off"?"offline":"";
      const b=this._el("button",null,"item "+klass);
      b.type="button";
      b.disabled=!item;
      const dot=this._el("span",null,"dot");
      b.append(dot,this._el("span",label+": "+labelState));
      if(item){
        const attrs=item[1].attributes||{};
        b.title=attrs.failure_reason||
          (attrs.last_successful_update?"Last successful poll: "+attrs.last_successful_update:"");
        b.addEventListener("click",()=>this.dispatchEvent(new CustomEvent(
          "hass-more-info",{bubbles:true,composed:true,detail:{entityId:item[0]}}
        )));
      }
      wrap.append(b);
    }
    const last=main?.[1].attributes?.last_successful_update;
    let lastText="Last successful update: not yet available";
    if(last){
      const dt=new Date(last);
      if(!Number.isNaN(dt.getTime()))lastText="Last main update: "+dt.toLocaleString();
    }
    wrap.append(this._el("span",lastText,"age"));
    root.append(wrap);
  }
}
// Managed dashboard uses release-scoped component tags; stable names remain
// available to existing user-authored Lovelace cards.
const XH_COMPONENT_VERSION=(new URL(import.meta.url).searchParams.get("v")||"dev").replace(/\./g,"-");
const XH_COMPONENT_TAG="tado-x-connectivity-status-v"+XH_COMPONENT_VERSION;
if(!customElements.get(XH_COMPONENT_TAG))
  customElements.define(XH_COMPONENT_TAG,class extends TadoXConnectivityStatus {});

if(!customElements.get("tado-x-connectivity-status"))
  customElements.define("tado-x-connectivity-status",TadoXConnectivityStatus);
