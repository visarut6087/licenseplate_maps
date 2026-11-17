const API = localStorage.getItem('plate_api_url') || 'http://127.0.0.1:8000';
const videoMode = location.pathname.endsWith('/video.html');
const $ = id => document.getElementById(id);
let sources = [], events = [], selected = null, busy = false, pinned = false, clearedThrough = 0;
const cards = new Map();
const statuses = {starting:'กำลังเปิด',running:'กำลังทำงาน',seeking:'กำลังเลื่อนวิดีโอ',reconnecting:'กำลังเชื่อมต่อใหม่',finished:'เล่นจบแล้ว',stopped:'หยุดแล้ว',error:'เกิดข้อผิดพลาด'};
const text = (tag, value, className) => {const el=document.createElement(tag);el.textContent=value;if(className)el.className=className;return el;};
const formatTime = value => {const seconds=Math.max(0,Math.floor(Number(value)||0));const h=Math.floor(seconds/3600);const m=Math.floor(seconds%3600/60);const s=seconds%60;return h?`${h}:${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`:`${m}:${String(s).padStart(2,'0')}`;};
async function api(path, options={}) {
  const response=await fetch(API+path,{...options,signal:AbortSignal.timeout(path==='/api/models/load'?600000:30000)});
  if(!response.ok){let error;try{error=(await response.json()).detail;}catch{error=response.statusText;}throw new Error(typeof error==='string'?error:JSON.stringify(error));}
  return response.json();
}
function notice(message=''){$('notice').textContent=message;$('notice').hidden=!message;}
if(videoMode){$('page-title').textContent='ทดสอบอ่านทะเบียนจาก MP4';$('source-heading').textContent='วิดีโอทดสอบ';$('add-source').textContent='เลือกไฟล์ MP4';$('empty-title').textContent='เลือกวิดีโอเพื่อเริ่มทดสอบ';$('empty-description').textContent='ดูภาพวิดีโอ พร้อมภาพหลักฐานและผลอ่านทะเบียน';$('source-format').textContent='MP4';}
$(videoMode?'video-tab':'camera-tab').setAttribute('aria-current','page');
$('export-link').href=API+'/api/export.csv';
$('add-source').onclick=()=>videoMode?$('video-file').click():$('camera-form').hidden=false;
$('cancel-camera').onclick=()=>{$('camera-form').hidden=true;};
$('camera-form').onsubmit=async e=>{e.preventDefault();const button=e.submitter;button.disabled=true;$('camera-error').textContent='';try{await api('/api/cameras',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:$('camera-name').value,url:$('camera-url').value})});$('camera-form').reset();$('camera-form').hidden=true;await refresh();}catch(err){$('camera-error').textContent=err.message;}finally{button.disabled=false;}};
$('video-file').onchange=async()=>{const file=$('video-file').files[0];if(!file)return;const form=new FormData();form.append('file',file);$('add-source').disabled=true;notice('กำลังอัปโหลดวิดีโอ…');try{await api('/api/videos',{method:'POST',body:form});notice();await refresh();}catch(err){notice(err.message);}finally{$('add-source').disabled=false;$('video-file').value='';}};
$('load-models').onclick=async()=>{$('load-models').disabled=true;$('model-status').textContent='กำลังโหลดโมเดล อาจใช้เวลาหลายนาที';try{await api('/api/models/load',{method:'POST'});notice();}catch(err){notice(err.message);}finally{$('load-models').disabled=false;await refresh();}};
$('source-filter').onchange=()=>{selected=null;pinned=false;renderEvents();};
$('event-search').oninput=()=>{selected=null;pinned=false;renderEvents();};
$('clear-events').onclick=()=>{clearedThrough=Math.max(clearedThrough,...events.map(event=>Number(event.order)||0));selected=null;pinned=false;renderEvents();};
function renderSources(){
  const visible=sources.filter(s=>s.kind===(videoMode?'video':'camera'));
  $('source-count').textContent=visible.length+' แหล่งภาพ';$('empty-sources').hidden=visible.length>0;
  $('source-summary').textContent=visible.filter(s=>s.status==='running').length+' แหล่งภาพกำลังทำงาน';
  for(const [id,card] of cards)if(!visible.some(s=>s.id===id)){card.remove();cards.delete(id);}
  for(const s of visible){
    let card=cards.get(s.id);
    if(!card){card=text('article','','source-card');const meta=text('div','','source-meta');const label=text('div');label.append(text('strong',s.name),text('small','','state'));const stop=text('button','หยุด','secondary');stop.onclick=async()=>{try{await api('/api/sources/'+s.id,{method:'DELETE'});await refresh();}catch(err){notice(err.message);}};meta.append(label,stop);const img=document.createElement('img');img.alt='ภาพสด '+s.name;img.hidden=true;const wait=text('div','กำลังรอภาพ…','source-wait');const error=text('p','','error');card.append(meta,img,wait);if(videoMode){const timeline=text('div','','video-timeline');const range=document.createElement('input');range.type='range';range.className='video-seek';range.min='0';range.max='0';range.step='.1';range.value='0';range.setAttribute('aria-label','เลื่อนตำแหน่งวิดีโอ');const clock=text('span','0:00 / 0:00','video-time');range.oninput=()=>{range.dataset.dragging='1';clock.textContent=formatTime(range.value)+' / '+formatTime(range.max);};range.onchange=async()=>{range.disabled=true;try{await api('/api/sources/'+s.id+'/seek',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({seconds:Number(range.value)})});notice();}catch(err){notice(err.message);}finally{delete range.dataset.dragging;range.disabled=false;await refresh();}};timeline.append(range,clock);card.append(timeline);}card.append(error);cards.set(s.id,card);$('source-list').append(card);}
    card.querySelector('.state').textContent=(statuses[s.status]||s.status)+(s.tracking?' · tracking '+s.tracking:'')+(s.ocr_queue?' · รอ OCR '+s.ocr_queue:'');
    card.querySelector('button').disabled=['stopped','finished'].includes(s.status);
    card.querySelector('.error').textContent=s.error||'';
    if(videoMode){const range=card.querySelector('.video-seek'),clock=card.querySelector('.video-time');const duration=Math.max(0,Number(s.duration_seconds)||0);range.max=String(duration);range.disabled=!duration||s.status==='stopped';if(!range.dataset.dragging)range.value=String(Math.min(duration,Number(s.media_seconds)||0));clock.textContent=formatTime(range.value)+' / '+formatTime(duration);}
    if(s.frames>0)loadFrame(card,s);
  }
  const filter=$('source-filter'), old=filter.value;
  if(filter.dataset.ids!==visible.map(s=>s.id).join(',')){filter.replaceChildren(new Option('ทั้งหมด',''),...visible.map(s=>new Option(s.name,s.id)));filter.value=old;filter.dataset.ids=visible.map(s=>s.id).join(',');}
}
async function loadFrame(card,source){
  if(card.loading)return;card.loading=true;
  try{const response=await fetch(API+'/api/sources/'+source.id+'/frame?t='+Date.now(),{signal:AbortSignal.timeout(5000)});if(!response.ok)return;const url=URL.createObjectURL(await response.blob());const img=card.querySelector('img');const old=img.src;img.onload=()=>{if(old.startsWith('blob:'))URL.revokeObjectURL(old);};img.src=url;img.hidden=false;card.querySelector('.source-wait').hidden=true;}catch{}finally{card.loading=false;}
}
function showEvent(event){
  selected=event.id;
  for(const [id,key] of [['full-image','full_image'],['crop-image','crop_image']]){$(id).src=API+'/api/results/'+event[key];$(id).hidden=false;}
  $('full-empty').hidden=$('crop-empty').hidden=true;
  $('event-id').textContent='#'+event.order;
  const details=[text('strong',event.plate_number,'plate'),text('span',event.province||'ไม่ทราบจังหวัด'),text('span',event.vehicle_type+' · '+(event.vehicle_probability*100).toFixed(1)+'%'),text('span',new Date(event.detected_at).toLocaleString('th-TH',{timeZone:'Asia/Bangkok',hour12:false}),'muted')];
  if(event.media_seconds!==null)details.push(text('span','วินาทีที่ '+event.media_seconds.toFixed(2),'muted'));
  const link=text('a','เปิด JSON','muted');link.href=API+'/api/results/'+event.json_file;link.target='_blank';link.rel='noopener';details.push(link);
  $('event-detail').replaceChildren(...details);
  for(const row of $('log-body').children)row.classList.toggle('selected',row.dataset.id===selected);
}
function renderEvents(){
  const kind=videoMode?'video':'camera';const allowed=new Set(sources.filter(s=>s.kind===kind).map(s=>s.id));
  const query=$('event-search').value.trim().toLocaleLowerCase('th');
  // Saved events remain available after backend restart; filtering applies only to known sources.
  const visible=events.filter(e=>(Number(e.order)||0)>clearedThrough&&(e.source_kind?e.source_kind===kind:(!sources.some(s=>s.id===e.source_id)||allowed.has(e.source_id)))&&(!$('source-filter').value||e.source_id===$('source-filter').value)&&(!query||[e.plate_number,e.province,e.vehicle_type,e.source_name,e.order].join(' ').toLocaleLowerCase('th').includes(query)));
  $('log-count').textContent=visible.length+' รายการ';$('empty-logs').hidden=visible.length>0;
  $('log-body').replaceChildren(...visible.map(e=>{const row=document.createElement('tr');row.dataset.id=e.id;const order=text('td','#'+e.order);order.append(text('small',new Date(e.detected_at).toLocaleTimeString('th-TH',{timeZone:'Asia/Bangkok',hour12:false})));const plate=text('td');const button=text('button',e.plate_number);button.onclick=()=>{pinned=e.id!==visible[0]?.id;showEvent(e);};plate.append(button,text('small',e.province||'ไม่ทราบจังหวัด'));row.append(order,plate,text('td',e.vehicle_type),text('td',e.source_name));row.classList.toggle('selected',e.id===selected);return row;}));
  const current=(pinned&&visible.find(e=>e.id===selected))||visible[0];if(current)showEvent(current);
  else{$('full-image').hidden=$('crop-image').hidden=true;$('full-empty').hidden=$('crop-empty').hidden=false;$('event-id').textContent='ยังไม่มีรายการ';$('event-detail').replaceChildren(text('span','เลือกทะเบียนในรายการเพื่อดูภาพคู่กัน','muted'));}
}
async function refresh(){if(busy)return;busy=true;try{const [health,newSources,newEvents]=await Promise.all([api('/api/health'),api('/api/sources'),api('/api/events?limit=100')]);sources=newSources;events=newEvents;$('connection').textContent='เชื่อมต่อ API แล้ว';$('connection-dot').classList.add('online');$('model-status').textContent=health.models.ready?'โมเดลพร้อมใช้งาน':health.models.loading?'กำลังโหลดโมเดล':health.models.error||'โมเดลยังไม่ถูกโหลด';renderSources();renderEvents();}catch(err){$('connection').textContent='เชื่อมต่อ API ไม่สำเร็จ';$('connection-dot').classList.remove('online');}finally{busy=false;}}
refresh();setInterval(refresh,1000);
setInterval(()=>{for(const source of sources){const card=cards.get(source.id);if(card&&source.frames>0&&source.status==='running')loadFrame(card,source);}},200);
