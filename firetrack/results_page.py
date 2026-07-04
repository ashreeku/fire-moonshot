"""Embedded HTML for the FireTrack Results view (served at /results).

Two independent panels: a 2D detection player (video frames with the tracked-drone
overlay) and a dependency-free 3D orbit plot of the reconstructed trajectory.
"""

RESULTS_HTML = b"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>FireTrack \xc2\xb7 Results</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Chakra+Petch:wght@600;700&family=IBM+Plex+Mono:wght@400;500&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
<style>
:root{--bg:#0B0F14;--panel:#141B24;--raised:#1B2531;--line:#263241;--line-soft:#1d2733;
 --text:#E8EEF4;--muted:#8895A7;--faint:#5C6B7E;--ember:#FF6A2B;--cyan:#36C5D9;--green:#46D17F;
 --disp:'Chakra Petch',system-ui,sans-serif;--mono:'IBM Plex Mono',ui-monospace,monospace;--body:'Inter',system-ui,sans-serif;}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font-family:var(--body);font-size:14px}
a{color:var(--cyan);text-decoration:none}
header{position:sticky;top:0;z-index:5;border-bottom:1px solid var(--line);background:rgba(11,15,20,.85);backdrop-filter:blur(10px)}
.hud{max-width:1180px;margin:0 auto;padding:13px 22px;display:flex;align-items:center;gap:16px}
.brand{font-family:var(--disp);font-weight:700;letter-spacing:.14em;font-size:18px}
.brand .ey{color:var(--ember)}
nav{margin-left:auto;display:flex;gap:6px}
nav a{font-family:var(--disp);font-weight:600;font-size:13px;letter-spacing:.04em;padding:7px 14px;border-radius:8px;border:1px solid var(--line);color:var(--muted)}
nav a.on{color:var(--bg);background:var(--cyan);border-color:var(--cyan)}
.wrap{max-width:1180px;margin:0 auto;padding:18px 22px 60px;display:grid;grid-template-columns:1fr 1fr;gap:18px}
@media (max-width:920px){.wrap{grid-template-columns:1fr}}
.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;overflow:hidden;display:flex;flex-direction:column}
.card .hd{padding:13px 16px;border-bottom:1px solid var(--line-soft);display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.card .hd h2{font-family:var(--disp);font-weight:600;font-size:14px;letter-spacing:.06em;margin:0;text-transform:uppercase}
.card .bd{padding:16px}
select{font-family:var(--mono);font-size:12px;background:var(--raised);color:var(--text);border:1px solid var(--line);border-radius:7px;padding:6px 9px;margin-left:auto;max-width:60%}
.stage2d{position:relative;background:#06090d;border:1px solid var(--line);border-radius:9px;overflow:hidden;min-height:240px;display:flex;align-items:center;justify-content:center}
.fwrap{position:relative;display:inline-block;max-width:100%;line-height:0}
.fwrap img{display:block;width:100%;height:auto}
.fwrap canvas{position:absolute;inset:0;width:100%;height:100%}
.scene3d{background:#06090d;border:1px solid var(--line);border-radius:9px}
.controls{display:flex;align-items:center;gap:10px;margin-top:12px}
button{font-family:var(--disp);font-weight:600;font-size:13px;color:var(--text);background:var(--raised);border:1px solid var(--line);border-radius:8px;padding:8px 13px;cursor:pointer}
button:hover{border-color:var(--cyan)}
button.primary{background:var(--ember);border-color:var(--ember);color:#1a0d05}
button.on{background:var(--cyan);border-color:var(--cyan);color:#06121a}
input[type=range]{flex:1;accent-color:var(--ember)}
.meta{font-family:var(--mono);font-size:12px;color:var(--muted);margin-top:10px;display:flex;gap:16px;flex-wrap:wrap}
.meta b{color:var(--text);font-weight:500}
.legend{display:flex;gap:14px;font-family:var(--mono);font-size:11px;color:var(--muted);margin-top:10px;flex-wrap:wrap}
.legend i{display:inline-block;width:14px;height:3px;border-radius:2px;margin-right:5px;vertical-align:middle}
.empty{color:var(--muted);text-align:center;padding:40px 10px;font-family:var(--mono);font-size:13px}
.hint{color:var(--faint);font-size:11px;font-family:var(--mono);margin-top:6px}
:focus-visible{outline:2px solid var(--cyan);outline-offset:2px}
</style></head>
<body>
<header><div class="hud">
  <div class="brand">FIRE<span class="ey">TRACK</span></div>
  <nav><a href="/">Control</a><a href="/results" class="on">Results</a></nav>
</div></header>
<div class="wrap">

  <section class="card">
    <div class="hd"><h2>Detection \xc2\xb7 2D</h2><select id="detsel"></select></div>
    <div class="bd">
      <div class="stage2d" id="detstage"><div class="empty" id="detempty">Run detection, then pick a camera.</div>
        <div class="fwrap" id="fwrap" style="display:none"><img id="detframe" alt=""><canvas id="detoverlay"></canvas></div></div>
      <div class="controls" id="detctrl" style="display:none">
        <button id="detplay">Play</button>
        <input type="range" id="detscrub" min="0" value="0">
        <span class="meta" id="detframenum"></span>
      </div>
      <div class="controls" id="detedit" style="display:none">
        <button id="editbtn" onclick="toggleEdit()">Edit track</button>
        <button id="clearframe" onclick="clearFrame()" style="display:none">Clear frame</button>
        <button id="savedits" class="primary" onclick="saveEdits()" style="display:none">Save</button>
        <span class="meta" id="editinfo"></span>
      </div>
      <div class="meta" id="detmeta"></div>
    </div>
  </section>

  <section class="card">
    <div class="hd"><h2>Reconstruction \xc2\xb7 3D</h2><select id="trisel"></select></div>
    <div class="bd">
      <canvas class="scene3d" id="scene" width="520" height="360"></canvas>
      <div class="legend">
        <span><i style="background:var(--cyan)"></i>smoothed</span>
        <span><i style="background:var(--faint)"></i>raw</span>
        <span><i style="background:var(--green)"></i>ground truth</span>
        <span><i style="background:var(--ember)"></i>current frame</span>
      </div>
      <div class="controls" id="trictrl" style="display:none">
        <button id="triplay">Play</button>
        <input type="range" id="triscrub" min="0" value="0">
      </div>
      <div class="meta" id="trimeta"></div>
      <div class="controls" id="tridl" style="display:none">
        <button onclick="downloadTraj('csv')">Download CSV</button>
        <button onclick="downloadTraj('npz')">Download .npz</button>
      </div>
      <div class="hint">Drag to orbit \xc2\xb7 scroll to zoom</div>
    </div>
  </section>

</div>
<script>
async function getResults(){return (await fetch('/api/results')).json();}
function opt(v,t){const o=document.createElement('option');o.value=v;o.textContent=t;return o;}

/* ---------- Detection 2D ---------- */
let det={data:null,frame:0,timer:null};
const dimg=document.getElementById('detframe'),dov=document.getElementById('detoverlay');
async function loadDet(dir){
 stopDet();
 det.data=await (await fetch('/api/centroids?dir='+encodeURIComponent(dir))).json();
 det.dir=dir;det.frame=0;det.edits={};det.editing=false;
 document.getElementById('detempty').style.display='none';
 document.getElementById('fwrap').style.display='inline-block';
 document.getElementById('detctrl').style.display='flex';
 document.getElementById('detedit').style.display='flex';
 document.getElementById('editbtn').textContent='Edit track';document.getElementById('editbtn').classList.remove('on');
 document.getElementById('clearframe').style.display='none';
 document.getElementById('savedits').style.display='none';
 document.getElementById('editinfo').textContent='';dov.style.cursor='';
 const sc=document.getElementById('detscrub');sc.max=det.data.n_frames-1;sc.value=0;
 const m=det.data;document.getElementById('detmeta').innerHTML=
   `<span>frames <b>${m.n_frames}</b></span><span>detected <b>${m.n_detected}</b> (${(100*m.n_detected/m.n_frames||0).toFixed(0)}%)</span><span><b>${m.width}\xc3\x97${m.height}</b></span>`;
 showFrame(0);
}
function showFrame(i){
 det.frame=i;
 dimg.onload=drawOverlay;
 dimg.src='/api/result-frame?dir='+encodeURIComponent(det.dir)+'&frame='+i;
 document.getElementById('detscrub').value=i;
 document.getElementById('detframenum').innerHTML=`<b>frame ${i}</b> / ${det.data.n_frames-1}`;
}
function drawOverlay(){
 const w=dimg.clientWidth,h=dimg.clientHeight;dov.width=w;dov.height=h;
 const ctx=dov.getContext('2d');ctx.clearRect(0,0,w,h);
 const c=det.data.centroids[det.frame],edited=det.edits&&(det.frame in det.edits);
 if(!c||c[0]==null){ctx.fillStyle='#FFC857';ctx.font='12px monospace';
   ctx.fillText(edited?'cleared (edited)':'no detection this frame',10,18);return;}
 const sx=w/det.data.width,sy=h/det.data.height,x=c[0]*sx,y=c[1]*sy;
 ctx.strokeStyle=edited?'#FF6A2B':'#46D17F';ctx.lineWidth=2;
 ctx.beginPath();ctx.arc(x,y,11,0,7);ctx.stroke();
 ctx.beginPath();ctx.moveTo(x-16,y);ctx.lineTo(x+16,y);ctx.moveTo(x,y-16);ctx.lineTo(x,y+16);ctx.stroke();
}
function updateEditInfo(){const n=Object.keys(det.edits||{}).length,info=document.getElementById('editinfo');
 info.textContent=!det.editing?'':(n?`${n} unsaved edit(s)`:'Click the drone to set it \\u00b7 Clear = no detection');
 document.getElementById('savedits').style.display=n?'inline-flex':'none';}
function toggleEdit(){det.editing=!det.editing;stopDet();
 const b=document.getElementById('editbtn');b.textContent=det.editing?'Done':'Edit track';b.classList.toggle('on',det.editing);
 document.getElementById('clearframe').style.display=det.editing?'inline-flex':'none';
 dov.style.cursor=det.editing?'crosshair':'';updateEditInfo();}
function clearFrame(){if(!det.editing||!det.data)return;
 det.data.centroids[det.frame]=[null,null];det.edits[det.frame]={clear:true};drawOverlay();updateEditInfo();}
async function saveEdits(){
 const edits=Object.entries(det.edits).map(([f,v])=>v.clear?{frame:+f,clear:true}:{frame:+f,x:v.x,y:v.y});
 if(!edits.length)return;
 const r=await fetch('/api/centroids/edit',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({dir:det.dir,edits})});
 const d=await r.json().catch(()=>({}));const info=document.getElementById('editinfo');
 if(!r.ok){info.textContent='Save failed: '+(d.error||'error');return;}
 det.edits={};
 if(d.n_detected!=null){det.data.n_detected=d.n_detected;
   document.getElementById('detmeta').innerHTML=`<span>frames <b>${det.data.n_frames}</b></span><span>detected <b>${d.n_detected}</b> (${(100*d.n_detected/det.data.n_frames||0).toFixed(0)}%)</span><span><b>${det.data.width}\xc3\x97${det.data.height}</b></span>`;}
 info.textContent='Saved \\u2014 re-run Triangulate to update 3D.';document.getElementById('savedits').style.display='none';
}
dov.addEventListener('click',e=>{
 if(!det.editing||!det.data)return;
 const r=dov.getBoundingClientRect();
 const x=(e.clientX-r.left)*det.data.width/r.width,y=(e.clientY-r.top)*det.data.height/r.height;
 det.data.centroids[det.frame]=[x,y];det.edits[det.frame]={x,y};drawOverlay();updateEditInfo();
});
function stopDet(){if(det.timer){clearInterval(det.timer);det.timer=null;document.getElementById('detplay').textContent='Play';}}
document.getElementById('detplay').onclick=()=>{
 if(det.timer){stopDet();return;}
 document.getElementById('detplay').textContent='Pause';
 det.timer=setInterval(()=>{let n=det.frame+1;if(n>=det.data.n_frames){stopDet();return;}showFrame(n);},100);
};
document.getElementById('detscrub').oninput=e=>{stopDet();showFrame(parseInt(e.target.value));};
window.addEventListener('resize',()=>{if(det.data)drawOverlay();});

/* ---------- Reconstruction 3D ---------- */
let tri={data:null,yaw:0.6,pitch:-0.5,zoom:1,marker:0,timer:null};
const cv=document.getElementById('scene');
function finitePts(arrs){const o=[];for(const a of arrs)if(a)for(const p of a)if(p&&p[0]!=null)o.push(p);return o;}
function setupView(){
 const pts=finitePts([tri.data.smooth,tri.data.raw,tri.data.gt]);
 if(!pts.length){tri.center=[0,0,0];tri.extent=1;return;}
 const lo=[1e9,1e9,1e9],hi=[-1e9,-1e9,-1e9];
 for(const p of pts)for(let k=0;k<3;k++){lo[k]=Math.min(lo[k],p[k]);hi[k]=Math.max(hi[k],p[k]);}
 tri.center=[0,1,2].map(k=>(lo[k]+hi[k])/2);
 tri.extent=Math.max(hi[0]-lo[0],hi[1]-lo[1],hi[2]-lo[2],1e-6);
}
function project(p){
 const cy=Math.cos(tri.yaw),sy=Math.sin(tri.yaw),cp=Math.cos(tri.pitch),sp=Math.sin(tri.pitch);
 const x=p[0]-tri.center[0],y=p[1]-tri.center[1],z=p[2]-tri.center[2];
 const x1=cy*x+sy*z,z1=-sy*x+cy*z,y1=y;
 const y2=cp*y1-sp*z1;
 const s=tri.zoom*0.7*Math.min(cv.width,cv.height)/tri.extent;
 return [cv.width/2+x1*s, cv.height/2-y2*s];
}
function poly(ctx,arr,color,dash){
 ctx.strokeStyle=color;ctx.lineWidth=2;ctx.setLineDash(dash||[]);ctx.beginPath();
 let pen=false;
 for(const p of arr){if(!p||p[0]==null){pen=false;continue;}const s=project(p);if(!pen){ctx.moveTo(s[0],s[1]);pen=true;}else ctx.lineTo(s[0],s[1]);}
 ctx.stroke();ctx.setLineDash([]);
}
function axes(ctx){
 const L=tri.extent*0.45,o=tri.center;const cols=['#c0566f','#6fae6f','#5aa0c0'];const lbl=['x','y','z'];
 for(let k=0;k<3;k++){const e=o.slice();e[k]+=L;const a=project(o),b=project(e);
   ctx.strokeStyle=cols[k];ctx.lineWidth=1;ctx.setLineDash([3,3]);ctx.beginPath();ctx.moveTo(a[0],a[1]);ctx.lineTo(b[0],b[1]);ctx.stroke();ctx.setLineDash([]);
   ctx.fillStyle=cols[k];ctx.font='11px monospace';ctx.fillText(lbl[k],b[0]+3,b[1]);}
}
function drawScene(){
 const ctx=cv.getContext('2d');ctx.clearRect(0,0,cv.width,cv.height);
 if(!tri.data){return;}
 axes(ctx);
 const raw=tri.data.raw;ctx.fillStyle='#5C6B7E';
 for(const p of raw){if(p&&p[0]!=null){const s=project(p);ctx.fillRect(s[0]-1,s[1]-1,2,2);}}
 if(tri.data.gt)poly(ctx,tri.data.gt,'#46D17F',[5,4]);
 poly(ctx,tri.data.smooth,'#36C5D9');
 const m=tri.data.smooth[tri.marker]||tri.data.raw[tri.marker];
 if(m&&m[0]!=null){const s=project(m);ctx.fillStyle='#FF6A2B';ctx.beginPath();ctx.arc(s[0],s[1],5,0,7);ctx.fill();}
}
function downloadTraj(fmt){if(tri.dir)window.location.href='/api/trajectory/download?dir='+encodeURIComponent(tri.dir)+'&fmt='+fmt;}
async function loadTri(dir){
 stopTri();
 tri.dir=dir;
 tri.data=await (await fetch('/api/trajectory?dir='+encodeURIComponent(dir))).json();
 tri.marker=0;setupView();drawScene();
 document.getElementById('trictrl').style.display='flex';
 document.getElementById('tridl').style.display='flex';
 const sc=document.getElementById('triscrub');sc.max=tri.data.smooth.length-1;sc.value=0;
 const mt=tri.data.metrics;document.getElementById('trimeta').innerHTML=
   `<span>triangulated <b>${mt.n_triangulated}</b>/${tri.data.n_frames}</span>`+
   (mt.median_reproj_px!=null?`<span>reproj <b>${mt.median_reproj_px.toFixed(1)}px</b></span>`:'')+
   (mt.has_gt&&mt.rmse_smooth_m!=null?`<span>RMSE vs GT <b>${mt.rmse_smooth_m.toFixed(3)}m</b></span>`:'<span>no ground truth</span>');
}
function stopTri(){if(tri.timer){clearInterval(tri.timer);tri.timer=null;document.getElementById('triplay').textContent='Play';}}
document.getElementById('triplay').onclick=()=>{
 if(tri.timer){stopTri();return;}
 document.getElementById('triplay').textContent='Pause';
 tri.timer=setInterval(()=>{tri.marker++;if(tri.marker>=tri.data.smooth.length){stopTri();tri.marker=tri.data.smooth.length-1;}
   document.getElementById('triscrub').value=tri.marker;drawScene();},60);
};
document.getElementById('triscrub').oninput=e=>{stopTri();tri.marker=parseInt(e.target.value);drawScene();};
let drag=null;
cv.addEventListener('pointerdown',e=>{drag=[e.clientX,e.clientY];cv.setPointerCapture(e.pointerId);});
cv.addEventListener('pointermove',e=>{if(!drag)return;tri.yaw+=(e.clientX-drag[0])*0.01;tri.pitch+=(e.clientY-drag[1])*0.01;
 tri.pitch=Math.max(-1.5,Math.min(1.5,tri.pitch));drag=[e.clientX,e.clientY];drawScene();});
cv.addEventListener('pointerup',()=>drag=null);
cv.addEventListener('wheel',e=>{e.preventDefault();tri.zoom*=e.deltaY<0?1.1:0.9;tri.zoom=Math.max(0.2,Math.min(6,tri.zoom));drawScene();},{passive:false});

/* ---------- init ---------- */
(async()=>{
 const r=await getResults();
 const ds=document.getElementById('detsel'),ts=document.getElementById('trisel');
 if(!r.detections.length)ds.appendChild(opt('','no detections yet'));
 r.detections.forEach(d=>ds.appendChild(opt(d.dir,`${d.label} \xc2\xb7 ${d.source}`)));
 if(!r.trajectories.length)ts.appendChild(opt('','no reconstructions yet'));
 r.trajectories.forEach(t=>ts.appendChild(opt(t.dir,`${t.run} \xc2\xb7 ${t.source}`)));
 ds.onchange=e=>{if(e.target.value)loadDet(e.target.value);};
 ts.onchange=e=>{if(e.target.value)loadTri(e.target.value);};
 if(r.detections.length)loadDet(r.detections[0].dir);
 if(r.trajectories.length)loadTri(r.trajectories[0].dir);
})();
</script>
</body></html>"""
