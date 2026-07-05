"""Embedded HTML for the FireTrack ground-control dashboard.

Kept in its own module so webui.py stays focused on routing/logic. The page is a
single self-contained document (styles + script inline) served at ``/``; it talks
to the same JSON API the server exposes.
"""

DASHBOARD_HTML = b"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>FireTrack \xc2\xb7 Ground Control</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Chakra+Petch:wght@500;600;700&family=IBM+Plex+Mono:wght@400;500;600&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
<style>
:root{
  --bg:#0B0F14; --panel:#141B24; --raised:#1B2531; --line:#263241; --line-soft:#1d2733;
  --text:#E8EEF4; --muted:#8895A7; --faint:#5C6B7E;
  --ember:#FF6A2B; --ember-soft:#FFA666; --cyan:#36C5D9; --green:#46D17F; --warn:#FFC857;
  --disp:'Chakra Petch',system-ui,sans-serif;
  --mono:'IBM Plex Mono',ui-monospace,Menlo,monospace;
  --body:'Inter',system-ui,sans-serif;
  --r:12px;
}
*{box-sizing:border-box}
html,body{margin:0}
body{background:var(--bg);color:var(--text);font-family:var(--body);font-size:14px;line-height:1.5;
  background-image:radial-gradient(circle at 18% -10%,rgba(255,106,43,.10),transparent 42%),
    radial-gradient(circle at 92% 0%,rgba(54,197,217,.08),transparent 40%);
  background-attachment:fixed;}
a{color:var(--cyan)}
.wrap{max-width:1180px;margin:0 auto;padding:0 22px 60px}

/* ---------- HUD header ---------- */
header{position:sticky;top:0;z-index:30;border-bottom:1px solid var(--line);
  background:rgba(11,15,20,.82);backdrop-filter:blur(10px)}
.hud{max-width:1180px;margin:0 auto;padding:14px 22px;display:flex;align-items:center;gap:16px;flex-wrap:wrap}
.brand{display:flex;align-items:center;gap:12px}
.flame{width:30px;height:30px;flex:0 0 auto;filter:drop-shadow(0 0 9px rgba(255,106,43,.55))}
.brand h1{font-family:var(--disp);font-weight:700;font-size:21px;letter-spacing:.14em;margin:0;line-height:1}
.brand .ey{font-family:var(--mono);font-size:10px;letter-spacing:.34em;color:var(--ember);text-transform:uppercase}
.topnav{display:flex;gap:6px;margin-left:18px}
.topnav a{font-family:var(--disp);font-weight:600;font-size:13px;letter-spacing:.04em;padding:6px 13px;border-radius:8px;border:1px solid var(--line);color:var(--muted);text-decoration:none}
.topnav a.on{color:var(--bg);background:var(--cyan);border-color:var(--cyan)}
.chips{margin-left:auto;display:flex;gap:8px;flex-wrap:wrap}
.chip{font-family:var(--mono);font-size:11px;letter-spacing:.05em;color:var(--muted);
  border:1px solid var(--line);border-radius:99px;padding:5px 11px;display:flex;align-items:center;gap:7px;background:var(--panel)}
