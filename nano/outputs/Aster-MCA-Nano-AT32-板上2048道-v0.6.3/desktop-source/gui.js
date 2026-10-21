'use strict';
const $ = id => document.getElementById(id);
const token = document.querySelector('meta[name="aster-token"]').content;
let state = null, operation = false, localError = '', localNotice = '', zoom = null, drag = null, geometry = null;
let previousPhase = null, currentPlot = null;
let previousRecord = null;
const canvas = $('plot'), ctx = canvas.getContext('2d');
const fmt = (n, digits=0) => Number(n || 0).toLocaleString('zh-CN', {maximumFractionDigits:digits});
async function api(path, body) {
  const options = {headers: {'X-Aster-Token':token}};
  if (body !== undefined) {options.method='POST'; options.headers['Content-Type']='application/json'; options.body=JSON.stringify(body);}
  const response = await fetch('/api/'+path, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || '操作失败');
  return data;
}
function nameOf(record) {
  if (!record) return '尚无记录';
  const prefix = record.name.startsWith('cs-source') ? '铯源记录' : record.name.startsWith('detector-background') ? '探头本底' : record.name.startsWith('open-') ? '空载记录' : '采集记录';
  return prefix + (record.started ? ' · '+record.started.slice(0,19).replace('T',' ') : ' · '+record.name);
}
async function action(path, body) {
  operation=true; localError=''; update();
  try {const result=await api(path,body);localNotice=result.path?'已保存：'+result.path:''; state=await api('state');}
  catch(e) {localError=e.message;}
  finally {operation=false; update();}
}
function combine(values,n) {
  const width=values.length/n, result=new Array(n).fill(0);
  if(width<1 || !Number.isInteger(width)) throw new Error('此记录没有足够的原始道数');
  for(let j=0;j<values.length;j++) result[Math.floor(j/width)]+=values[j];
  return result;
}
function plotData() {
  if (!state?.current) return null;
  const r=state.current, mode=$('mode').value, n=Number($('channels').value);
  const raw=combine(r.histogram.counts[mode],n), seconds=r.seconds || 0;
  const bg=state.background_compatible ? state.background : null;
  const background=bg ? combine(bg.histogram.counts[mode],n) : null;
  const bgScaled=background && seconds>0 ? background.map(v=>v*seconds/bg.seconds) : null;
  const useRate=$('units').value==='rate', factor=useRate?(seconds>0?1/seconds:0):1;
  const net=$('net').checked && !!bgScaled;
  const values=raw.map((v,i)=>(v-(net?bgScaled[i]:0))*factor);
  return {r,mode,n,raw,seconds,bg,background,bgScaled,useRate,factor,net,values,
          overlay:!net && $('showBackground').checked && bgScaled ? bgScaled.map(v=>v*factor):null,
          width:r.histogram.ranges[mode]/n};
}
function update() {
  if (!state) return;
  const busy=state.busy || operation, r=state.current;
  if(r){
    for(const option of $('mode').options) option.disabled=!(option.value in r.histogram.counts);
    if(!( $('mode').value in r.histogram.counts)) $('mode').value='area8';
    for(const option of $('channels').options) option.disabled=Number(option.value)>r.histogram.master_channels;
    if(r.name!==previousRecord){if(r.acquisition_mode==='histogram')$('channels').value='2048';zoom=null;previousRecord=r.name;}
    if(Number($('channels').value)>r.histogram.master_channels)$('channels').value=String(r.histogram.master_channels);
  }
  const selected=$('port').value;
  if (JSON.stringify([...$('port').options].map(o=>o.value))!==JSON.stringify(state.ports)) {
    $('port').replaceChildren(...state.ports.map(p=>new Option(p.replace('/dev/cu.',''),p)));
    if(state.ports.includes(selected)) $('port').value=selected;
  }
  $('connect').disabled=busy || !state.ports.length;
  $('start').disabled=busy || !state.connected;
  $('stop').disabled=!['starting','acquiring','stopping'].includes(state.phase);
  for(const id of ['port','seconds','threshold','condition','notes','load','setBackground','clearBackground']) $(id).disabled=busy;
  $('exportCsv').disabled=!r?.valid || busy;
  $('exportPng').disabled=!r?.valid || busy;
  $('showBackground').disabled=!state.background_compatible;
  $('net').disabled=!state.background_compatible;
  if(!state.background_compatible) $('net').checked=false;
  if($('net').checked) $('log').checked=false;
  $('log').disabled=$('net').checked;
  $('connectionBadge').textContent=state.connected?`AT32 v${state.connected.info.fw} · 已连接`:'未连接设备 · 可查看历史谱';
  const rate=state.connected?.info.sample_rate_hz || state.current?.sample_rate_hz;
  const burst=state.connected ? state.connected.info.fw==='0.5.0' : r?.acquisition_mode==='burst';
  const onboard=state.connected ? ['0.6.0','0.6.1','0.6.2','0.6.3'].includes(state.connected.info.fw) : r?.acquisition_mode==='histogram';
  $('acquisitionMode').textContent=onboard?'AT32 · 4 MS/s · 板上累计 2048 道 · 结束后读取能谱':burst?'AT32 · 4 MS/s 分段采集 · 采满后上传 · 电脑端处理':rate===4000000?'AT32 · 4 MS/s 连续采样 · 脉冲片段传输 · 电脑端处理':rate===1000000?'AT32 · 1 MS/s 全波形传输 · 电脑端处理':'AT32 · 1M / 4M 采集';
  $('durationLabel').textContent=burst?'总时长 / 秒':'时长 / 秒';
  $('connectionBadge').className='badge'+(state.connected?' active':'');
  const labels={starting:'正在开始',acquiring:'采集中',stopping:'正在停止并校验',error:'本轮无效',complete:'采集完成',connecting:'正在连接',loading:'正在打开'};
  $('phase').textContent=labels[state.phase] || (state.origin==='history'?'历史记录':'就绪');
  $('phase').className='badge'+(state.phase==='error'?' bad':state.busy?' active':'');
  $('recordName').textContent=nameOf(r);
  $('validity').textContent=r?.valid?`${r.sample_rate_hz/1e6 || 1} MS/s 记录 · 采集完整性校验通过 · 未能量标定`:state.busy?'数据暂存中，结束后校验':'未能量标定';
  const waiting=r?.awaiting_result && state.busy;
  $('elapsed').textContent=waiting?'结束后确认':r?fmt(r.seconds,3)+' s':'—';
  $('coverageText').textContent=waiting?`剩余约 ${fmt(r.remaining_seconds??state.requested_seconds,1)} 秒 · 板上累计中，结束后显示能谱`:
    r?.acquisition_mode==='histogram'?`采样覆盖 ${fmt(r.seconds,3)} s · 总耗时（含读取）${fmt(r.wall_seconds,2)} s · 保存 2048 道能谱`:
    r?.acquisition_mode==='burst'?`总耗时 ${fmt(r.wall_seconds,2)} s · 采样占比 ${fmt((r.duty_cycle||0)*100,1)}% · 分段之间未采样`:'';
  $('accepted').textContent=waiting?'结束后读取':r?fmt(r.accepted):'—';
  $('rate').textContent=r&&r.seconds>0?fmt(r.accepted/r.seconds,1)+' /s':'—';
  $('conditionText').textContent=r?'记录条件：'+r.condition:'';
  $('pathText').textContent='自动保存位置：'+(r?.path||state.save_root);
  $('backgroundText').textContent=state.background?'本底：'+nameOf(state.background)+(state.background_compatible?'':'（处理参数不同，叠加与扣本底已禁用）'):'未设置本底';
  const err=localError || state.error;
  $('error').hidden=!err; $('error').textContent=err;
  $('notice').hidden=!localNotice; $('notice').textContent=localNotice;
  render();
}
function niceStep(span,target=6) {
  const raw=span/target, power=10**Math.floor(Math.log10(raw||1)), fraction=raw/power;
  return power*(fraction<=1?1:fraction<=2?2:fraction<=5?5:10);
}
function render() {
  const box=canvas.getBoundingClientRect(), ratio=window.devicePixelRatio||1;
  if(!box.width||!box.height) return;
  if(canvas.width!==Math.round(box.width*ratio)||canvas.height!==Math.round(box.height*ratio)) {canvas.width=Math.round(box.width*ratio);canvas.height=Math.round(box.height*ratio);}
  ctx.setTransform(ratio,0,0,ratio,0,0);ctx.clearRect(0,0,box.width,box.height);ctx.fillStyle='#fff';ctx.fillRect(0,0,box.width,box.height);
  const d=plotData();currentPlot=d;
  if(!d){ctx.fillStyle='#758591';ctx.font='14px -apple-system,sans-serif';ctx.fillText('连接设备开始采集，或打开已保存的记录。',55,80);return;}
  const {n,values}=d;
  let xmin=zoom?Math.max(0,zoom[0]):0, xmax=zoom?Math.min(n,zoom[1]):n;
  if(xmax-xmin<2){xmin=0;xmax=n;zoom=null;}
  const left=64,right=box.width-24,top=53,bottom=box.height-47;
  const visible=values.slice(Math.floor(xmin),Math.ceil(xmax));
  if(d.overlay) visible.push(...d.overlay.slice(Math.floor(xmin),Math.ceil(xmax)));
  const logarithmic=$('log').checked && !d.net;
  let ymax=Math.max(1,...visible)*1.12,ymin=Math.min(0,...visible)*1.15,ticks=[];
  if(logarithmic) {
    const positives=visible.filter(v=>v>0);const floor=positives.length?Math.min(...positives):1;
    ymin=10**Math.floor(Math.log10(floor));ymax=10**Math.ceil(Math.log10(Math.max(ymax,ymin*10)));
    for(let p=Math.log10(ymin);p<=Math.log10(ymax)+.001;p++) ticks.push(10**p);
  } else {
    const step=niceStep(ymax-ymin);ymax=Math.ceil(ymax/step)*step;ymin=Math.floor(ymin/step)*step;
    for(let y=ymin;y<=ymax+step*.01;y+=step) ticks.push(y);
  }
  const x=v=>left+(v-xmin)/(xmax-xmin)*(right-left);
  const y=v=>bottom-(logarithmic?(Math.log10(Math.max(v,ymin))-Math.log10(ymin))/(Math.log10(ymax)-Math.log10(ymin)):(v-ymin)/(ymax-ymin))*(bottom-top);
  geometry={left,right,top,bottom,xmin,xmax,x,y};
  ctx.font='11px -apple-system,sans-serif';ctx.fillStyle='#263c4b';ctx.textAlign='left';
  ctx.fillText(`${d.mode==='area8'?'8 µs 积分谱':'采样峰高谱'} · ${n} 道 · ${fmt(d.seconds,3)} s · 未能量标定`,left,19);
  ctx.fillStyle='#74848e';ctx.fillText(nameOf(d.r),left,36);
  ctx.textAlign='right';ctx.fillStyle=d.net?'#229272':'#1679ad';ctx.fillText(d.net?'净谱：当前记录 − 本底':'蓝：当前记录',right,19);
  if(d.overlay){ctx.fillStyle='#8796a1';ctx.fillText('灰：本底（按时长归一）',right,36);}
  ctx.strokeStyle='#e8edf1';ctx.lineWidth=1;
  for(const tick of ticks){ctx.beginPath();ctx.moveTo(left,y(tick));ctx.lineTo(right,y(tick));ctx.stroke();ctx.fillStyle='#6c7c88';ctx.textAlign='right';ctx.fillText(fmt(tick,3),left-9,y(tick)+4);}
  const step=niceStep(xmax-xmin,9);
  for(let tick=Math.ceil(xmin/step)*step;tick<=xmax;tick+=step){ctx.beginPath();ctx.moveTo(x(tick),top);ctx.lineTo(x(tick),bottom);ctx.stroke();ctx.textAlign='center';ctx.fillText(fmt(tick),x(tick),bottom+19);}
  ctx.strokeStyle='#a5b4be';ctx.beginPath();ctx.moveTo(left,top);ctx.lineTo(left,bottom);ctx.lineTo(right,bottom);ctx.stroke();
  ctx.textAlign='center';ctx.fillStyle='#536674';ctx.fillText(`道号（每道 ${d.width} ${d.mode==='area8'?'ADC 码·µs':'ADC 码'}）`,(left+right)/2,box.height-7);
  ctx.save();ctx.translate(15,(top+bottom)/2);ctx.rotate(-Math.PI/2);ctx.fillText((d.net?'净':'')+(d.useRate?'计数 / 秒':'计数')+(logarithmic?'（对数）':''),0,0);ctx.restore();
  function stairs(data,color){ctx.save();ctx.beginPath();ctx.rect(left,top,right-left,bottom-top);ctx.clip();ctx.beginPath();ctx.lineWidth=1.35;ctx.strokeStyle=color;let begun=false;
    for(let j=Math.floor(xmin);j<Math.ceil(xmax)&&j<n;j++){if(logarithmic&&data[j]<=0){begun=false;continue;}const xx=x(j),yy=y(data[j]);if(begun)ctx.lineTo(xx,yy);else ctx.moveTo(xx,yy);ctx.lineTo(x(j+1),yy);begun=true;}ctx.stroke();ctx.restore();}
  if(d.overlay) stairs(d.overlay,'#9aa7b0');
  stairs(values,d.net?'#229272':'#1679ad');
  if(d.net){ctx.strokeStyle='#909da6';ctx.beginPath();ctx.moveTo(left,y(0));ctx.lineTo(right,y(0));ctx.stroke();}
  if(drag){ctx.fillStyle='#1679ad20';ctx.fillRect(Math.min(drag.start,drag.current),top,Math.abs(drag.current-drag.start),bottom-top);}
  if(state.phase==='error'){ctx.fillStyle='#a33c2a';ctx.font='bold 22px -apple-system,sans-serif';ctx.textAlign='center';ctx.fillText('本轮无效 · 不用于能谱比较',(left+right)/2,(top+bottom)/2);}
  const h=d.r.histogram, inside=d.raw.reduce((a,b)=>a+b,0);
  $('inrange').textContent=d.r.awaiting_result&&state.busy?'结束后读取':fmt(inside);
  $('mapping').textContent=`每道 ${d.width} ${d.mode==='area8'?'ADC 码·µs':'ADC 码'} · 量程外 ${fmt(h.under[d.mode]+h.over[d.mode])} 个`+(logarithmic?' · 零计数道不绘制':'');
  $('legend').replaceChildren();
  for(const [label,color] of [[d.net?'扣本底后的净谱':'当前记录',d.net?'#229272':'#1679ad'],...(d.overlay?[['本底（按采样时长归一）','#9aa7b0']]:[])]){
    const span=document.createElement('span'),dot=document.createElement('i');dot.className='dot';dot.style.backgroundColor=color;span.append(dot,document.createTextNode(label));$('legend').append(span);
  }
}
async function records(){const items=await api('records'),selected=$('records').value;$('records').replaceChildren(...items.map(r=>new Option(`${r.name} · ${r.seconds.toFixed(2)} s`,r.id)));const current=items.find(r=>r.name===state?.current?.name);if(current)$('records').value=current.id;else if(items.some(r=>r.id===selected))$('records').value=selected;}
function csvExport(){const d=plotData();if(!d?.r.valid)return;action('export-csv',{mode:d.mode,channels:d.n,record_name:d.r.name});}
$('connect').onclick=async()=>{
  await action('connect',{port:$('port').value});
  if(state?.connected){
    const sparse=state.connected.info.fw==='0.4.4';
    const burst=state.connected.info.fw==='0.5.0';
    const onboard=['0.6.0','0.6.1','0.6.2','0.6.3'].includes(state.connected.info.fw);
    $('threshold').value=sparse?64:20;
    localNotice=onboard?'板上采谱：设定时间后独立累计 2048 道，结束时读取结果。仅保存能谱；需要提前结束可点“停止”。':burst?'分段模式：每次采 2.048 ms，再上传完整波形。时长设置表示总耗时；门限只用于电脑端分析，默认 20 码。':sparse?'4M 测试模式：门限默认 64 码；20 码曾因空载波动导致过载。低幅度事件灵敏度尚待优化。':'';
    update();
  }
};
$('start').onclick=()=>{zoom=null;action('start',{seconds:Number($('seconds').value),threshold:Number($('threshold').value),condition:$('condition').value+($('notes').value?'；'+$('notes').value:'')});};
$('stop').onclick=()=>action('stop',{});
$('load').onclick=()=>{zoom=null;action('load',{id:$('records').value});};
$('refresh').onclick=()=>records().catch(e=>{localError=e.message;update();});
$('setBackground').onclick=()=>action('background',{});
$('clearBackground').onclick=()=>action('background',{clear:true});
$('exportCsv').onclick=csvExport;
$('exportPng').onclick=()=>{const d=plotData();if(!d?.r.valid)return;action('export-png',{mode:d.mode,channels:d.n,record_name:d.r.name,image:canvas.toDataURL('image/png')});};
for(const id of ['mode','channels','units','log','showBackground','net']) $(id).onchange=()=>{if(id==='mode'||id==='channels')zoom=null;update();};
$('resetZoom').onclick=()=>{zoom=null;render();};
$('fitZoom').onclick=()=>{const d=plotData();if(!d)return;let last=0;for(let i=0;i<d.n;i++)if(d.raw[i])last=i;zoom=[0,Math.min(d.n,Math.max(32,Math.ceil((last+1)*1.1)))];render();};
canvas.onpointerdown=e=>{if(!geometry)return;const px=e.offsetX;if(px<geometry.left||px>geometry.right)return;drag={start:px,current:px};canvas.setPointerCapture(e.pointerId);};
canvas.onpointermove=e=>{if(!geometry||!currentPlot)return;const g=geometry,px=Math.max(g.left,Math.min(g.right,e.offsetX));if(drag){drag.current=px;render();return;}const ch=Math.floor(g.xmin+(px-g.left)/(g.right-g.left)*(g.xmax-g.xmin));if(ch<0||ch>=currentPlot.n)return;const tip=$('tooltip');tip.hidden=false;tip.textContent=`道 ${ch}\n计数 ${fmt(currentPlot.raw[ch])}`;tip.style.left=Math.min(e.offsetX+20,canvas.clientWidth-105)+'px';tip.style.top=Math.max(3,e.offsetY-55)+'px';};
canvas.onpointerup=e=>{if(!drag||!geometry)return;const g=geometry;if(Math.abs(drag.current-drag.start)>12){const f=px=>g.xmin+(px-g.left)/(g.right-g.left)*(g.xmax-g.xmin);zoom=[Math.floor(f(Math.min(drag.start,drag.current))),Math.ceil(f(Math.max(drag.start,drag.current)))];}drag=null;render();};
canvas.onpointercancel=()=>{drag=null;render();};canvas.onpointerleave=()=>{$('tooltip').hidden=true;};canvas.ondblclick=()=>{zoom=null;render();};
new ResizeObserver(render).observe(canvas.parentElement);
async function poll(){try{state=await api('state');if(previousPhase===null||(state.phase!==previousPhase&&['complete','error'].includes(state.phase)))await records();previousPhase=state.phase;update();}catch(e){localError='本机程序未响应：'+e.message;$('error').hidden=false;$('error').textContent=localError;$('connectionBadge').textContent='本机程序连接中断';$('start').disabled=true;$('stop').disabled=true;}finally{setTimeout(poll,500);}}
poll();
