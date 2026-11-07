/* Stable tado X Heating sidebar loader, aligned with Renson's managed loader.
 * Version-specific dashboard modules can be swapped in without reloading
 * Home Assistant. Existing Lovelace card names/URLs remain available.
 */
const TX_CHECK_MS=60000;
class TadoXHeatingLoaderPanel extends HTMLElement {
  constructor(){
    super();this.attachShadow({mode:"open"});
    this._hass=null;this._panel=null;this._route=null;this._narrow=false;
    this._active=null;this._version=null;this._checking=false;
    this._timer=null;this._retries=new Map();
    this._onFocus=()=>this._check();
    this._onVisibility=()=>{if(!document.hidden)return this._check();};
    const style=document.createElement("style");
    style.textContent=":host{display:block;color:var(--primary-text-color)}.status{padding:12px 18px;font-size:13px;color:var(--secondary-text-color,#777)}.status:empty{display:none}";
    this._status=document.createElement("div");this._status.className="status";
    this._mount=document.createElement("div");
    this.shadowRoot.append(style,this._status,this._mount);
  }
  set hass(value){this._hass=value;if(this._active)this._active.hass=value;}
  set panel(value){this._panel=value;if(this._active)this._active.panel=value;}
  set route(value){this._route=value;if(this._active)this._active.route=value;}
  set narrow(value){this._narrow=!!value;if(this._active)this._active.narrow=this._narrow;}
  connectedCallback(){
    if(this._timer!==null)return;
    this._check();
    this._timer=window.setInterval(()=>this._check(),TX_CHECK_MS);
    window.addEventListener("focus",this._onFocus);
    document.addEventListener("visibilitychange",this._onVisibility);
  }
  disconnectedCallback(){
    if(this._timer!==null){window.clearInterval(this._timer);this._timer=null;}
    window.removeEventListener("focus",this._onFocus);
    document.removeEventListener("visibilitychange",this._onVisibility);
  }
  _tag(version){return "tado-x-managed-heating-panel-v"+version.replace(/\./g,"-");}
  _hasPendingAction(){
    const active=this._active;
    return !!(active?._busy?.size||active?._busy===true||
      (active?._cards||[]).some(c=>c?._busy===true||
        c?._actionBusy===true||c?._dirty?.size>0));
  }
  async _loadModule(version){
    const retry=this._retries.get(version)||0;
    const url="/tado/assets/"+version+"/x-managed-panel.js?v="+version+
      (retry?"&retry="+retry:"");
    try{await import(url);}
    catch(error){this._retries.set(version,retry+1);throw error;}
  }
  async _check(){
    if(this._checking||!this.isConnected)return;
    this._checking=true;
    try{
      const response=await fetch("/tado/manifest.json?_="+Date.now(),
        {cache:"no-store",credentials:"same-origin"});
      if(!response.ok)throw Error("Manifest HTTP "+response.status);
      const manifest=await response.json(),version=manifest?.version;
      if(typeof version!=="string"||!/^[0-9]+\.[0-9]+\.[0-9]+$/.test(version))
        throw Error("Invalid integration version");
      if(version===this._version){this._status.textContent="";return;}
      if(this._hasPendingAction()){
        this._status.textContent="A frontend update is available; it will apply after heating changes finish. Unsaved schedule edits must be saved or discarded.";
        return;
      }
      const tag=this._tag(version);
      if(!customElements.get(tag))await this._loadModule(version);
      if(!customElements.get(tag))throw Error("New dashboard component did not register: "+tag);
      const next=document.createElement(tag);
      next.panel=this._panel;next.route=this._route;
      next.narrow=this._narrow;next.hass=this._hass;
      this._mount.replaceChildren(next);
      this._active=next;this._version=version;this._status.textContent="";
    }catch(error){
      this._status.textContent=(this._active?
        "New dashboard not ready; continuing with current version. ":
        "Unable to load tado X dashboard. ")+(error?.message||String(error));
    }finally{this._checking=false;}
  }
}
if(!customElements.get("tado-x-heating-loader-panel"))
  customElements.define("tado-x-heating-loader-panel",TadoXHeatingLoaderPanel);
