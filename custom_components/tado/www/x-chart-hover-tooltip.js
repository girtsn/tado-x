/* Shared interaction for integration-managed Recorder SVG charts.
 * Shows the selected Recorder bucket without inventing values in data gaps.
 */
const RECORDER_BUCKET_MS={
  "5minute":300000,hour:3600000,day:86400000,
  week:604800000,month:31*86400000
};

export function attachRecorderChartTooltip(container,svg,series,options){
  const {start,end,width,left,right,top,bottom,yFor,unit="",period="hour"}=options;
  if(!Number.isFinite(start)||!Number.isFinite(end)||end<=start||!width||
     typeof yFor!=="function")return;
  const groups=series.map((s,index)=>({
    track:index,
    label:s.label,color:s.color,unit:s.unit??unit,
    points:(s.points||[]).filter(p=>Number.isFinite(p.x)&&Number.isFinite(p.y)&&
      p.x>=start&&p.x<=end).slice().sort((a,b)=>a.x-b.x)
  })).filter(s=>s.points.length);
  if(!groups.length)return;
  const times=[...new Set(groups.flatMap(s=>s.points.map(p=>p.x)))].sort((a,b)=>a-b);
  const bucket=RECORDER_BUCKET_MS[period]||3600000;
  // Avoid attaching stale values across gaps. An empty Recorder bucket is empty.
  const tolerance=bucket*0.9;
  const nearest=(arr,value,key)=>{
    let lo=0,hi=arr.length;
    while(lo<hi){const mid=(lo+hi)>>>1;
      if(key(arr[mid])<value)lo=mid+1;else hi=mid;
    }
    const after=arr[Math.min(lo,arr.length-1)];
    const before=arr[Math.max(0,lo-1)];
    return Math.abs(key(before)-value)<=Math.abs(key(after)-value)?before:after;
  };
  const element=(tag,attrs={})=>{
    const node=document.createElementNS("http://www.w3.org/2000/svg",tag);
    for(const [key,value] of Object.entries(attrs))node.setAttribute(key,String(value));
    return node;
  };
  container.style.position="relative";
  const tip=document.createElement("div");
  tip.className="recorder-hover-tooltip";
  tip.style.cssText="position:absolute;display:none;z-index:20;pointer-events:none;"+
    "max-width:min(320px,calc(100% - 8px));max-height:330px;overflow:hidden;"+
    "padding:9px 11px;border-radius:9px;border:1px solid var(--divider-color,#bbb);"+
    "background:var(--card-background-color,var(--ha-card-background,#fff));"+
    "color:var(--primary-text-color,#222);box-shadow:0 4px 16px rgba(0,0,0,.22);"+
    "font:12px/1.5 var(--primary-font-family,Roboto,Arial,sans-serif);";
  container.append(tip);
  const plotWidth=width-left-right;
  const xFor=ms=>left+(ms-start)/(end-start)*plotWidth;
  const crosshair=element("line",{y1:top,y2:options.height-bottom,
    stroke:"var(--primary-text-color,#555)","stroke-width":1,
    "stroke-dasharray":"4 4",opacity:0.7,visibility:"hidden",
    "pointer-events":"none"});
  svg.append(crosshair);
  const markers=groups.map(g=>{
    const marker=element("circle",{r:4.5,fill:g.color,
      stroke:"var(--card-background-color,#fff)","stroke-width":1.5,
      visibility:"hidden","pointer-events":"none"});
    svg.append(marker);return marker;
  });
  const hit=element("rect",{x:left,y:top,width:plotWidth,
    height:options.height-top-bottom,fill:"transparent","pointer-events":"all"});
  hit.style.touchAction="pan-y";
  svg.append(hit);
  let active=-1;
  const hide=()=>{
    tip.style.display="none";
    crosshair.setAttribute("visibility","hidden");
    for(const marker of markers)marker.setAttribute("visibility","hidden");
  };
  function display(index,clientX,clientY){
    const ms=times[index];if(ms==null)return hide();
    active=index;
    tip.replaceChildren();
    const stamp=document.createElement("strong");
    stamp.textContent=new Date(ms).toLocaleString();
    stamp.style.display="block";stamp.style.marginBottom="5px";
    tip.append(stamp);
    const x=xFor(ms);
    crosshair.setAttribute("x1",x);crosshair.setAttribute("x2",x);
    crosshair.setAttribute("visibility","visible");
    groups.forEach((g,i)=>{
      const p=nearest(g.points,ms,v=>v.x);
      const valid=Math.abs(p.x-ms)<=tolerance;
      markers[i].setAttribute("visibility",valid?"visible":"hidden");
      if(valid){
        markers[i].setAttribute("cx",xFor(p.x));
        markers[i].setAttribute("cy",yFor(p.y,g.track));
      }
      const row=document.createElement("div");
      row.style.cssText="display:flex;align-items:center;gap:7px;white-space:nowrap";
      const color=document.createElement("span");
      color.style.cssText="width:9px;height:9px;border-radius:50%;flex:0 0 9px";
      color.style.background=g.color;
      const label=document.createElement("span");
      label.textContent=g.label;label.style.flex="1 1 auto";
      const value=document.createElement("strong");
      value.style.marginLeft="7px";value.style.fontVariantNumeric="tabular-nums";
      value.textContent=valid?
        p.y.toLocaleString(undefined,{maximumFractionDigits:2})+
          (g.unit?" "+g.unit:""):"—";
      row.append(color,label,value);tip.append(row);
    });
    tip.style.display="block";
    const parent=container.getBoundingClientRect();
    const xPixel=clientX-parent.left+13;
    const yPixel=clientY-parent.top-tip.offsetHeight-12;
    tip.style.left=Math.max(4,Math.min(parent.width-tip.offsetWidth-4,xPixel))+"px";
    tip.style.top=Math.max(4,Math.min(parent.height-tip.offsetHeight-4,
      yPixel<4?clientY-parent.top+12:yPixel))+"px";
  }
  const onPointer=event=>{
    const rect=svg.getBoundingClientRect();
    if(!rect.width||!Number.isFinite(event.clientX))return;
    const x=(event.clientX-rect.left)/rect.width*width;
    const target=start+Math.max(0,Math.min(1,(x-left)/plotWidth))*(end-start);
    const ms=nearest(times,target,t=>t);
    if(Math.abs(ms-target)>tolerance){hide();return;}
    display(times.indexOf(ms),event.clientX,event.clientY);
  };
  hit.addEventListener("pointermove",onPointer);
  hit.addEventListener("pointerdown",onPointer);
  hit.addEventListener("pointerleave",event=>{
    if(event.pointerType!=="touch")hide();
  });
  svg.setAttribute("tabindex","0");
  svg.addEventListener("keydown",event=>{
    if(event.key==="Escape"){hide();return;}
    if(event.key!=="ArrowLeft"&&event.key!=="ArrowRight")return;
    event.preventDefault();
    const direction=event.key==="ArrowRight"?1:-1;
    const next=active<0?(direction>0?0:times.length-1):
      Math.max(0,Math.min(times.length-1,active+direction));
    const bounds=svg.getBoundingClientRect();
    const fraction=xFor(times[next])/width;
    display(next,bounds.left+bounds.width*fraction,bounds.top+bounds.height/2);
  });
  svg.addEventListener("blur",hide);
}