.dot{width:8px;height:8px;border-radius:50%;background:var(--faint);box-shadow:0 0 0 0 transparent}
.dot.on{background:var(--green);box-shadow:0 0 8px var(--green)}
.dot.off{background:#3a4756}
.dot.run{background:var(--ember);animation:pulse 1.1s infinite}
@keyframes pulse{0%{box-shadow:0 0 0 0 rgba(255,106,43,.6)}70%{box-shadow:0 0 0 7px rgba(255,106,43,0)}100%{box-shadow:0 0 0 0 transparent}}
.tagline{width:100%;color:var(--muted);font-size:13px;margin-top:2px}

/* ---------- pipeline rail (signature) ---------- */
.rail{margin:26px 0 8px}
.rail-h{font-family:var(--mono);font-size:11px;letter-spacing:.28em;color:var(--faint);text-transform:uppercase;margin:0 0 12px}
.stages{display:grid;grid-template-columns:repeat(4,1fr);gap:0;position:relative}
.stage{position:relative;padding:16px 16px 18px;border:1px solid var(--line);background:var(--panel);
  border-right-width:0}
.stage:first-child{border-radius:var(--r) 0 0 var(--r)}
.stage:last-child{border-radius:0 var(--r) var(--r) 0;border-right-width:1px}
.stage .top{display:flex;align-items:center;gap:10px;margin-bottom:9px}
.stage .num{font-family:var(--mono);font-size:11px;color:var(--faint)}
.stage .ico{width:18px;height:18px;color:var(--muted)}
.stage h3{font-family:var(--disp);font-weight:600;font-size:15px;margin:0;letter-spacing:.02em}
.stage p{margin:0;color:var(--muted);font-size:12.5px;min-height:34px}
.stage .foot{display:flex;align-items:center;justify-content:space-between;margin-top:11px}
.pill{font-family:var(--mono);font-size:10.5px;letter-spacing:.08em;text-transform:uppercase;
  padding:3px 9px;border-radius:99px;border:1px solid var(--line);color:var(--faint)}
.metric{font-family:var(--mono);font-size:12px;color:var(--muted)}
.st-done h3,.st-done .ico{color:var(--green)}
.st-done .pill{color:var(--green);border-color:rgba(70,209,127,.4);background:rgba(70,209,127,.08)}
.st-done{box-shadow:inset 0 -2px 0 var(--green)}
.st-active h3,.st-active .ico{color:var(--ember)}
.st-active .pill{color:var(--ember);border-color:rgba(255,106,43,.5);background:rgba(255,106,43,.1)}
.st-active{box-shadow:inset 0 -2px 0 var(--ember)}
.st-partial .pill{color:var(--cyan);border-color:rgba(54,197,217,.4);background:rgba(54,197,217,.08)}
.st-partial{box-shadow:inset 0 -2px 0 var(--cyan)}
.connect{position:absolute;top:50%;right:-7px;width:14px;height:14px;z-index:5;color:var(--line)}
.stage:last-child .connect{display:none}

/* ---------- layout ---------- */
.grid{display:grid;grid-template-columns:1fr 340px;gap:18px;margin-top:18px;align-items:start}
.card{background:var(--panel);border:1px solid var(--line);border-radius:var(--r);overflow:hidden}
.card>.hd{padding:13px 16px;border-bottom:1px solid var(--line-soft);display:flex;align-items:center;gap:10px}
.card>.hd h2{font-family:var(--disp);font-weight:600;font-size:14px;letter-spacing:.06em;margin:0;text-transform:uppercase}
.card>.bd{padding:16px}

/* tabs */
.tabs{display:flex;gap:6px}
.tab{font-family:var(--disp);font-weight:600;letter-spacing:.04em;font-size:13px;padding:8px 15px;border-radius:8px;
  border:1px solid var(--line);background:var(--raised);color:var(--muted);cursor:pointer}
.tab.active{color:var(--bg);background:var(--ember);border-color:var(--ember)}
.tab .sub{font-family:var(--mono);font-weight:400;font-size:10px;display:block;letter-spacing:.04em;opacity:.8}

/* buttons */
.actions{display:flex;flex-wrap:wrap;gap:8px;margin:4px 0 14px}
button{font-family:var(--disp);font-weight:600;font-size:13px;letter-spacing:.03em;color:var(--text);
  background:var(--raised);border:1px solid var(--line);border-radius:8px;padding:9px 14px;cursor:pointer;
  display:inline-flex;align-items:center;gap:7px;transition:border-color .15s,background .15s,transform .05s}
button:hover:not(:disabled){border-color:var(--cyan)}
button:active:not(:disabled){transform:translateY(1px)}
button:disabled{opacity:.38;cursor:not-allowed}
button svg{width:15px;height:15px}
button.primary{background:var(--ember);border-color:var(--ember);color:#1a0d05}
button.primary:hover:not(:disabled){background:var(--ember-soft);border-color:var(--ember-soft)}
.hint{color:var(--faint);font-size:12px;margin-top:4px}

/* video list */
.listhd{display:flex;align-items:center;justify-content:space-between;font-family:var(--mono);font-size:11px;
  color:var(--faint);letter-spacing:.1em;text-transform:uppercase;margin:8px 2px 6px}
.vid{display:flex;align-items:center;gap:11px;padding:9px 11px;border:1px solid var(--line-soft);
  border-radius:9px;margin-bottom:7px;background:var(--raised)}
.vid input{accent-color:var(--ember);width:15px;height:15px}
.vid .nm{font-family:var(--mono);font-size:13px;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.tag{font-family:var(--mono);font-size:10px;letter-spacing:.06em;padding:2px 8px;border-radius:99px}
.tag.ok{color:var(--green);background:rgba(70,209,127,.1);border:1px solid rgba(70,209,127,.3)}
.tag.no{color:var(--faint);border:1px solid var(--line)}
.empty{text-align:center;color:var(--muted);padding:26px 14px;border:1px dashed var(--line);border-radius:10px}
.empty .big{font-family:var(--disp);font-size:15px;color:var(--text);margin-bottom:5px}

/* camera cards */
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:12px;margin-bottom:14px;border-radius:11px}
.cards.over{outline:2px dashed var(--ember);outline-offset:4px}
.card-cam{display:flex;flex-direction:column;border:1px solid var(--line);border-radius:11px;background:var(--raised);overflow:hidden}
.thumb{aspect-ratio:16/10;background:#06090d;display:flex;align-items:center;justify-content:center;overflow:hidden}
.thumb img{width:100%;height:100%;object-fit:cover}
.cam-name{font-family:var(--mono);font-size:12px;padding:8px 10px 4px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.cchips{display:flex;flex-wrap:wrap;gap:4px;padding:0 10px 8px}
.cchip{font-family:var(--mono);font-size:9px;letter-spacing:.03em;padding:2px 6px;border-radius:99px;border:1px solid var(--line);color:var(--faint)}
.cchip.on{color:var(--green);border-color:rgba(70,209,127,.3);background:rgba(70,209,127,.08)}
.cam-acts{margin-top:auto;display:flex;gap:6px;padding:8px 10px;border-top:1px solid var(--line-soft)}
.cam-acts button{flex:1;padding:6px 4px;font-size:11px;margin:0}
button.danger{border-color:rgba(255,106,43,.4);color:var(--ember-soft)}
button.danger:hover:not(:disabled){border-color:var(--ember);background:rgba(255,106,43,.1)}
.card-add{display:flex;flex-direction:column;align-items:center;justify-content:center;min-height:150px;cursor:pointer;color:var(--muted);border:1px dashed var(--line);border-radius:11px;background:var(--raised);gap:4px;text-align:center}
.card-add:hover,.card-add:focus-visible{border-color:var(--ember);color:var(--text)}
.card-add .plus{font-size:30px;font-family:var(--disp);color:var(--ember);line-height:1}
.card-add small{font-family:var(--mono);font-size:10px;color:var(--faint)}
.prog{height:6px;border-radius:4px;background:var(--line);overflow:hidden;margin-top:8px}
.prog>i{display:block;height:100%;width:0;background:var(--cyan);transition:width .2s}

/* calibration */
.calib{margin-top:14px;border:1px solid var(--line);border-radius:10px;background:var(--raised);padding:14px}
.calib-row{display:flex;align-items:center;gap:14px;flex-wrap:wrap}
.calib-row>div:first-child{flex:1;min-width:200px}
.cal-state{font-family:var(--mono);font-size:11px;padding:2px 9px;border-radius:99px;border:1px solid var(--line);color:var(--faint)}
.cal-state.ok{color:var(--green);border-color:rgba(70,209,127,.3);background:rgba(70,209,127,.08)}
.cal-state.bad{color:var(--ember);border-color:rgba(255,106,43,.4);background:rgba(255,106,43,.1)}
.ce{margin-top:12px;padding-top:12px;border-top:1px solid var(--line-soft)}
.ce-head{display:flex;align-items:center;gap:10px;font-family:var(--mono);font-size:11px;color:var(--faint);text-transform:uppercase;letter-spacing:.1em;margin-bottom:10px}
.ce-head select{margin-left:auto;font-family:var(--mono);font-size:12px;background:var(--bg);color:var(--text);border:1px solid var(--line);border-radius:7px;padding:5px 8px}
.ce-g{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-bottom:8px}
.ce-g label{display:flex;flex-direction:column;gap:3px;font-family:var(--mono);font-size:10px;color:var(--muted)}
.ce-g input,.ce-g select{background:var(--bg);color:var(--text);border:1px solid var(--line);border-radius:6px;padding:6px 7px;font-family:var(--mono);font-size:12px;width:100%}
.ce-foot{display:flex;align-items:center;gap:10px;margin:4px 0 6px}
@media (max-width:520px){.ce-g{grid-template-columns:repeat(2,1fr)}}

/* aside */
.steps{counter-reset:s;margin:0;padding:0;list-style:none}
.steps li{counter-increment:s;position:relative;padding:0 0 14px 34px;color:var(--muted);font-size:13px}
.steps li:before{content:counter(s);position:absolute;left:0;top:-1px;width:23px;height:23px;border-radius:7px;
  font-family:var(--mono);font-size:12px;display:flex;align-items:center;justify-content:center;
  color:var(--ember);background:rgba(255,106,43,.1);border:1px solid rgba(255,106,43,.3)}
.steps li b{color:var(--text);font-weight:600}
.steps li:last-child{padding-bottom:0}
.key{display:flex;flex-direction:column;gap:9px}
.key .row{display:flex;align-items:center;gap:10px;font-size:12.5px;color:var(--muted)}
.sw{width:11px;height:11px;border-radius:3px;flex:0 0 auto}
.kv{font-family:var(--mono);font-size:12px;display:flex;justify-content:space-between;gap:10px;
  padding:6px 0;border-bottom:1px solid var(--line-soft)}
.kv:last-child{border-bottom:0}
.kv span{color:var(--faint)} .kv b{color:var(--text);font-weight:500;text-align:right;word-break:break-all}
.aside-sec+.aside-sec{margin-top:18px;padding-top:16px;border-top:1px solid var(--line-soft)}
.aside-h{font-family:var(--mono);font-size:11px;letter-spacing:.2em;text-transform:uppercase;color:var(--faint);margin:0 0 11px}

/* console */
.console{margin-top:18px}
.console .hd{justify-content:space-between}
.jobchip{font-family:var(--mono);font-size:11px;color:var(--muted);display:flex;align-items:center;gap:8px}
.jprogtext{font-family:var(--mono);font-size:11px;color:var(--ember);margin-left:auto;white-space:nowrap}
.jprog{height:5px;background:var(--line);display:none}
.jprog>i{display:block;height:100%;width:0;background:linear-gradient(90deg,var(--ember),var(--ember-soft));transition:width .35s}
#log{font-family:var(--mono);font-size:12px;line-height:1.65;background:#070A0E;color:#bfe6d6;
  padding:14px 16px;height:300px;overflow:auto;white-space:pre-wrap;border-top:1px solid var(--line-soft)}
#log:empty:before{content:'Console idle. Run a stage to stream its log here.';color:var(--faint)}
.err{color:var(--ember-soft)}

/* annotator */
.annot{margin-top:18px}
.annot iframe{width:100%;height:660px;border:0;display:block;background:var(--bg)}
.hidden{display:none!important}

@media (max-width:880px){
  .stages{grid-template-columns:1fr 1fr}
  .stage{border-right-width:1px;border-bottom-width:0}
  .stage:nth-child(1){border-radius:var(--r) 0 0 0} .stage:nth-child(2){border-radius:0 var(--r) 0 0}
  .stage:nth-child(3){border-radius:0;border-bottom-width:0} .stage:nth-child(4){border-radius:0;border-bottom-width:1px}
  .stage:nth-child(-n+2){border-bottom-width:0}
  .connect{display:none}
  .grid{grid-template-columns:1fr}
}
@media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
:focus-visible{outline:2px solid var(--cyan);outline-offset:2px}
</style></head>
<body>
<header><div class="hud">
  <div class="brand">
    <svg class="flame" viewBox="0 0 24 24" fill="none"><path d="M12 2c1 3.5-2 4.8-2 7.5C10 11.4 11 12.5 11 12.5S9 12 8.2 10.4C7 12 6.5 13.6 6.5 15.2 6.5 18.9 9 21.5 12 21.5s5.5-2.6 5.5-6.3c0-3.6-2.4-5.5-3.7-8.2C12.9 5.3 13 3.4 12 2Z" fill="#FF6A2B"/><path d="M12 21.5c1.7 0 3-1.4 3-3.2 0-1.9-1.4-2.8-2-4.3-.7 1-1.6 1.6-1.6 2.9 0 .8.5 1.4.5 1.4s-1-.4-1.4-1.4c-.5.7-.8 1.5-.8 2.4 0 1.8 1.1 2.2 2.3 2.2Z" fill="#FFC857"/></svg>
    <div><h1>FIRETRACK</h1><span class="ey">Ground Control</span></div>
  </div>
  <nav class="topnav"><a href="/" class="on">Control</a><a href="/results">Results</a></nav>
  <div class="chips" id="chips"></div>
  <div class="tagline">Track a drone across synced phone cameras &mdash; segment it with SAM3, then solve its 3D flight path against motion capture.</div>
</div></header>

<div class="wrap">

<section class="rail">
  <p class="rail-h">Mission pipeline</p>
  <div class="stages" id="stages"></div>
</section>

<div class="grid">
  <main class="card">
    <div class="hd"><div class="tabs">
      <div class="tab active" id="tab-dataset" onclick="setMode('dataset')">5-27 dataset<span class="sub">upload files \xc2\xb7 mocap 3D</span></div>
      <div class="tab" id="tab-upload" onclick="setMode('upload')">Upload clips<span class="sub">detect + calibrated 3D</span></div>
    </div></div>
    <div class="bd">

      <div id="mode-dataset">
        <p class="hint" style="margin:0 0 12px">Upload a 5-27 run zip containing camera folders plus the 6D mocap TSV. The app extracts it under <code>/work/dataset_uploads</code> and prepares it for the 5-27 pipeline.</p>
        <div class="actions">
          <button onclick="document.getElementById('dataset-zip').click()" data-keep>@FMT Upload zip</button>
          <button class="danger" onclick="clearDataset()" data-keep>Clear dataset</button>
        </div>
        <input type="file" id="dataset-zip" accept=".zip,application/zip" class="hidden">
        <div id="ds-progress"></div>
        <div class="actions">
          <button onclick="run('format')" data-st="format">@FMT Format</button>
          <button onclick="annotate('dataset')" data-keep>@CLK Annotate</button>
          <button onclick="run('detect')" data-st="detect">@DET Detect</button>
          <button onclick="run('triangulate')" data-st="triangulate">@TRI Triangulate</button>
          <button class="primary" onclick="run('run-all')" data-st="run-all">@RUN Run all</button>
        </div>
        <p class="hint">Leave all clips unchecked to process every formatted camera.</p>
        <div class="listhd"><span>Camera clips</span><label style="text-transform:none;letter-spacing:0;cursor:pointer"><input type="checkbox" id="ds-all" onchange="toggleAll('dataset')"> select all</label></div>
        <div id="ds-list"></div>
      </div>

      <div id="mode-upload" class="hidden">
        <p class="hint" style="margin:0 0 12px">Add at least 2 cameras &mdash; click a card (or drop a video on it) to add a clip, detect the drone, calibrate each camera, then triangulate.</p>
        <div class="cards" id="cards"></div>
        <input type="file" id="files" accept="video/*" multiple class="hidden">
        <div id="up-progress"></div>
        <div class="calib">
          <div class="calib-row">
            <div><b>3D calibration</b> <span id="cal-state" class="cal-state">not loaded</span>
              <div class="hint">Upload a JSON with each camera's <code>K</code>, <code>R</code>, <code>t</code> (world&rarr;camera) and <code>start_epoch_s</code> to unlock triangulation.</div></div>
            <button onclick="document.getElementById('calfile').click()" data-keep>Load JSON</button>
            <input type="file" id="calfile" accept=".json,application/json" class="hidden">
          </div>
          <div class="ce">
            <div class="ce-head"><span>Or enter a camera</span>
              <select id="ce-clip" data-keep></select><span id="ce-mark" class="cal-state"></span></div>
            <div class="ce-g">
              <label>fx<input id="ce-fx" type="number" step="any"></label>
              <label>fy<input id="ce-fy" type="number" step="any"></label>
              <label>cx<input id="ce-cx" type="number" step="any"></label>
              <label>cy<input id="ce-cy" type="number" step="any"></label>
              <label>res W<input id="ce-rw" type="number" step="any" placeholder="opt"></label>
              <label>res H<input id="ce-rh" type="number" step="any" placeholder="opt"></label>
            </div>
            <div class="ce-g">
              <label>pitch&deg;<input id="ce-pitch" type="number" step="any"></label>
              <label>yaw&deg;<input id="ce-yaw" type="number" step="any"></label>
              <label>roll&deg;<input id="ce-roll" type="number" step="any"></label>
              <label>angle order<select id="ce-order"><option value="ZYX">yaw\xc2\xb7pitch\xc2\xb7roll (ZYX)</option><option value="XYZ">roll\xc2\xb7pitch\xc2\xb7yaw (XYZ)</option></select></label>
            </div>
            <div class="ce-g">
              <label>cam pos x<input id="ce-px" type="number" step="any"></label>
              <label>cam pos y<input id="ce-py" type="number" step="any"></label>
              <label>cam pos z<input id="ce-pz" type="number" step="any"></label>
              <label>start_epoch_s<input id="ce-epoch" type="number" step="any"></label>
            </div>
            <div class="ce-g">
              <label style="grid-column:span 2">orientation is<select id="ce-conv"><option value="c2w">camera&rarr;world (pose)</option><option value="w2c">world&rarr;camera (solvePnP)</option></select></label>
              <label style="grid-column:span 2">distortion (optional)<input id="ce-dist" type="text" placeholder="k1,k2,p1,p2,k3"></label>
            </div>
            <div class="ce-foot"><button id="ce-save" class="primary" data-keep onclick="saveCamera()">Save camera</button>
              <span id="ce-msg" class="hint"></span></div>
            <div class="hint">Orientation = pitch/yaw/roll in degrees (roll=X, pitch=Y, yaw=Z); pick the order your tool uses. Camera position = where the camera sits in the world. K from fx/fy/cx/cy.</div>
          </div>
        </div>
        <div class="actions" style="margin-top:14px">
          <button onclick="annotate('upload')" data-keep>@CLK Annotate</button>
          <button class="primary" onclick="run('detect')" data-st="detect">@DET Run 2D detection</button>
          <button id="btn-up-tri" onclick="run('triangulate')" data-st="triangulate">@TRI Triangulate (3D)</button>
        </div>
      </div>

    </div>
  </main>

  <aside class="card"><div class="bd">
    <div class="aside-sec">
      <p class="aside-h">Getting started</p>
      <ol class="steps">
        <li><b>Pick a source.</b> Upload a 5-27 run for mocap-backed 3D, or upload arbitrary clips for calibrated 3D.</li>
        <li><b>Annotate.</b> Click the drone once per clip so SAM3 knows what to follow. Optional &mdash; skip it to use the text prompt.</li>
        <li><b>Detect.</b> SAM3 tracks the drone frame-by-frame and saves 2D centroid tracks.</li>
        <li><b>Triangulate.</b> 5-27 mode fuses tracks against mocap; clip mode uses your supplied camera poses.</li>
      </ol>
    </div>
    <div class="aside-sec">
      <p class="aside-h">Status key</p>
      <div class="key">
        <div class="row"><span class="sw" style="background:var(--faint)"></span> Idle &mdash; not run yet</div>
        <div class="row"><span class="sw" style="background:var(--ember)"></span> Running &mdash; in progress now</div>
        <div class="row"><span class="sw" style="background:var(--cyan)"></span> Partial &mdash; some clips done</div>
        <div class="row"><span class="sw" style="background:var(--green)"></span> Complete &mdash; outputs written</div>
      </div>
    </div>
    <div class="aside-sec">
      <p class="aside-h">Outputs</p>
      <div class="kv"><span>formatted</span><b>/work/formatted</b></div>
      <div class="kv"><span>5-27 uploads</span><b>/work/dataset_uploads</b></div>
      <div class="kv"><span>2D tracks</span><b>/work/detections</b></div>
      <div class="kv"><span>3D trajectory</span><b>/work/triangulation</b></div>
      <div class="kv"><span>clicks</span><b id="kv-clicks">/work/clicks.json</b></div>
    </div>
  </div></aside>
</div>

<section class="card console">
  <div class="hd"><h2>Console</h2><span class="jobchip" id="jobchip"></span><span class="jprogtext" id="jprogtext"></span></div>
  <div class="jprog" id="jprog"><i></i></div>
  <div id="log"></div>
</section>

<section class="card annot hidden" id="annot-panel">
  <div class="hd"><h2>Annotator</h2><button onclick="closeAnnot()" data-keep style="margin-left:auto">Close</button></div>
  <iframe id="annot" title="Click annotator"></iframe>
</section>

</div>

<script>
const ICONS={
 '@FMT':'M3 7h18M3 12h18M3 17h10','@CLK':'M12 2v4M12 18v4M2 12h4M18 12h4M7 7l3 3M14 14l3 3',
 '@DET':'M12 5C6 5 2.7 12 2.7 12S6 19 12 19s9.3-7 9.3-7S18 5 12 5Z','@TRI':'M12 3l9 16H3z',
 '@RUN':'M5 4l14 8-14 8z'};
const STAGES=[
 {id:'format',icon:'@FMT',name:'Format',desc:'Straighten and standardize the raw phone clips.'},
 {id:'clicks',icon:'@CLK',name:'Annotate',desc:'Click the drone once per clip to lock onto it.'},
 {id:'detect',icon:'@DET',name:'Detect',desc:'Track the drone frame-by-frame in 2D with SAM3.'},
 {id:'triangulate',icon:'@TRI',name:'Triangulate',desc:'Fuse the camera tracks into one 3D flight path.'},
];
function svg(cls,d){return `<svg class="${cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="${d}"/></svg>`;}
let mode='dataset',since=0,polling=false,lastJob='';

function setMode(m){mode=m;
 for(const k of ['dataset','upload']){
   document.getElementById('tab-'+k).classList.toggle('active',k===m);
   document.getElementById('mode-'+k).classList.toggle('hidden',k!==m);}}
function selected(which){return [...document.querySelectorAll('.cb-'+which+':checked')].map(c=>c.value);}
function toggleAll(which){const on=document.getElementById((which==='dataset'?'ds':'up')+'-all').checked;
 document.querySelectorAll('.cb-'+which).forEach(c=>c.checked=on);}

function chip(label,on,text){return `<div class="chip"><span class="dot ${on?'on':'off'}"></span>${label}${text?' \\u00b7 '+text:''}</div>`;}
function renderChips(s){const e=s.env||{};const j=s.job;
 let run=j.status==='running'?`<div class="chip"><span class="dot run"></span>${(j.name||'job').toUpperCase()}</div>`:'';
 document.getElementById('chips').innerHTML=run+
  chip('GPU',e.gpu)+chip('WEIGHTS',e.weights_cached,e.offline?'offline':'')+
  chip('SAM3',e.weights_cached?true:false);}

function stageState(s,id){
 const j=s.job,parts=(j.name||'').split(':'),jstage=parts[1]||parts[0];
 if(j.status==='running'){ if(jstage===id) return 'active';
   if(jstage==='run-all'&&id!=='clicks') return 'active'; }
 if(id==='format') return (s.outputs.formatted&&s.dataset.length)?'done':'idle';
 if(id==='clicks'){const c=mode==='upload'?s.uploads_clicks:s.clicks; if(c&&c.clicked>0) return c.pending?'partial':'done'; return 'idle';}
 if(id==='detect'){const all=mode==='upload'?s.uploads:s.dataset;const tot=all.length;
   const done=all.filter(v=>v.has_detection).length;
   if(!tot)return 'idle'; return done>=tot?'done':(done?'partial':'idle');}
 if(id==='triangulate') return (mode==='upload'?s.outputs.uploads_triangulation:s.outputs.triangulation)?'done':'idle';
 return 'idle';}
function stageMetric(s,id){
 if(id==='format') return s.dataset.length?s.dataset.length+' clips':'';
 if(id==='clicks'){const c=mode==='upload'?s.uploads_clicks:s.clicks; return c?c.clicked+'/'+c.total:'';}
 if(id==='detect'){const all=mode==='upload'?s.uploads:s.dataset;
   return all.length?all.filter(v=>v.has_detection).length+'/'+all.length:'';}
 if(id==='triangulate'){ if(mode==='upload')return s.outputs.uploads_triangulation?'solved':''; return s.outputs.triangulation?'solved':''; }
 return '';}
const LABELS={idle:'Idle',active:'Running',partial:'Partial',done:'Complete'};
function renderStages(s){
 document.getElementById('stages').innerHTML=STAGES.map((st,i)=>{
  const state=stageState(s,st.id),m=stageMetric(s,st.id);
  return `<div class="stage st-${state}">
    <div class="top"><span class="num">0${i+1}</span>${svg('ico',ICONS[st.icon])}<h3>${st.name}</h3></div>
    <p>${st.desc}</p>
    <div class="foot"><span class="pill">${LABELS[state]}</span><span class="metric">${m}</span></div>
    ${svg('connect','M9 6l6 6-6 6')}</div>`;}).join('');}

function vidRow(which,v){return `<div class="vid"><input type="checkbox" class="cb-${which}" value="${v.label}">
  <span class="nm">${v.label}</span><span class="tag ${v.has_detection?'ok':'no'}">${v.has_detection?'detected':'pending'}</span></div>`;}
function renderList(id,which,items,emptyTitle,emptyBody){
 const el=document.getElementById(id);
 el.innerHTML=items.length?items.map(v=>vidRow(which,v)).join('')
  :`<div class="empty"><div class="big">${emptyTitle}</div>${emptyBody}</div>`;}
let cardsSig=null;
function cchip(on,label){return `<span class="cchip ${on?'on':''}">${label}${on?' \\u2713':''}</span>`;}
function camCard(u,cal){return `<div class="card-cam">
  <div class="thumb"><img src="/api/upload-frame?label=${encodeURIComponent(u.label)}&frame=0" alt="" onerror="this.style.display='none'"></div>
  <div class="cam-name" title="${u.label}">${u.label}</div>
  <div class="cchips">${cchip(true,'uploaded')}${cchip(u.has_detection,'detected')}${cchip(cal,'calibrated')}</div>
  <div class="cam-acts"><button onclick="calibrateCard('${u.label}')">Calibrate</button>
    <button class="danger" onclick="removeCamera('${u.label}')">Remove</button></div></div>`;}
function addCard(label,sub){return `<div class="card-add" tabindex="0" onclick="document.getElementById('files').click()" onkeydown="if(event.key==='Enter')document.getElementById('files').click()"><div class="plus">+</div><div>${label}</div>${sub?`<small>${sub}</small>`:''}</div>`;}
function renderCards(uploads,calCams){
 const set=new Set(calCams||[]);
 const sig=uploads.map(u=>u.label+(u.has_detection?'D':'')+(set.has(u.label)?'C':'')).join('|');
 if(sig===cardsSig)return; cardsSig=sig;
 let html=uploads.map(u=>camCard(u,set.has(u.label))).join('');
 const need=Math.max(0,2-uploads.length);
 for(let i=0;i<need;i++)html+=addCard('Camera '+(uploads.length+i+1),'click to add');
 html+=addCard('Add camera','');
 document.getElementById('cards').innerHTML=html;
}
function calibrateCard(label){const sel=document.getElementById('ce-clip');sel.value=label;prefillCamera();
 document.querySelector('.calib').scrollIntoView({behavior:'smooth',block:'center'});}
async function removeCamera(label){
 if(!confirm('Remove camera "'+label+'"?\\nThis deletes its video, detection outputs, and calibration.'))return;
 await fetch('/api/upload/remove',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({label})});
 cardsSig=null;refresh();
}

async function refresh(){
 let s; try{ s=await(await fetch('/api/status')).json(); }catch(e){ return; }
 renderChips(s); renderStages(s);
 renderList('ds-list','dataset',s.dataset,'No formatted clips yet','Upload a 5-27 run zip, then run Format.');
 renderCards(s.uploads,(s.calibration||{}).cameras||[]);
 const j=s.job,running=j.status==='running';
 document.getElementById('jobchip').innerHTML=j.name?
   `<span class="dot ${running?'run':(j.status==='failed'?'off':'on')}"></span>${j.name} \\u2014 ${j.status}${j.error?' <span class="err">('+j.error+')</span>':''}`:'';
 document.querySelectorAll('main button,.console button').forEach(b=>{if(!b.dataset.keep)b.disabled=running;});
 // calibration state + 3D-button gating (upload mode)
 const cal=s.calibration||{present:false,n_cameras:0};
 const cs=document.getElementById('cal-state');
 if(cs){cs.className='cal-state'+(cal.present?' ok':(cal.error?' bad':''));
   cs.textContent=cal.present?(cal.n_cameras+' cameras'):(cal.error?'invalid file':'not loaded');}
 syncClips(s.uploads,cal.cameras);
 const detUp=s.uploads.filter(v=>v.has_detection).length;
 const tri=document.getElementById('btn-up-tri');
 if(tri)tri.disabled=running||!cal.present||detUp<2;
 updateProgress(j);
 if(running&&!polling)pollLog();
}
function updateProgress(j){
 const bar=document.getElementById('jprog'),txt=document.getElementById('jprogtext'),p=j&&j.progress;
 if(j&&j.status==='running'&&p&&p.total){
   const pct=Math.min(100,Math.round(100*(p.frame||0)/p.total));
   bar.style.display='block';bar.firstElementChild.style.width=pct+'%';
   txt.textContent=`${p.label||''} ${p.frame||0}/${p.total} (${pct}%)`+(p.n_videos>1?` \\u00b7 clip ${p.video}/${p.n_videos}`:'');
 }else{bar.style.display='none';bar.firstElementChild.style.width='0';txt.textContent='';}
}
function syncClips(uploads,calCams){
 const sel=document.getElementById('ce-clip');if(!sel)return;
 const want=uploads.map(u=>u.label),have=[...sel.options].map(o=>o.value);
 if(want.join('|')!==have.join('|')){const cur=sel.value;
   sel.innerHTML=want.length?want.map(l=>`<option value="${l}">${l}</option>`).join(''):'<option value="">upload a clip first</option>';
   if(want.includes(cur))sel.value=cur;}
 const set=new Set(calCams||[]),mk=document.getElementById('ce-mark');
 mk.className='cal-state'+(set.has(sel.value)?' ok':'');mk.textContent=set.has(sel.value)?'set':(sel.value?'not set':'');
}
const CE=['ce-fx','ce-fy','ce-cx','ce-cy','ce-rw','ce-rh','ce-pitch','ce-yaw','ce-roll','ce-px','ce-py','ce-pz','ce-epoch','ce-dist'];
async function prefillCamera(){
 const g=id=>document.getElementById(id),v=g('ce-clip').value;CE.forEach(i=>g(i).value='');
 document.getElementById('ce-msg').textContent='';if(!v)return;
 const store=await (await fetch('/api/calibration')).json();
 const c=(store.cameras||[]).find(c=>c.video===v);if(!c)return;
 if(c.K){g('ce-fx').value=c.K[0][0];g('ce-fy').value=c.K[1][1];g('ce-cx').value=c.K[0][2];g('ce-cy').value=c.K[1][2];}
 if(c.resolution){g('ce-rw').value=c.resolution[0];g('ce-rh').value=c.resolution[1];}
 if(c.euler){g('ce-pitch').value=c.euler.pitch;g('ce-yaw').value=c.euler.yaw;g('ce-roll').value=c.euler.roll;}
 if(c.euler_order)g('ce-order').value=c.euler_order;
 if(c.position){['ce-px','ce-py','ce-pz'].forEach((id,i)=>g(id).value=c.position[i]);}
 if(c.pose_convention)g('ce-conv').value=c.pose_convention;
 if(c.start_epoch_s!=null)g('ce-epoch').value=c.start_epoch_s;
 if(c.dist)g('ce-dist').value=c.dist.join(',');
}
async function saveCamera(){
 const g=id=>document.getElementById(id).value.trim(),num=id=>parseFloat(g(id));
 const v=g('ce-clip'),msg=document.getElementById('ce-msg');msg.style.color='';
 if(!v){msg.textContent='Pick a clip first.';return;}
 const req=['ce-fx','ce-fy','ce-cx','ce-cy','ce-pitch','ce-yaw','ce-roll','ce-px','ce-py','ce-pz','ce-epoch'];
 if(req.some(id=>g(id)===''||isNaN(num(id)))){msg.textContent='Fill fx/fy/cx/cy, pitch/yaw/roll, camera position, and start_epoch_s.';return;}
 const body={video:v,K:[[num('ce-fx'),0,num('ce-cx')],[0,num('ce-fy'),num('ce-cy')],[0,0,1]],
   euler:{pitch:num('ce-pitch'),yaw:num('ce-yaw'),roll:num('ce-roll')},euler_order:g('ce-order'),
   position:[num('ce-px'),num('ce-py'),num('ce-pz')],pose_convention:g('ce-conv'),
   start_epoch_s:num('ce-epoch')};
 if(g('ce-rw')&&g('ce-rh'))body.resolution=[num('ce-rw'),num('ce-rh')];
 if(g('ce-dist'))body.dist=g('ce-dist').split(',').map(parseFloat).filter(x=>!isNaN(x));
 const r=await fetch('/api/calibration/camera',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
 const d=await r.json().catch(()=>({}));
 if(!r.ok){msg.style.color='var(--ember)';msg.textContent='Rejected: '+(d.error||'unknown');}
 else{msg.style.color='var(--green)';msg.textContent='Saved \\u2014 '+d.n_cameras+' camera(s) calibrated.';}
 refresh();
}
document.getElementById('ce-clip').addEventListener('change',prefillCamera);
async function run(stage){
 const r=await fetch('/api/run',{method:'POST',headers:{'Content-Type':'application/json'},
   body:JSON.stringify({stage,source:mode,only:selected(mode)})});
 if(r.status===409){flash('A job is already running.');return;}
 if(!r.ok){const d=await r.json().catch(()=>({}));flash(d.error||'Could not start.');return;}
 since=0;document.getElementById('log').textContent='';pollLog();refresh();
}
async function pollLog(){polling=true;
 let r; try{ r=await(await fetch('/api/log?since='+since)).json(); }catch(e){ polling=false; return; }
 if(r.lines&&r.lines.length){since=r.next;const l=document.getElementById('log');
   l.textContent+=r.lines.join('\\n')+'\\n';l.scrollTop=l.scrollHeight;}
 updateProgress({status:r.status,progress:r.progress});
 if(r.status==='running'){setTimeout(pollLog,1000);}else{polling=false;refresh();}
}
function flash(msg){const l=document.getElementById('log');l.textContent+='! '+msg+'\\n';l.scrollTop=l.scrollHeight;}

/* 5-27 dataset uploads with progress */
function uploadDatasetZip(file){return new Promise((res)=>{
 const id='zip'+Math.abs([...file.name].reduce((a,c)=>a*31+c.charCodeAt(0)|0,13));
 const box=document.getElementById('ds-progress');
 box.insertAdjacentHTML('beforeend',`<div style="margin:8px 0"><div style="font-family:var(--mono);font-size:12px;color:var(--muted)">${file.name}</div><div class="prog"><i id="${id}"></i></div></div>`);
 const x=new XMLHttpRequest();x.open('POST','/api/dataset-upload-zip?name='+encodeURIComponent(file.name));
 x.upload.onprogress=e=>{if(e.lengthComputable)document.getElementById(id).style.width=(100*e.loaded/e.total)+'%';};
 x.onload=()=>{const bar=document.getElementById(id);bar.style.width='100%';bar.style.background=x.status<300?'var(--green)':'var(--ember)';
   if(x.status<300){let d={};try{d=JSON.parse(x.responseText||'{}')}catch(_){};flash('Zip extracted: '+(d.extracted||0)+' files. Run Format next.');}
   else flash('Zip upload failed: '+file.name);res();};
 x.onerror=()=>{flash('Zip upload failed: '+file.name);res();};x.send(file);});}
async function clearDataset(){
 if(!confirm('Clear uploaded 5-27 files and generated dataset outputs?'))return;
 await fetch('/api/dataset/clear',{method:'POST'});
 document.getElementById('ds-progress').textContent='';
 refresh();
}
document.getElementById('dataset-zip').addEventListener('change',async e=>{
 const f=e.target.files[0]; if(!f)return;
 await uploadDatasetZip(f); e.target.value=''; refresh();
});

/* uploads with progress */
function uploadOne(file){return new Promise((res)=>{
 const id='p'+Math.abs([...file.name].reduce((a,c)=>a*31+c.charCodeAt(0)|0,7));
 const box=document.getElementById('up-progress');
 box.insertAdjacentHTML('beforeend',`<div style="margin:8px 0"><div style="font-family:var(--mono);font-size:12px;color:var(--muted)">${file.name}</div><div class="prog"><i id="${id}"></i></div></div>`);
 const x=new XMLHttpRequest();x.open('POST','/api/upload?name='+encodeURIComponent(file.name));
 x.upload.onprogress=e=>{if(e.lengthComputable)document.getElementById(id).style.width=(100*e.loaded/e.total)+'%';};
 x.onload=()=>{document.getElementById(id).style.width='100%';document.getElementById(id).style.background='var(--green)';res();};
 x.onerror=()=>{flash('Upload failed: '+file.name);res();};x.send(file);});}
async function handleFiles(files){for(const f of files)await uploadOne(f);refresh();}
const drop=document.getElementById('cards');
['dragenter','dragover'].forEach(ev=>drop.addEventListener(ev,e=>{e.preventDefault();drop.classList.add('over');}));
['dragleave','drop'].forEach(ev=>drop.addEventListener(ev,e=>{e.preventDefault();drop.classList.remove('over');}));
drop.addEventListener('drop',e=>handleFiles(e.dataTransfer.files));
document.getElementById('files').addEventListener('change',e=>handleFiles(e.target.files));

/* calibration upload */
document.getElementById('calfile').addEventListener('change',async e=>{
 const f=e.target.files[0]; if(!f)return;
 let text; try{ text=await f.text(); JSON.parse(text); }catch(_){ flash('Calibration is not valid JSON.'); return; }
 const r=await fetch('/api/calibration',{method:'POST',headers:{'Content-Type':'application/json'},body:text});
 const d=await r.json().catch(()=>({}));
 if(!r.ok){flash('Calibration rejected: '+(d.error||'unknown'));}
 else{flash('Calibration loaded: '+d.n_cameras+' cameras.');}
 e.target.value=''; refresh();
});

async function annotate(source){
 await fetch('/api/clicks/select',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({source})});
 document.getElementById('annot-panel').classList.remove('hidden');
 document.getElementById('annot').src='/clicks?t='+Date.now();
 document.getElementById('annot-panel').scrollIntoView({behavior:'smooth',block:'start'});
}
function closeAnnot(){document.getElementById('annot-panel').classList.add('hidden');
 document.getElementById('annot').src='about:blank';refresh();}

/* render @ICON tokens in button labels into svg */
document.querySelectorAll('button[data-st],button[data-keep]').forEach(b=>{
 b.innerHTML=b.innerHTML.replace(/@\\w+/,m=>svg('',ICONS[m]||'M5 4l14 8-14 8z'));});
refresh();setInterval(refresh,2500);
</script>
</body></html>"""
