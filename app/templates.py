# Three pages sharing CSS, top bar and data plumbing: "/" telemetry, "/flow" power-flow charts,
# "/control" zero-feed-in controller + battery-plan parameters + read-only env.
# Raw strings on purpose: the embedded JS uses backslash escapes ('\n') that must
# reach the browser unchanged. Design: "GridPulse Telemetry" (Stitch mockup).

_CSS = r"""
  :root{
    color-scheme:dark;
    --bg:#0f131c; --panel:#181c24; --tile:#1c2028; --well:#0a0e16; --hi:#262a33; --hi2:#31353e;
    --line:#252b36; --line-strong:#3e484f;
    --text:#dfe2ee; --muted:#bdc8d1; --dim:#87929a;
    --pv:#38bdf8; --pv-t:#8ed5ff; --inv:#4edea3; --bat:#ffc174; --bat-c:#f59e0b; --load:#ffb4ab; --load-c:#f43f5e; --grid:#94a3b8;
    --ok:#4edea3; --warn:#ffc174; --bad:#ffb4ab;
    --sans:"Geist",ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
    --head:"Space Grotesk",var(--sans);
    --mono:"JetBrains Mono",ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
  }
  *{box-sizing:border-box}
  html{background:var(--bg)}
  body{margin:0;background:var(--bg);color:var(--text);font:13px/18px var(--sans);-webkit-font-smoothing:antialiased}
  h1,h2,h3,p{margin:0}
  button,input{font:inherit;color:inherit}
  svg{display:block}
  a{color:inherit;text-decoration:none}
  .lbl{font:500 10px/14px var(--mono);letter-spacing:.04em;text-transform:uppercase;color:var(--muted)}
  .unit{font:400 11px/14px var(--mono);color:var(--dim)}
  .val{font:500 14px/18px var(--mono);font-variant-numeric:tabular-nums}

  /* ---- top bar ---- */
  .topbar{position:sticky;top:0;z-index:5;display:flex;align-items:center;justify-content:space-between;gap:12px 20px;flex-wrap:wrap;
    padding:8px 16px;background:var(--panel);border-bottom:1px solid var(--line)}
  .topbar .grp{display:flex;align-items:center;gap:16px;flex-wrap:wrap}
  .nav{display:flex;gap:4px;padding:3px;background:var(--well);border-radius:6px}
  .nav a{padding:6px 12px;border-radius:4px;font:500 12px/16px var(--sans);color:var(--muted);transition:background .15s,color .15s}
  .nav a:hover{color:var(--text)}
  .nav a[aria-current=page]{background:var(--hi2);color:var(--text)}
  .pill{display:inline-flex;align-items:center;gap:6px;padding:4px 8px;border-radius:4px;background:var(--well);font:600 10px/14px var(--mono);letter-spacing:.04em;text-transform:uppercase}
  .dot{width:8px;height:8px;border-radius:50%;background:currentColor;flex:none}
  .pill.ok{color:var(--ok)} .pill.warn{color:var(--warn)} .pill.bad{color:var(--bad)}
  .pill.ok .dot{animation:pulse 2s ease-in-out infinite}
  @keyframes pulse{50%{opacity:.35}}
  .kv{display:flex;flex-direction:column;gap:3px}
  .kv.r{align-items:flex-end}
  .kv .v{display:flex;align-items:baseline;gap:4px}
  .sep{width:1px;align-self:stretch;background:var(--hi2)}
  .hide-sm{display:none!important}
  @media(min-width:1000px){.hide-sm{display:flex!important}}

  /* ---- layout ---- */
  main{padding:16px;display:grid;gap:16px;max-width:1800px;margin:0 auto}
  .cols{display:grid;gap:16px;grid-template-columns:minmax(0,1fr)}
  @media(min-width:1100px){.cols{grid-template-columns:5fr 7fr}}
  .card{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:12px;display:grid;gap:12px;align-content:start;min-width:0}
  .card.sub{background:var(--tile)}
  .head{display:flex;align-items:center;justify-content:space-between;gap:8px;flex-wrap:wrap}
  .head .t{display:flex;align-items:center;gap:8px;min-width:0}
  .head h2{font:600 16px/24px var(--head);letter-spacing:-.01em}
  .head.lg h2{font-size:20px;line-height:28px}
  .head p{font:400 10px/14px var(--mono);color:var(--muted);letter-spacing:.02em}
  .ico{width:22px;height:22px;flex:none}
  .tag{padding:2px 8px;border-radius:4px;font:500 10px/14px var(--mono);letter-spacing:.04em;text-transform:uppercase;background:var(--hi2);color:var(--muted);white-space:nowrap}
  .tag.ok{background:rgba(78,222,163,.15);color:var(--ok)}
  .tag.info{background:rgba(142,213,255,.14);color:var(--pv-t)}
  .tag.warn{background:rgba(255,193,116,.16);color:var(--warn)}
  .tag.bad{background:rgba(255,180,171,.14);color:var(--bad)}
  :focus-visible{outline:2px solid var(--pv-t);outline-offset:2px}

  /* ---- Nulleinspeisung ---- */
  .trio{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px}
  @media(max-width:520px){.trio{grid-template-columns:1fr}}
  .stat{position:relative;background:var(--tile);border-radius:6px;padding:8px 8px 8px 12px;display:grid;gap:4px;align-content:space-between;overflow:hidden}
  .stat::before{content:"";position:absolute;left:0;top:0;bottom:0;width:3px;background:var(--c,var(--dim))}
  .stat .big{font:600 24px/28px var(--mono);letter-spacing:-.03em;font-variant-numeric:tabular-nums;color:var(--c2,var(--text))}
  .stat .sub{font:500 10px/14px var(--mono);color:var(--muted);letter-spacing:.02em}
  .well{background:var(--well);border-radius:6px;padding:8px;display:grid;gap:2px}
  .opt{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:6px 4px;border-radius:4px;cursor:pointer;user-select:none}
  .opt:hover{background:var(--tile)}
  .opt + .opt{border-top:1px solid rgba(49,53,62,.5)}
  .opt .l{display:flex;align-items:center;gap:10px;min-width:0}
  .opt .n{display:grid}
  .opt .n b{font-weight:500}
  .opt .n small{font:400 10px/14px var(--mono);color:var(--muted)}
  input[type=checkbox]{appearance:none;width:16px;height:16px;flex:none;margin:0;border:1px solid var(--line-strong);border-radius:4px;background:#0f172a;display:grid;place-items:center;cursor:pointer}
  input[type=checkbox]:checked{background:var(--pv);border-color:var(--pv)}
  input[type=checkbox]:checked::after{content:"";width:8px;height:4px;border-left:2px solid #00212f;border-bottom:2px solid #00212f;transform:rotate(-45deg) translate(1px,-1px)}
  input[type=checkbox]#ctl-dry:checked{background:var(--bat-c);border-color:var(--bat-c)}
  .note{display:flex;gap:10px;align-items:flex-start;background:var(--tile);border-radius:6px;padding:8px}
  .note b{font-weight:500}
  .note small{display:block;font:400 10px/14px var(--mono);color:var(--muted);margin-top:2px}
  .note svg{width:20px;height:20px;flex:none;color:var(--bat);margin-top:1px}
  .status{display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap;background:var(--hi2);border-radius:6px;padding:8px}
  .status .s{display:flex;align-items:center;gap:8px}
  .status .txt{font:500 13px/18px var(--mono);color:var(--ok);text-align:right;min-width:0;overflow-wrap:anywhere;flex:1}
  .status .txt.warn{color:var(--warn)} .status .txt.bad{color:var(--bad)}
  details.diag{background:var(--tile);border-radius:6px}
  details.diag summary{cursor:pointer;padding:6px 8px;font:500 10px/14px var(--mono);letter-spacing:.04em;list-style:none;display:flex;align-items:center;justify-content:space-between}
  details.diag summary::-webkit-details-marker{display:none}
  details.diag summary::after{content:"▾";color:var(--muted);transition:transform .15s}
  details.diag[open] summary::after{transform:rotate(180deg)}
  details.diag pre{margin:0;padding:8px;background:var(--well);border-radius:0 0 6px 6px;font:400 10px/16px var(--mono);color:var(--muted);white-space:pre-wrap;overflow-wrap:anywhere;max-height:220px;overflow:auto}

  /* ---- Live telemetry ---- */
  .chips{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:4px}
  @media(min-width:640px){.chips{grid-template-columns:repeat(5,minmax(0,1fr))}}
  .chip{background:var(--tile);border-radius:6px;padding:8px;display:grid;gap:8px}
  .chip .r{display:flex;justify-content:space-between;gap:4px;align-items:center;color:var(--c)}
  .chip .r span:first-child{display:flex;align-items:center;gap:4px;font:500 10px/14px var(--mono);text-transform:uppercase;letter-spacing:.04em}
  .chip .r i{width:6px;height:6px;border-radius:50%;background:var(--c)}
  .chip .r .val{font-size:11px}
  .bar{height:6px;border-radius:3px;background:var(--hi2);overflow:hidden}
  .bar>div{height:100%;border-radius:3px;background:var(--c);transition:width .4s}
  .soc{background:var(--tile);border-radius:6px;padding:8px;display:grid;gap:6px}
  .soc .top{display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap}
  .soc .top .l{display:flex;align-items:center;gap:8px;font-weight:500}
  .soc .top .l svg{width:20px;height:20px;color:var(--bat)}
  .track{position:relative;height:12px;border-radius:6px;background:var(--well);overflow:hidden}
  .track .fill{height:100%;border-radius:6px;background:linear-gradient(90deg,var(--bat-c),var(--bat) 55%,var(--ok));transition:width .5s}
  .track .mk{position:absolute;top:0;bottom:0;width:2px;transform:translateX(-1px)}
  .scale{position:relative;height:29px;font:500 10px/14px var(--mono)}
  .scale span{position:absolute;white-space:nowrap}
  .tables{display:grid;gap:8px;grid-template-columns:minmax(0,1fr)}
  @media(min-width:760px){.tables{grid-template-columns:1fr 1fr}}
  .tbl{background:var(--tile);border-radius:6px;padding:4px;align-content:start}
  .tbl .cap{padding:4px 8px;font:600 10px/14px var(--mono);letter-spacing:.04em;text-transform:uppercase}
  .row{display:flex;align-items:center;justify-content:space-between;gap:8px;padding:6px 8px;border-radius:4px;min-height:32px}
  .row:hover{background:var(--hi)}
  .row>span:first-child{color:var(--muted)}
  .row .vv{display:flex;align-items:baseline;gap:4px;white-space:nowrap}
  .row.on{background:rgba(56,189,248,.1)} .row.on>span:first-child{color:var(--pv-t)}
  .foot{display:flex;justify-content:space-between;gap:8px;flex-wrap:wrap;background:var(--well);border-radius:6px;padding:8px;color:var(--muted);font:500 10px/14px var(--mono)}
  .foot b{color:var(--text);font-weight:600}

  /* ---- charts (live page) ---- */
  .flow{display:grid;gap:12px;grid-template-columns:minmax(0,1fr)}
  @media(min-width:1100px){.flow{grid-template-columns:2fr 1fr}}
  .flow .sub{gap:8px}
  .stack{display:grid;gap:12px;align-content:start;min-width:0}
  main.narrow{max-width:1100px}
  .prev{display:grid;gap:12px;grid-template-columns:minmax(0,1fr);align-items:start}
  @media(min-width:1100px){.prev{grid-template-columns:repeat(3,minmax(0,1fr))}}
  .ranges{display:flex;gap:2px;padding:3px;background:var(--well);border-radius:6px}
  .ranges button{border:0;background:none;cursor:pointer;padding:4px 10px;border-radius:4px;font:500 11px/16px var(--mono);color:var(--muted);transition:background .15s,color .15s}
  .ranges button:hover{color:var(--text)}
  .ranges button:disabled{opacity:.4;cursor:default}
  .ranges button[aria-pressed=true]{background:var(--hi2);color:var(--text)}
  .head .grp2{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
  .legend{display:flex;flex-wrap:wrap;gap:4px 12px;font:500 10px/14px var(--mono);color:var(--muted)}
  .legend span{display:inline-flex;align-items:center;gap:4px}
  .legend i{width:10px;height:3px;border-radius:2px;display:inline-block}
  .plot{position:relative;background:var(--well);border-radius:6px;padding:8px}
  .plot svg{width:100%;height:auto;overflow:visible}
  .plot .tip{position:absolute;z-index:2;pointer-events:none;background:var(--hi);border:1px solid var(--line-strong);border-radius:6px;padding:6px 8px;
    font:500 10px/15px var(--mono);box-shadow:0 8px 24px -4px rgba(0,0,0,.6);white-space:nowrap}
  .plot .tip b{font-weight:600;color:var(--text)}

  /* ---- settings page ---- */
  .cfg{display:grid;gap:16px;grid-template-columns:minmax(0,1fr)}
  @media(min-width:1000px){.cfg{grid-template-columns:5fr 7fr}}
  .plan{background:var(--well);border-radius:6px;padding:8px;display:grid;gap:6px}
  .plan .strip{position:relative;height:22px;border-radius:4px;background:rgba(56,189,248,.12);overflow:hidden}
  .plan .seg{position:absolute;top:0;bottom:0;background:rgba(255,193,116,.2);border-left:1px solid var(--bat);border-right:1px solid var(--bat)}
  .plan .now{position:absolute;top:-2px;bottom:-2px;width:2px;background:var(--text)}
  .plan .ticks{position:relative;height:14px;font:500 10px/14px var(--mono);color:var(--dim)}
  .plan .ticks span{position:absolute;transform:translateX(-50%)}
  .plan .ticks span:first-child{transform:none} .plan .ticks span:last-child{transform:translateX(-100%)}
  .plan .legend i{height:8px;width:8px;border-radius:2px}
  .pills{display:grid;grid-template-columns:1fr 1fr;gap:4px}
  .pills>div{background:var(--well);border-radius:4px;padding:6px 8px;display:grid;gap:2px;font:400 10px/14px var(--mono);color:var(--muted)}
  .pills b{font:500 12px/16px var(--mono)}
  .form{display:grid;gap:12px;grid-template-columns:minmax(0,1fr)}
  @media(min-width:640px){.form{grid-template-columns:1fr 1fr}}
  .field{background:var(--well);border-radius:6px;padding:8px;display:grid;gap:6px;align-content:start}
  .field .top{display:flex;justify-content:space-between;gap:8px;align-items:baseline}
  .field label{font:600 10px/14px var(--mono);letter-spacing:.04em;text-transform:uppercase;color:var(--muted);overflow-wrap:anywhere}
  .field .tagl{font:500 10px/14px var(--mono);white-space:nowrap}
  .field .help{font:400 10px/14px var(--mono);color:var(--dim)}
  .field .in{display:flex;align-items:center;gap:8px}
  .field input[type=number],.field input[type=time]{width:100%;min-width:0;background:var(--tile);border:1px solid transparent;border-radius:4px;padding:4px 8px;font:500 14px/18px var(--mono);color-scheme:dark}
  .field input:focus{outline:none;border-color:var(--pv)}
  .field input[aria-invalid=true]{border-color:var(--bad)}
  .field .rv{min-width:52px;text-align:right;white-space:nowrap}
  input[type=range]{width:100%;accent-color:var(--c,var(--pv));cursor:pointer;margin:6px 0}
  .actions{display:flex;flex-wrap:wrap;align-items:center;justify-content:flex-end;gap:8px;padding-top:8px;border-top:1px solid var(--line)}
  .actions .msg{margin-right:auto;font:500 11px/16px var(--mono);min-height:16px}
  .msg.ok{color:var(--ok)} .msg.bad{color:var(--bad)} .msg.warn{color:var(--warn)}
  .btn{display:inline-flex;align-items:center;gap:6px;padding:8px 14px;border:0;border-radius:6px;background:var(--hi);color:var(--muted);cursor:pointer;transition:background .15s,color .15s}
  .btn:hover:not(:disabled){background:var(--hi2);color:var(--text)}
  .btn.primary{background:var(--pv-t);color:#00354a;font-weight:600}
  .btn.primary:hover:not(:disabled){background:var(--pv);color:#00354a}
  .btn:disabled{opacity:.45;cursor:not-allowed}
  .btn svg{width:16px;height:16px}
  .envgrid{display:grid;gap:12px;grid-template-columns:repeat(auto-fit,minmax(min(100%,340px),1fr))}
  .envgrid .grp{background:var(--well);border-radius:6px;padding:4px;display:grid;align-content:start}
  .envgrid .cap{padding:6px 8px;font:600 10px/14px var(--mono);letter-spacing:.04em;text-transform:uppercase;color:var(--pv-t)}
  .ev{display:flex;justify-content:space-between;align-items:center;gap:12px;padding:6px 8px;min-height:32px;border-radius:4px}
  .ev:hover{background:var(--tile)}
  .ev .k{font:500 11px/16px var(--mono);color:var(--muted);overflow-wrap:anywhere}
  .ev .r{display:flex;align-items:center;gap:8px;justify-content:flex-end;min-width:0}
  .ev .v{font:500 12px/16px var(--mono);text-align:right;overflow-wrap:anywhere}
  .ev .v.mask{color:var(--dim);letter-spacing:.12em}
  .ev .v.unset{color:var(--dim);font-style:italic}
  .lock{width:12px;height:12px;color:var(--dim);flex:none}
  details.acc>summary{cursor:pointer;list-style:none;border-radius:6px;justify-content:flex-start}
  details.acc>summary .tag{margin-left:auto}
  details.acc>summary::-webkit-details-marker{display:none}
  details.acc>summary::after{content:"▾";color:var(--muted);font-size:16px;transition:transform .15s;padding-left:4px}
  details.acc[open]>summary::after{transform:rotate(180deg)}
  details.acc>summary:hover h2{color:var(--pv-t)}
  details.acc[open]>summary{margin-bottom:0}
  /* ---- raw page ---- */
  .rawbar{display:flex;flex-wrap:wrap;align-items:center;gap:8px}
  .rawbar input[type=search]{flex:1 1 200px;min-width:0;max-width:360px;background:var(--well);border:1px solid var(--line);border-radius:6px;padding:7px 10px;font:500 12px/16px var(--mono);color-scheme:dark}
  .rawbar input:focus{outline:none;border-color:var(--pv)}
  .rawbar .stat2{margin-left:auto;font:500 11px/16px var(--mono);color:var(--muted);text-align:right}
  .btn.sm{padding:6px 10px;font-size:12px}
  .rawcols{display:grid;gap:12px;grid-template-columns:minmax(0,1fr)}
  @media(min-width:1100px){.rawcols{grid-template-columns:4fr 8fr}}
  .pane{max-height:calc(100vh - 280px);min-height:320px;overflow:auto;background:var(--well);border-radius:6px;padding:4px}
  .frow{display:grid;grid-template-columns:minmax(90px,1.1fr) minmax(0,1.4fr) auto;gap:8px;align-items:center;padding:5px 8px;border-radius:4px;min-height:30px}
  .frow:hover{background:var(--tile)}
  .frow .fk{font:500 12px/16px var(--mono);color:var(--muted);overflow-wrap:anywhere;display:flex;align-items:center;gap:6px;flex-wrap:wrap}
  .frow .fv{font:500 12px/16px var(--mono);text-align:right;overflow-wrap:anywhere;border-radius:3px;padding:0 4px}
  .frow .fc{font:400 10px/14px var(--mono);color:var(--dim);white-space:nowrap;min-width:36px;text-align:right}
  .frow.flash .fv{animation:flash 1.6s ease-out}
  @keyframes flash{from{background:rgba(56,189,248,.4)}to{background:transparent}}
  details.entry{border-radius:4px}
  details.entry:hover{background:var(--tile)}
  details.entry>summary{display:flex;align-items:center;gap:10px;padding:6px 8px;cursor:pointer;list-style:none;min-height:30px}
  details.entry>summary::-webkit-details-marker{display:none}
  details.entry>summary::before{content:"▸";color:var(--dim);font-size:10px;transition:transform .12s}
  details.entry[open]>summary::before{transform:rotate(90deg)}
  details.entry .et{font:500 11px/16px var(--mono);color:var(--pv-t);white-space:nowrap}
  details.entry .es{flex:1;min-width:0;font:400 11px/16px var(--mono);color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  details.entry .eb{padding:4px 10px 10px 26px;display:grid;gap:6px}
  details.entry pre{margin:0;padding:8px;background:var(--panel);border-radius:6px;font:400 11px/16px var(--mono);color:var(--text);white-space:pre-wrap;overflow-wrap:anywhere;max-height:360px;overflow:auto;user-select:text}
  .empty{padding:24px 12px;text-align:center;color:var(--dim);font:400 11px/16px var(--mono)}
  @media(prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
"""

_ICON_SLIDERS = ('<svg class="ico" style="color:var(--pv-t)" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">'
                 '<path d="M4 7h10M18 7h2M4 17h2M10 17h10"/><circle cx="16" cy="7" r="2"/><circle cx="8" cy="17" r="2"/></svg>')


def _topbar(active: str) -> str:
    cur = lambda page: ' aria-current="page"' if page == active else ""
    return f"""
<header class="topbar">
  <div class="grp">
    <nav class="nav" aria-label="Seiten"><a href="/"{cur('tele')}>Telemetrie</a><a href="/flow"{cur('flow')}>Leistungsfluss</a><a href="/control"{cur('control')}>Regler &amp; Parameter</a><a href="/raw"{cur('raw')}>Raw</a></nav>
    <span class="pill warn" id="conn"><i class="dot"></i><span id="conn-t">verbinde …</span></span>
    <div class="grp hide-sm">
      <div class="kv"><span class="lbl">Letztes Update</span><span class="unit" style="color:var(--text)" id="upd">–</span></div>
      <div class="sep"></div>
      <div class="kv"><span class="lbl">Quelle</span><span class="unit" style="color:var(--text)" id="src">–</span></div>
      <div class="sep"></div>
      <div class="kv"><span class="lbl">Zähler-Alter</span><span class="unit" style="color:var(--text)" id="meter-age">–</span></div>
    </div>
  </div>
  <div class="grp">
    <div class="kv r"><span class="lbl">Ertrag heute</span><span class="v"><span class="val" style="color:var(--pv-t)" id="h-yield">–</span><span class="unit">kWh</span></span></div>
    <div class="sep"></div>
    <div class="kv r"><span class="lbl">Batterie SOC</span><span class="v"><span class="val" style="color:var(--inv)" id="h-soc">–</span><span class="unit">%</span></span></div>
    <div class="sep"></div>
    <div class="kv r"><span class="lbl">Netz (Zähler)</span><span class="v"><span class="val" id="h-grid">–</span><span class="unit">W</span></span></div>
  </div>
</header>
"""


# Shared by both pages: helpers, state, top bar, SSE + control polling. A page fills in
# PAGE.live() (new reading / history) and PAGE.control() (fresh /api/control) and then calls start().
_COMMON_JS = r"""
const $ = (id) => document.getElementById(id);
const esc = (t) => String(t ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
const fx = (v, d = 0) => (v == null || isNaN(v)) ? '–' : Number(v).toFixed(d);
const pad2 = (n) => String(n).padStart(2, '0');
const hm = (t) => { const d = new Date(t * 1000); return pad2(d.getHours()) + ':' + pad2(d.getMinutes()); };
const hms = (t) => { const d = new Date(t * 1000); return hm(t) + ':' + pad2(d.getSeconds()); };
const toMin = (s) => { const [h, m] = String(s).split(':'); return (+h) * 60 + (+m); };
function setTag(id, text, cls) { const e = $(id); if (e) { e.textContent = text; e.className = 'tag' + (cls ? ' ' + cls : ''); } }

const PAGE = {};
let history = [], latest = null, ctl = null, sseUp = false;

function renderConn() {
  const age = latest?._t ? Date.now() / 1000 - latest._t : null;
  let cls = 'bad', txt = 'Getrennt';
  if (sseUp && age != null && age < 15) { cls = 'ok'; txt = 'Bridge online'; }
  else if (sseUp && age != null && age < 120) { cls = 'warn'; txt = 'Daten veraltet'; }
  else if (sseUp) { cls = 'bad'; txt = 'Keine Daten'; }
  $('conn').className = 'pill ' + cls;
  $('conn-t').textContent = txt;
  const t = latest?._t ? hms(latest._t) : '–';
  $('upd').textContent = age != null ? `${fx(age, 1)}s her (${t})` : '–';
  $('src').textContent = latest?.source ?? '–';
  $('meter-age').textContent = ctl?.meter_age_s != null ? ctl.meter_age_s + ' s' : '–';
  $('h-yield').textContent = fx(latest?.pvEnergyTodayKwh ?? latest?.todayEnergyKwh, 2);
  $('h-soc').textContent = fx(latest?.soc, 0);
  $('h-grid').textContent = fx(ctl?.meter_w);
}

// Battery bar with threshold markers (ids soc-*), used by both pages. Right-aligned labels
// end at their marker, so Release/Voll stay readable when the thresholds are close together.
function renderSocBar(s) {
  if (!$('soc-track')) return;
  const soc = latest?.soc;
  $('soc-v').textContent = fx(soc, 0);
  $('soc-fill').style.width = (soc == null ? 0 : Math.min(soc, 100)) + '%';
  $('soc-wh').textContent = soc != null && s ? `(${fx(soc / 100 * s.BATTERY_CAPACITY_WH)} Wh / ${fx(s.BATTERY_CAPACITY_WH)} Wh)` : '';
  if (!s) return;
  const marks = [[s.NIGHT_MIN_SOC, 'Min', 'var(--bad)', 0, 'c'], [s.CHARGE_RELEASE_SOC, 'Release', 'var(--inv)', 0, 'r'],
                 [s.CHARGE_FULL_SOC, 'Voll', 'var(--pv-t)', 1, 'r']];
  $('soc-track').querySelectorAll('.mk').forEach((e) => e.remove());
  $('soc-track').insertAdjacentHTML('beforeend', marks.map(([v, , c]) => `<div class="mk" style="left:${v}%;background:${c}"></div>`).join(''));
  const shift = {c: '-50%', r: '-100%', l: '0'};
  $('soc-scale').innerHTML = '<span style="left:0;top:0;color:var(--dim)">0%</span>' +
    marks.map(([v, l, c, row, al]) => `<span style="left:${v}%;top:${row * 15}px;transform:translateX(${shift[al]});color:${c}">${l} ${fx(v, 0)}%</span>`).join('');
}

// Battery efficiency since recording began (the bridge keeps SOC + counters from that moment):
//   (energy discharged + change of stored energy) / energy charged.
// Below 0.15 kWh charged the ratio is too noisy to show.
const EFF_MIN_KWH = 0.15;
function batteryEfficiency() {
  const r = latest, s = ctl?.settings;
  if (!r || !s || r._effBaseT == null || r.soc == null) return null;
  const charged = r.batChargeEnergyKwh - r._effBaseChargeKwh, discharged = r.batDischargeEnergyKwh - r._effBaseDischargeKwh;
  if (charged < EFF_MIN_KWH) return {pending: true, charged};
  const stored = (r.soc - r._effBaseSoc) / 100 * s.BATTERY_CAPACITY_WH / 1000;
  const pct = (discharged + stored) / charged * 100;
  return pct > 0 && pct <= 110 ? {pct, charged, discharged, stored} : {pending: true, charged};
}
function effText() {
  const e = batteryEfficiency();
  if (!e) return '–';
  return e.pending ? `sammle Daten (${fx(e.charged, 2)} / ${EFF_MIN_KWH} kWh)` : fx(e.pct, 1) + ' %';
}

async function refreshControl() {
  try { ctl = await (await fetch('/api/control')).json(); } catch (e) { return; }
  renderConn(); PAGE.control?.();
}

function applyPayload(p) {
  const r = p.reading;
  if (!r) return;
  latest = r;
  if (r._t != null) {
    const last = history[history.length - 1];
    if (!last || last._t !== r._t) { history.push(r); if (history.length > 600) history.shift(); }
  }
  // Hidden tabs keep collecting data but skip the (expensive) drawing; visibilitychange catches up.
  if (!document.hidden) { renderConn(); PAGE.live?.(); }
}

// Browsers allow only ~6 connections per host over HTTP/1.1, and every open live stream holds one
// for as long as it lives. Tabs in the background therefore close their streams and reopen them
// when shown again - otherwise a handful of open tabs starves every new request ("pending").
const streams = [];
function managedStream(url, onopen, onerror, onmessage) {
  let src = null;
  const s = {
    open() { if (src) return; src = new EventSource(url); src.onopen = onopen; src.onerror = onerror; src.onmessage = onmessage; },
    close() { if (src) { src.close(); src = null; } },
  };
  streams.push(s);
  return s;
}

async function start() {
  // Everything starts at once: the stream delivers the newest reading immediately, so only the
  // chart page needs the (compact) history, and no request waits for another.
  if (PAGE.pollLatest) {
    // Pages with their own stream (Raw) poll the latest reading instead of holding a second connection.
    const poll = async () => {
      try { const d = await (await fetch('/api/state')).json(); sseUp = true; if (d.latest) applyPayload({reading: d.latest}); } catch (e) { sseUp = false; renderConn(); }
    };
    poll(); setInterval(() => { if (!document.hidden) poll(); }, 3000);
  } else {
    managedStream('/api/stream', () => { sseUp = true; renderConn(); }, () => { sseUp = false; renderConn(); },
                  (ev) => { sseUp = true; applyPayload(JSON.parse(ev.data)); });
  }
  if (!document.hidden) streams.forEach((st) => st.open());
  addEventListener('pagehide', () => streams.forEach((st) => st.close()));
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) { streams.forEach((st) => st.close()); return; }
    streams.forEach((st) => st.open());
    renderConn(); refreshControl(); PAGE.live?.();
  });
  setInterval(() => { if (!document.hidden) refreshControl(); }, 5000);
  setInterval(() => { if (!document.hidden) renderConn(); }, 1000);
  const jobs = [refreshControl()];
  if (PAGE.needsHistory) {
    jobs.push(fetch('/api/history?compact=1').then((r) => r.json()).then((rows) => {
      // Readings that arrived over the stream while this request was running come after `rows`.
      const lastT = rows.length ? rows[rows.length - 1]._t : 0;
      history = rows.concat(history.filter((h) => h._t > lastT)).slice(-600);
      PAGE.live?.();
    }).catch(() => {}));
  }
  await Promise.all(jobs);
}

"""


_TELE_BODY = """
<main class="narrow">
  <!-- Live-Telemetrie -->
  <section class="card">
    <div class="head">
      <div class="t">
        <svg class="ico" style="color:var(--inv)" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 3v18h18"/><path d="M7 15l4-4 3 3 5-6"/></svg>
        <div><h2>Live-Telemetrie &amp; Ertragswerte</h2><p>Quelle: <span id="src2">–</span> · Update: <span id="upd2" style="color:var(--pv-t)">–</span></p></div>
      </div>
      <span class="tag" id="mqtt-tag">MQTT: –</span>
    </div>

    <div class="chips" id="chips"></div>

    <div class="soc">
      <div class="top">
        <span class="l"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"><rect x="2" y="7" width="17" height="10" rx="2"/><path d="M22 11v2"/></svg>Batterie Ladezustand (SOC)</span>
        <span style="display:flex;align-items:baseline;gap:4px"><span class="val" style="color:var(--bat);font-weight:700" id="soc-v">–</span><span class="unit">%</span><span class="unit" id="soc-wh" style="margin-left:6px"></span></span>
      </div>
      <div class="track" id="soc-track"><div class="fill" id="soc-fill" style="width:0"></div></div>
      <div class="scale" id="soc-scale"></div>
    </div>

    <div class="tables">
      <div class="tbl card sub" style="padding:4px;gap:0">
        <div class="cap" style="color:var(--pv-t)">Aktuelle Leistungen</div>
        <div id="tbl-power"></div>
      </div>
      <div class="tbl card sub" style="padding:4px;gap:0">
        <div class="cap" style="color:var(--inv)">Kumulierte Ertrags- &amp; Zählerwerte</div>
        <div id="tbl-energy"></div>
      </div>
    </div>

    <div class="foot">
      <span>Eigenverbrauchsquote: <b id="selfuse">–</b></span>
      <span title="(entladen + Änderung des Speicherinhalts) / geladen, seit Aufzeichnungsbeginn">Lade-Effizienz: <b id="eff">–</b></span>
      <span>Ausgang gespeist aus: <b id="sock-src">–</b></span>
      <span>MQTT-Zähler: <b id="mqtt-meter">–</b></span>
    </div>
  </section>
</main>
"""


_TELE_JS = r"""
const POWER_ROWS = [
  // Third entry: a "real" raw value shown in parentheses for comparison only (never used in calculations).
  ['pvPow', 'PV Gesamterzeugung', 'pvPreal'], ['pv1Pow', 'PV Eingang 1 (String A)'], ['pv2Pow', 'PV Eingang 2 (String B)'],
  ['invPow', 'Wechselrichter Ausgang'], ['batPow', 'Batterie (+ entlädt / − lädt)', 'batPreal'],
  ['offGridPow', 'Steckdose (Off-Grid-Last)'], ['loadPow', 'Ausgang gesamt (Load)'], ['_export', 'Abgabe ins Hausnetz (abgeleitet)'],
  ['gridPow', 'Netz-Durchleitung (Steckdose)'], ['_meter', 'Netz (Zähler)'],
];
const ENERGY_ROWS = [
  ['todayEnergyKwh', 'PV Energy Today (WR)', 2, ''], ['lifetimeEnergyKwh', 'PV Energy Lifetime', 2, ''],
  ['pvEnergyTodayKwh', 'PV Energy Today (Bridge)', 2, ''], ['pvEnergyTotalKwh', 'PV Energy Total (Bridge)', 4, 'var(--pv-t)'],
  ['batChargeEnergyKwh', 'Batterie Ladeenergie (Gesamt)', 4, 'var(--inv)'], ['batDischargeEnergyKwh', 'Batterie Entladeenergie (Gesamt)', 4, 'var(--bat)'],
];

function chip(color, label, v, max) {
  const pct = v == null ? 0 : Math.min(Math.abs(v) / max * 100, 100);
  return `<div class="chip" style="--c:${color}"><div class="r"><span><i></i>${label}</span><span class="val">${fx(v)} W</span></div><div class="bar"><div style="width:${pct}%"></div></div></div>`;
}

// Derived (from a capture with a test feed-in): the inverter's total output (invPow == loadPow) minus what the
// socket itself draws (offGridPow) is what it feeds into the house grid.
function exportW(r) {
  if (r.invPow == null || r.offGridPow == null) return null;
  const d = r.invPow - r.offGridPow;
  return d > 3 ? d : 0;
}

// What feeds the inverter's output, read off the device fields (verified against captures):
// pvPow > 0 = PV contributes, batPow > 0 = battery discharging, gridPow > 0 = grid passed through to the socket.
function socketSource(r) {
  if (r.offGridPow == null || r.invPow == null) return '–';
  if (r.offGridPow < 5 && r.invPow < 5) return 'keine Last';
  const src = [];
  if (r.pvPow > 5) src.push('PV');
  if (r.batPow > 5) src.push('Akku');
  if (r.gridPow > 5) src.push('Netz');
  return src.join(' + ') || 'unklar';
}

function renderLive() {
  const r = latest || {}, meter = ctl?.meter_w;
  const max = Math.max(800, ctl?.control_max_w || 0);
  $('chips').innerHTML =
    chip('#38bdf8', 'PV', r.pvPow, max) + chip('#4edea3', 'WR Out', r.invPow, max) +
    chip('#f59e0b', 'Akku', r.batPow, max) + chip('#ffb4ab', 'Steckdose', r.offGridPow, max) +
    chip('#94a3b8', 'Netz', meter ?? r.gridPow, max);
  $('tbl-power').innerHTML = POWER_ROWS.map(([k, label, alt]) => {
    const v = k === '_meter' ? meter : k === '_export' ? (r.exportPow ?? exportW(r)) : r[k];
    const on = (k === 'pv1Pow' || k === 'pv2Pow') && v > 0;
    const real = alt && r[alt] != null ? `<span class="unit" title="${alt}: Rohwert des Geräts, nur zum Vergleich">(${fx(r[alt])} W)</span>` : '';
    return `<div class="row${on ? ' on' : ''}"><span>${label}</span><span class="vv"><span class="val"${on ? ' style="color:var(--pv-t)"' : ''}>${fx(v)}</span><span class="unit">W</span>${real}</span></div>`;
  }).join('');
  $('tbl-energy').innerHTML = ENERGY_ROWS.map(([k, label, dec, color]) =>
    `<div class="row"><span>${label}</span><span class="vv"><span class="val"${color ? ` style="color:${color}"` : ''}>${fx(r[k], dec)}</span><span class="unit">kWh</span></span></div>`
  ).join('');
  $('src2').textContent = r.source ?? '–';
  $('upd2').textContent = r._t ? hms(r._t) : '–';
  // Share of consumption covered by PV/battery instead of the grid (needs the meter).
  const inv = r.invPow, load = meter != null && inv != null ? meter + inv : null;
  $('eff').textContent = effText();
  $('sock-src').textContent = socketSource(r);
  $('selfuse').textContent = load && load > 0 ? fx(Math.min(inv / load * 100, 100), 0) + ' %' : '–';
  renderSocBar(ctl?.settings);
}

function renderMqtt() {
  const c = ctl; if (!c) return;
  setTag('mqtt-tag', 'MQTT: ' + (c.mqtt_connected ? 'verbunden' : 'getrennt'), c.mqtt_connected ? 'ok' : 'bad');
  $('mqtt-meter').textContent = c.mqtt_connected ? (c.meter_w != null ? 'empfängt' : 'wartet') : 'getrennt';
}
PAGE.live = renderLive;
PAGE.control = () => { renderMqtt(); renderLive(); };

"""


_FLOW_BODY = """
<main>
<!-- Live-Leistungsfluss -->
<section class="card">
  <div class="head lg">
    <div class="t">
      <svg class="ico" style="color:var(--pv-t);width:24px;height:24px" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12h4l3-8 4 16 3-8h4"/></svg>
      <div><h2>Leistungsfluss</h2><p id="flow-sub">Erzeugung und Akku als ungefilterte Real-Werte · Steckdose, Abgabe ins Hausnetz · Netzzähler und SOC daneben · Maus über den Chart für Werte</p></div>
    </div>
    <div class="grp2"><div class="ranges"><button type="button" id="smooth" title="Gleitender Durchschnitt über ~20 s (nur Live-Ansicht)">Glätten</button></div><div class="ranges" id="ranges" role="group" aria-label="Zeitraum"></div><span class="tag info" id="span-tag">–</span></div>
  </div>
  <div class="flow">
    <div class="card sub">
      <div class="head"><span class="lbl">Leistung [W]</span><div class="legend" id="legend-power"></div></div>
      <div class="plot" id="chart-power"></div>
    </div>
    <div class="stack">
      <div class="card sub">
        <div class="head"><span class="lbl">Netz (Zähler) [W]</span>
          <div class="legend"><span><i style="background:var(--grid);height:3px"></i>+ Bezug / − Einspeisung</span></div></div>
        <div class="plot" id="chart-meter"></div>
      </div>
      <div class="card sub">
        <div class="head"><span class="lbl">Batterie SOC [%]</span>
          <div class="legend"><span><i style="background:var(--bat-c)"></i>SOC</span><span><i style="background:var(--bad);height:1px"></i>Min</span><span><i style="background:var(--pv-t);height:1px"></i>Voll</span></div></div>
        <div class="plot" id="chart-soc"></div>
      </div>
    </div>
  </div>
</section>
</main>
"""


_FLOW_JS = r"""
const POWER_SERIES = [
  ['pvPreal', 'PV', '#38bdf8', 2, 'pvPow'],   // 5th entry: fallback key when the real value is missing
  ['invPow', 'WR', '#4edea3', 1.75],
  ['batPreal', 'Akku', '#ffc174', 1.5, 'batPow'],
  ['offGridPow', 'Steckdose', '#ffb4ab', 1.5],
  ['exportPow', 'Abgabe Hausnetz', '#c4b5fd', 1.5],
];
const METER_SERIES = [['meterPow', 'Netz (Zähler)', '#cbd5e1', 1.75]];
/* ---------- range: "live" = raw readings from memory, else 1-minute averages from the bridge's SQLite ---------- */
const RANGES = [['live', 'Live', 0], ['6h', '6 h', 360], ['24h', '24 h', 1440], ['7d', '7 T', 10080], ['30d', '30 T', 43200]];
let range = 'live', longData = null;
try { const r = localStorage.getItem('flow-range'); if (RANGES.some((x) => x[0] === r)) range = r; } catch (e) {}

// Live view only: centred moving average over ~20 s (7 samples) of the plotted values. The stored data
// is untouched; ranges from 6 h up are per-minute averages already.
let smoothOn = true;
try { smoothOn = localStorage.getItem('flow-smooth') !== '0'; } catch (e) {}
const SMOOTH_KEYS = ['pvPow', 'pvPreal', 'invPow', 'batPow', 'batPreal', 'offGridPow', 'exportPow', 'meterPow'];
const SMOOTH_HALF = 3;
let smoothCache = {key: '', rows: null};
function smoothed(rows) {
  if (!smoothOn || rows.length < 3) return rows;
  const key = rows.length + ':' + rows[rows.length - 1]._t;
  if (smoothCache.key === key) return smoothCache.rows;
  const out = rows.map((row, i) => {
    const o = {...row}, a = Math.max(0, i - SMOOTH_HALF), b = Math.min(rows.length - 1, i + SMOOTH_HALF);
    for (const k of SMOOTH_KEYS) {
      if (row[k] == null) continue;
      let sum = 0, n = 0;
      for (let j = a; j <= b; j++) { const v = rows[j][k]; if (v != null) { sum += v; n++; } }
      o[k] = sum / n;
    }
    return o;
  });
  smoothCache = {key, rows: out};
  return out;
}
const chartData = () => range === 'live' ? smoothed(history) : (longData?.rows ?? []);
const gapSeconds = () => range === 'live' ? 60 : (longData?.step ?? 60) * 2.5;  // longer holes are drawn as breaks
const dhm = (t) => { const d = new Date(t * 1000); return `${pad2(d.getDate())}.${pad2(d.getMonth() + 1)}. ${hm(t)}`; };

function renderSmooth() {
  const b = $('smooth');
  b.setAttribute('aria-pressed', String(smoothOn && range === 'live'));
  b.disabled = range !== 'live';
  b.onclick = () => { smoothOn = !smoothOn; try { localStorage.setItem('flow-smooth', smoothOn ? '1' : '0'); } catch (e) {} renderSmooth(); renderCharts(); };
}
function renderRanges() {
  renderSmooth();
  $('ranges').innerHTML = RANGES.map(([k, label]) => `<button type="button" data-r="${k}" aria-pressed="${k === range}">${label}</button>`).join('');
  $('ranges').querySelectorAll('button').forEach((b) => b.onclick = () => setRange(b.dataset.r));
}
async function loadLong() {
  const minutes = RANGES.find((x) => x[0] === range)[2];
  if (!minutes) return;
  try {
    const d = await (await fetch('/api/history/long?minutes=' + minutes)).json();
    if (range === RANGES.find((x) => x[2] === minutes)[0]) { longData = d; renderCharts(); }
  } catch (e) {}
}
function setRange(r) {
  range = r; longData = null;
  try { localStorage.setItem('flow-range', r); } catch (e) {}
  hover['chart-power'] = hover['chart-meter'] = hover['chart-soc'] = null;
  renderRanges(); renderCharts(); loadLong();
}

/* ---------- charts: drawn at their real pixel width so text stays crisp on wide screens ---------- */
const hover = {};
function niceStep(range, n) {
  const raw = range / n, pow = Math.pow(10, Math.floor(Math.log10(raw || 1)));
  for (const m of [1, 2, 2.5, 5, 10]) if (m * pow >= raw) return m * pow;
  return 10 * pow;
}

// Index of the sample closest to time t (data is sorted by _t).
function nearest(data, t) {
  let lo = 0, hi = data.length - 1;
  while (hi - lo > 1) { const m = (lo + hi) >> 1; if (data[m]._t < t) lo = m; else hi = m; }
  return Math.abs(data[lo]._t - t) <= Math.abs(data[hi]._t - t) ? lo : hi;
}

function drawChart(id, series, opts) {
  const el = $(id), W = Math.max(280, Math.floor((el.clientWidth || 640) - 16)), H = opts.h;
  const L = 42, R = 12, T = 8, B = 22;
  const data = chartData();
  const altKey = Object.fromEntries(series.map((sr) => [sr[0], sr[4]]));
  const V = (p, k) => p[k] ?? (altKey[k] ? p[altKey[k]] : null);
  if (data.length < 2) {
    const msg = range === 'live' ? 'warte auf Daten …' : longData && longData.enabled === false ? 'Verlaufs-Datenbank nicht verfügbar'
      : longData ? 'noch nicht genug Daten – es wird jede Minute ein Wert gespeichert' : 'lade …';
    el.innerHTML = `<div class="unit" style="padding:24px 0;text-align:center">${msg}</div>`; return;
  }
  const tMin = data[0]._t, tMax = data[data.length - 1]._t, span = Math.max(tMax - tMin, 1), gap = gapSeconds();
  const fmtAxis = span > 36 * 3600 ? dhm : hm, fmtTip = span > 36 * 3600 ? dhm : hms;
  let lo = opts.min, hi = opts.max, step = opts.step;
  if (lo === undefined) {
    lo = 0; hi = 0;
    for (const p of data) for (const [k] of series) { const v = V(p, k); if (v != null) { lo = Math.min(lo, v); hi = Math.max(hi, v); } }
    step = niceStep(Math.max(hi - lo, 40), H > 250 ? 6 : 4);
    lo = Math.floor(lo / step) * step; hi = Math.ceil(hi / step) * step; if (hi === lo) hi = lo + step;
  }
  const x = (t) => L + (t - tMin) / span * (W - L - R), y = (v) => T + (hi - v) / (hi - lo) * (H - T - B);
  let s = `<svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img" aria-label="${esc(opts.label)}">`;
  for (let v = lo; v <= hi + 1e-9; v += step) {
    s += `<line x1="${L}" x2="${W - R}" y1="${y(v).toFixed(1)}" y2="${y(v).toFixed(1)}" stroke="#334155" stroke-opacity="${v === 0 ? .7 : .3}" stroke-dasharray="${v === 0 ? '' : '2 3'}"/>` +
         `<text x="${L - 6}" y="${(y(v) + 3).toFixed(1)}" text-anchor="end" font-size="10" fill="#87929a" font-family="monospace">${v}</text>`;
  }
  const nT = W > 700 ? 6 : 4;
  for (let i = 0; i <= nT; i++) {
    const t = tMin + span * i / nT;
    s += `<text x="${x(t).toFixed(1)}" y="${H - 6}" text-anchor="${i === 0 ? 'start' : i === nT ? 'end' : 'middle'}" font-size="10" fill="#87929a" font-family="monospace">${fmtAxis(t)}</text>`;
  }
  for (const [v, color] of (opts.ref || [])) s += `<line x1="${L}" x2="${W - R}" y1="${y(v).toFixed(1)}" y2="${y(v).toFixed(1)}" stroke="${color}" stroke-opacity=".8" stroke-dasharray="4 3"/>`;
  for (const [k, , color, w] of series) {
    let d = '', prevT = null;
    for (const p of data) {
      const v = V(p, k);
      if (v == null) continue;
      d += (d && prevT != null && p._t - prevT <= gap ? 'L' : 'M') + x(p._t).toFixed(1) + ' ' + y(v).toFixed(1);
      prevT = p._t;
    }
    if (d) s += `<path d="${d}" fill="none" stroke="${color}" stroke-width="${w || 1.5}" stroke-linejoin="round" stroke-linecap="round"/>`;
  }
  // Cursor + tooltip live in their own layer: hovering repaints only these, never the whole chart.
  el.innerHTML = s + '<g class="cur"></g></svg><div class="tip" hidden></div>';
  const svg = el.querySelector('svg'), cur = svg.querySelector('.cur'), tipEl = el.querySelector('.tip');
  const paint = (idx) => {
    const p = data[idx];
    if (!p) { cur.innerHTML = ''; tipEl.hidden = true; return; }
    const px = x(p._t);
    let c = `<line x1="${px.toFixed(1)}" x2="${px.toFixed(1)}" y1="${T}" y2="${H - B}" stroke="#8ed5ff" stroke-opacity=".6"/>`;
    for (const [k, , color] of series) if (V(p, k) != null) c += `<circle cx="${px.toFixed(1)}" cy="${y(V(p, k)).toFixed(1)}" r="3" fill="${color}"/>`;
    cur.innerHTML = c;
    tipEl.innerHTML = `<b>${fmtTip(p._t)}</b>` +
      series.map(([k, l, col]) => `<div><span style="color:${col}">●</span> ${l} <b>${fx(V(p, k))}</b> ${opts.unit}</div>`).join('');
    const flip = px / W > .6;
    tipEl.style.top = '12px';
    tipEl.style.left = flip ? 'auto' : (px + 20) + 'px';
    tipEl.style.right = flip ? (W - px + 20) + 'px' : 'auto';
    tipEl.hidden = false;
  };
  let raf = 0, lastX = 0;
  svg.onmousemove = svg.ontouchmove = (ev) => {
    lastX = (ev.touches ? ev.touches[0] : ev).clientX;
    if (raf) return;
    raf = requestAnimationFrame(() => {
      raf = 0;
      const r = svg.getBoundingClientRect();
      const idx = nearest(data, tMin + ((lastX - r.left) / r.width * W - L) / (W - L - R) * span);
      if (hover[id] !== idx) { hover[id] = idx; paint(idx); }
    });
  };
  svg.onmouseleave = svg.ontouchend = () => { hover[id] = null; paint(-1); };
  if (hover[id] != null) paint(hover[id]);
}

let plotTop = null;
function renderCharts() {
  // Wide screens: the power chart takes all height left on the screen and the meter and SOC charts
  // share the same height in the right column (72 px = head, gaps and paddings of one card).
  // Narrow screens stack everything with fixed heights.
  const wide = innerWidth >= 1100;
  if (plotTop == null) plotTop = $('chart-power').getBoundingClientRect().top + scrollY;
  const hPower = !wide ? (innerWidth < 700 ? 240 : 280) : Math.max(300, Math.floor(innerHeight - plotTop - 66));
  const hSide = !wide ? (innerWidth < 700 ? 150 : 170) : Math.max(110, Math.floor((hPower - 84) / 2));
  $('legend-power').innerHTML = POWER_SERIES.map(([, l, c]) => `<span><i style="background:${c}"></i>${l}</span>`).join('');
  drawChart('chart-power', POWER_SERIES, {unit: 'W', label: 'Leistung in Watt', h: hPower});
  drawChart('chart-meter', METER_SERIES, {unit: 'W', label: 'Netzzähler in Watt', h: hSide});
  const s = ctl?.settings;
  drawChart('chart-soc', [['soc', 'SOC', '#f59e0b', 1.75]], {min: 0, max: 100, step: 25, unit: '%', label: 'Batterie SOC', h: hSide,
    ref: s ? [[s.NIGHT_MIN_SOC, '#ffb4ab'], [s.CHARGE_FULL_SOC, '#8ed5ff']] : []});
  const data = chartData();
  if (data.length > 1) {
    const min = (data[data.length - 1]._t - data[0]._t) / 60;
    const spanTxt = min >= 2880 ? `${fx(min / 1440, 1)} Tage` : min >= 90 ? `${fx(min / 60, 1)} h` : `${fx(min, 0)} min`;
    $('span-tag').textContent = range === 'live' ? `letzte ${spanTxt}` : `${spanTxt} · Ø je ${fx((longData?.step ?? 60) / 60, 0)} min`;
  } else $('span-tag').textContent = '–';
}
PAGE.needsHistory = true;
PAGE.live = () => { if (range === 'live') renderCharts(); };
// The 5 s control refresh only matters here when the threshold lines changed.
let refKey = null;
PAGE.control = () => {
  const c = ctl?.settings, key = c ? c.NIGHT_MIN_SOC + '/' + c.CHARGE_FULL_SOC : '';
  if (key !== refKey) { refKey = key; renderCharts(); }
};
let resizeTimer = 0;
addEventListener('resize', () => { clearTimeout(resizeTimer); resizeTimer = setTimeout(() => { plotTop = null; renderCharts(); }, 120); });
setInterval(() => { if (range !== 'live') loadLong(); }, 60000);
renderRanges();
if (range !== 'live') loadLong();

"""


_CONTROL_BODY = f"""
<main>
<div class="cfg">
  <!-- Nulleinspeisung -->
  <section class="card">
    <div class="head">
      <div class="t">{_ICON_SLIDERS}<div><h2>Nulleinspeisung</h2><p>Zähler → Ausgangsleistung</p></div></div>
      <span class="tag" id="ctl-mode">–</span>
    </div>

    <div class="trio">
      <div class="stat" style="--c:var(--grid)">
        <span class="lbl">Zähler (Netz)</span>
        <div><span class="big" id="t-meter">–</span> <span class="unit">W</span></div>
        <span class="sub" id="t-meter-s">–</span>
      </div>
      <div class="stat" style="--c:var(--inv);--c2:var(--inv)">
        <span class="lbl">WR Ausgang</span>
        <div><span class="big" id="t-inv">–</span> <span class="unit">W</span></div>
        <span class="sub" id="t-inv-s">–</span>
      </div>
      <div class="stat" style="--c:var(--pv-t);--c2:var(--pv-t)">
        <span class="lbl">Sollwert</span>
        <div><span class="big" id="t-set">–</span> <span class="unit">W</span></div>
        <span class="sub" id="t-set-s">–</span>
      </div>
    </div>

    <div class="well">
      <label class="opt"><span class="l"><input type="checkbox" id="ctl-enabled" onchange="setControl()"><span class="n"><b>Regler aktiv</b><small>Wechselrichter-Ausgang wird nachgeführt</small></span></span><span class="tag" id="b-enabled">–</span></label>
      <label class="opt"><span class="l"><input type="checkbox" id="ctl-dry" onchange="setControl()"><span class="n"><b>Trockenlauf</b><small>Nur loggen, nichts ans Gerät senden</small></span></span><span class="tag" id="b-dry">–</span></label>
      <label class="opt"><span class="l"><input type="checkbox" id="ctl-plan" onchange="setControl()"><span class="n"><b>Batterie-Plan</b><small>Tag laden, Nacht abgeben</small></span></span><span class="tag" id="b-plan">–</span></label>
    </div>

    <div class="note">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>
      <div><b id="phase">–</b><small id="est">–</small></div>
    </div>

    <div class="status">
      <span class="s"><i class="dot" id="st-dot" style="color:var(--ok)"></i><span class="lbl">Regelstatus</span></span>
      <span class="txt" id="last-action">–</span>
    </div>

    <details class="diag" id="diag">
      <summary>Diagnose (Zähler / MQTT)</summary>
      <pre id="diag-pre">–</pre>
    </details>
  </section>

    <div class="card sub">
      <div class="head"><h2 style="font-size:16px">Parameter-Matrix &amp; Schwellenwerte</h2><span class="tag warn" id="dirty" hidden>ungespeicherte Änderungen</span></div>
      <p class="unit" style="margin-top:-6px">Tag/Nacht-Zeitfenster, Ladereserve und Tiefentladeschutz des Batterie-Plans.</p>
      <form class="form" id="cfg-form" onsubmit="return false" novalidate>
        <div class="field"><div class="top"><label for="cfg-BATTERY_CAPACITY_WH">BATTERY_CAPACITY_WH</label><span class="tagl" style="color:var(--pv-t)">Nennkapazität</span></div>
          <div class="in"><input type="number" id="cfg-BATTERY_CAPACITY_WH" min="100" max="100000" step="1"><span class="unit">Wh</span></div>
          <span class="help">Basis für die Restzeit-Schätzung</span></div>

        <div class="field"><div class="top"><label for="cfg-CHARGE_RESERVE_W">CHARGE_RESERVE_W</label><span class="tagl" style="color:var(--inv)">Ladereserve</span></div>
          <div class="in"><input type="number" id="cfg-CHARGE_RESERVE_W" min="0" max="2000" step="10"><span class="unit">W</span></div>
          <span class="help">Tagsüber fürs Laden zurückgehalten, nur der Rest wird eingespeist</span></div>

        <div class="field" style="--c:var(--pv-t)"><div class="top"><label for="cfg-CHARGE_FULL_SOC">CHARGE_FULL_SOC</label><span class="tagl" style="color:var(--bat)">Ziel-Vollladung</span></div>
          <div class="in"><input type="range" id="cfg-CHARGE_FULL_SOC" min="50" max="100" step="1"><span class="val rv"><span id="rv-CHARGE_FULL_SOC"></span><span class="unit"> %</span></span></div>
          <span class="help">Ab hier gilt der Akku als voll → nur PV-Durchleitung</span></div>

        <div class="field" style="--c:var(--inv)"><div class="top"><label for="cfg-CHARGE_RELEASE_SOC">CHARGE_RELEASE_SOC</label><span class="tagl" style="color:var(--inv)">Freigabe-Schwelle</span></div>
          <div class="in"><input type="range" id="cfg-CHARGE_RELEASE_SOC" min="50" max="100" step="1"><span class="val rv"><span id="rv-CHARGE_RELEASE_SOC"></span><span class="unit"> %</span></span></div>
          <span class="help">Fällt der SOC darunter, wird wieder geladen (Hysterese)</span></div>

        <div class="field"><div class="top"><label for="cfg-NIGHT_START">NIGHT_START</label><span class="tagl" style="color:var(--dim)">Beginn Nachtabgabe</span></div>
          <div class="in"><input type="time" id="cfg-NIGHT_START"></div>
          <span class="help">Uhrzeit, ab der nachts abgegeben wird</span></div>

        <div class="field"><div class="top"><label for="cfg-NIGHT_END">NIGHT_END</label><span class="tagl" style="color:var(--dim)">Ende Nachtabgabe</span></div>
          <div class="in"><input type="time" id="cfg-NIGHT_END"></div>
          <span class="help">Danach wieder Tagbetrieb (Laden)</span></div>

        <div class="field"><div class="top"><label for="cfg-NIGHT_MAX_W">NIGHT_MAX_W</label><span class="tagl" style="color:var(--bad)">Nacht-Deckelung</span></div>
          <div class="in"><input type="number" id="cfg-NIGHT_MAX_W" min="0" max="2000" step="10"><span class="unit">W</span></div>
          <span class="help">Höchste Abgabe aus dem Akku während der Nacht</span></div>

        <div class="field" style="--c:var(--load-c)"><div class="top"><label for="cfg-NIGHT_MIN_SOC">NIGHT_MIN_SOC</label><span class="tagl" style="color:var(--bad)">Tiefentladeschutz</span></div>
          <div class="in"><input type="range" id="cfg-NIGHT_MIN_SOC" min="0" max="100" step="1"><span class="val rv" style="color:var(--bad)"><span id="rv-NIGHT_MIN_SOC"></span><span class="unit"> %</span></span></div>
          <span class="help">Bei SOC ≤ diesem Wert keine Nachtabgabe</span></div>
      </form>
      <div class="actions">
        <span class="msg" id="cfg-msg" role="status"></span>
        <button class="btn" type="button" id="btn-reset"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/></svg>Standard (.env)</button>
        <button class="btn" type="button" id="btn-revert" disabled>Verwerfen</button>
        <button class="btn primary" type="button" id="btn-save" disabled><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 16V4M6 10l6-6 6 6M4 20h16"/></svg>Übernehmen</button>
      </div>
    </div>
</div>

<section class="card">
  <div class="head lg">
    <div class="t">
      <svg class="ico" style="color:var(--bat);width:24px;height:24px" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="7" width="17" height="10" rx="2"/><path d="M22 11v2"/></svg>
      <div><h2>Batterie-Plan Vorschau</h2><p>Zeigt die Schwellen und das Zeitfenster – auch mit ungespeicherten Änderungen</p></div>
    </div>
  </div>
  <div class="prev">
      <div class="soc" style="background:var(--well)">
        <div class="top">
          <span class="l"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"><rect x="2" y="7" width="17" height="10" rx="2"/><path d="M22 11v2"/></svg>Batterie-Schwellen</span>
          <span style="display:flex;align-items:baseline;gap:4px"><span class="val" style="color:var(--bat);font-weight:700" id="soc-v">–</span><span class="unit">%</span><span class="unit" id="soc-wh" style="margin-left:6px"></span></span>
        </div>
        <div class="track" id="soc-track"><div class="fill" id="soc-fill" style="width:0"></div></div>
        <div class="scale" id="soc-scale"></div>
      </div>
      <div class="plan">
        <div class="lbl">Tagesplan (24 h)</div>
        <div class="strip" id="plan-strip"></div>
        <div class="ticks"><span style="left:0">00</span><span style="left:25%">06</span><span style="left:50%">12</span><span style="left:75%">18</span><span style="left:100%">24</span></div>
        <div class="legend"><span><i style="background:rgba(56,189,248,.35)"></i>Tag: laden, Reserve <b id="lg-reserve" style="color:var(--text)">–</b> W</span><span><i style="background:rgba(255,193,116,.5)"></i>Nacht: bis <b id="lg-night" style="color:var(--text)">–</b> W</span><span><i style="background:var(--text);width:2px"></i>jetzt</span></div>
      </div>
      <div class="pills">
        <div>Tiefentladeschutz<b id="p-prot">–</b></div>
        <div>Zeitfenster jetzt<b id="p-win">–</b></div>
        <div>Akku voll in<b id="p-full">–</b></div>
        <div>Nachtreichweite<b id="p-night">–</b></div>
      </div>
  </div>
</section>

<details class="card acc" id="env-acc">
  <summary class="head lg">
    <div class="t">
      <svg class="ico" style="color:var(--pv-t);width:24px;height:24px" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="11" width="16" height="9" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/></svg>
      <div><h2>Umgebung (.env)</h2><p>Nur lesen · Passwörter maskiert · Änderungen in der .env und Container neu starten</p></div>
    </div>
    <span class="tag">read-only</span>
  </summary>
  <div class="envgrid" id="envgrid"><div class="unit">lade …</div></div>
</details>
</main>
"""


_CONTROL_JS = r"""
function renderControl() {
  const c = ctl; if (!c) return;
  $('ctl-enabled').checked = c.enabled; $('ctl-dry').checked = c.dry_run; $('ctl-plan').checked = c.plan;
  const live = c.enabled && !c.dry_run;
  setTag('ctl-mode', !c.enabled ? 'Aus' : c.dry_run ? 'Trockenlauf' : 'Aktiv', !c.enabled ? '' : c.dry_run ? 'warn' : 'ok');
  setTag('b-enabled', live ? 'RUNNING' : c.enabled ? 'SIMULATION' : 'AUS', live ? 'ok' : c.enabled ? 'warn' : '');
  setTag('b-dry', c.dry_run ? 'AN' : 'AUS', c.dry_run ? 'warn' : '');
  setTag('b-plan', c.plan ? 'AUTO-SCHEDULE' : 'AUS', c.plan ? 'info' : '');

  const inv = c.inverter_w, meter = c.meter_w;
  $('t-meter').textContent = fx(meter); $('t-inv').textContent = fx(inv); $('t-set').textContent = fx(c.setpoint_w);
  $('t-meter-s').textContent = meter == null ? 'kein Messwert' : meter > 0 ? '↑ Bezug' : meter < 0 ? '↓ Einspeisung' : 'ausgeglichen';
  $('t-meter-s').style.color = meter > 0 ? 'var(--bad)' : meter < 0 ? 'var(--warn)' : 'var(--ok)';
  $('t-inv-s').textContent = inv != null && c.control_max_w ? `Auslastung ${fx(inv / c.control_max_w * 100)} %` : '–';
  $('t-set-s').textContent = c.setpoint_w != null && inv != null ? `Delta: ${fx(inv - c.setpoint_w)} W` : 'Ziel ' + fx(c.target_w) + ' W Bezug';

  $('phase').textContent = c.phase;
  renderEst();

  const la = c.last_action || '–', bad = /FEHLER/.test(la), warn = /TROCKENLAUF|übersprungen/.test(la);
  $('last-action').textContent = la;
  $('last-action').className = 'txt' + (bad ? ' bad' : warn ? ' warn' : '');
  $('st-dot').style.color = bad ? 'var(--bad)' : warn ? 'var(--warn)' : 'var(--ok)';


  const pretty = (t) => { try { return JSON.stringify(JSON.parse(t), null, 2); } catch (e) { return t; } };
  $('diag-pre').textContent =
    `MQTT: ${c.mqtt_connected ? 'verbunden' : 'getrennt'} · Discovery: ${c.config_seen ? 'gefunden' : 'nicht gesehen'}\n` +
    `Topic: ${c.state_topic ?? '–'} · Pfad: ${c.value_path ?? '(reine Zahl)'}\n` +
    `Letzte Nachricht: ${c.last_payload ? '\n' + pretty(c.last_payload) : 'noch keine empfangen'}`;
  // Meter/broker details only matter while something is wrong - open them then, unless the user chose otherwise.
  if ((c.meter_w == null || !c.mqtt_connected) && !$('diag').dataset.touched) $('diag').open = true;
}
$('diag').addEventListener('toggle', () => { $('diag').dataset.touched = '1'; });

async function setControl() {
  const enabled = $('ctl-enabled').checked, dry_run = $('ctl-dry').checked, plan = $('ctl-plan').checked;
  if (enabled && !dry_run && !confirm('Regler schreibt jetzt echte Leistungswerte ans Gerät. Fortfahren?')) return refreshControl();
  const res = await fetch('/api/control', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({enabled, dry_run, plan})});
  if (res.ok) { ctl = await res.json(); PAGE.control(); } else refreshControl();
}


function renderEst() {
  const c = ctl; if (!c) return;
  const eff = batteryEfficiency();
  const est = [c.est_full_h != null ? `Akku voll in ~${c.est_full_h} h` : null, c.est_night_h != null ? `Nachtreichweite ~${c.est_night_h} h` : null,
               eff && !eff.pending ? `Lade-Effizienz ${fx(eff.pct, 1)} %` : null].filter(Boolean);
  $('est').textContent = est.join(' · ') || '–';
}

const SETTING_KEYS = ['BATTERY_CAPACITY_WH', 'CHARGE_RESERVE_W', 'CHARGE_FULL_SOC', 'CHARGE_RELEASE_SOC',
                      'NIGHT_START', 'NIGHT_END', 'NIGHT_MAX_W', 'NIGHT_MIN_SOC'];
let dirty = false;
const inputOf = (k) => $('cfg-' + k);

/* ---------- form ---------- */
function fillForm(values) {
  for (const k of SETTING_KEYS) {
    const el = inputOf(k), v = String(values[k]);
    if (el.value !== v && document.activeElement !== el) el.value = v;
    const rv = $('rv-' + k); if (rv) rv.textContent = el.value;
  }
}
function readForm() {
  const out = {};
  for (const k of SETTING_KEYS) {
    const el = inputOf(k);
    out[k] = el.type === 'time' ? el.value : el.value === '' ? null : Number(el.value);
  }
  return out;
}
function setDirty(v) {
  dirty = v;
  $('dirty').hidden = !v; $('btn-save').disabled = !v; $('btn-revert').disabled = !v;
}
function message(text, cls) {
  const m = $('cfg-msg'); m.textContent = text; m.className = 'msg ' + (cls || '');
  clearTimeout(message.t); if (cls === 'ok') message.t = setTimeout(() => { m.textContent = ''; }, 3500);
}
function validate(v) {
  for (const k of SETTING_KEYS) inputOf(k).setAttribute('aria-invalid', 'false');
  const bad = (k, t) => { inputOf(k).setAttribute('aria-invalid', 'true'); return t; };
  for (const k of SETTING_KEYS) {
    const el = inputOf(k);
    if (v[k] === null || v[k] === '' || (el.type !== 'time' && (isNaN(v[k]) || v[k] < +el.min || v[k] > +el.max)))
      return bad(k, el.type === 'time' ? `${k}: Uhrzeit eingeben` : `${k}: Wert zwischen ${el.min} und ${el.max} eingeben`);
  }
  if (v.CHARGE_RELEASE_SOC > v.CHARGE_FULL_SOC) return bad('CHARGE_RELEASE_SOC', 'CHARGE_RELEASE_SOC darf nicht über CHARGE_FULL_SOC liegen');
  return null;
}

for (const k of SETTING_KEYS) {
  inputOf(k).addEventListener('input', () => {
    setDirty(true); message('', '');
    for (const kk of SETTING_KEYS) inputOf(kk).setAttribute('aria-invalid', 'false');
    const rv = $('rv-' + k); if (rv) rv.textContent = inputOf(k).value;
    renderPreview();
  });
}
$('btn-reset').onclick = () => {
  if (!ctl) return;
  fillForm(ctl.defaults); setDirty(true); renderPreview();
  message('Standardwerte aus .env geladen – mit „Übernehmen“ speichern', 'warn');
};
$('btn-revert').onclick = () => { setDirty(false); message('', ''); if (ctl) fillForm(ctl.settings); renderPreview(); };
$('btn-save').onclick = async () => {
  const values = readForm(), err = validate(values);
  if (err) return message(err, 'bad');
  $('btn-save').disabled = true;
  try {
    const res = await fetch('/api/control', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({settings: values})});
    const body = await res.json();
    if (!res.ok) { message(body.error || 'Speichern fehlgeschlagen', 'bad'); $('btn-save').disabled = false; return; }
    ctl = body; setDirty(false); fillForm(ctl.settings); renderPreview(); message('Parameter übernommen', 'ok');
  } catch (e) { message('Bridge nicht erreichbar', 'bad'); $('btn-save').disabled = false; }
};

/* ---------- preview: follows the form, falls back to the saved value for invalid fields ---------- */
function currentValues() {
  const s = ctl?.settings; if (!s) return null;
  const f = readForm(), out = {};
  for (const k of SETTING_KEYS) {
    const el = inputOf(k), v = f[k];
    const ok = el.type === 'time' ? /^[0-9]{2}:[0-9]{2}$/.test(v) : v !== null && !isNaN(v);
    out[k] = dirty && ok ? v : s[k];
  }
  return out;
}

function renderPreview() {
  const s = currentValues(); if (!s) return;
  renderSocBar(s);
  const a = toMin(s.NIGHT_START), b = toMin(s.NIGHT_END);
  const seg = (from, to) => `<div class="seg" style="left:${from / 14.4}%;width:${(to - from) / 14.4}%"></div>`;
  const now = new Date(), nowMin = now.getHours() * 60 + now.getMinutes();
  $('plan-strip').innerHTML = (a === b ? '' : a < b ? seg(a, b) : seg(0, b) + seg(a, 1440)) +
    `<div class="now" style="left:${nowMin / 14.4}%" title="jetzt"></div>`;
  $('lg-reserve').textContent = s.CHARGE_RESERVE_W; $('lg-night').textContent = s.NIGHT_MAX_W;
  const inNight = a === b ? false : a < b ? nowMin >= a && nowMin < b : nowMin >= a || nowMin < b;
  const soc = latest?.soc;
  const prot = soc != null && soc <= s.NIGHT_MIN_SOC;
  $('p-prot').textContent = soc == null ? '–' : prot ? 'Aktiv (SOC ≤ Min)' : 'Inaktiv (Normal)';
  $('p-prot').style.color = prot ? 'var(--bad)' : 'var(--inv)';
  $('p-win').textContent = `${inNight ? 'Nacht' : 'Tag'} · ${s.NIGHT_START}–${s.NIGHT_END}`;
  $('p-win').style.color = inNight ? 'var(--bat)' : 'var(--pv-t)';
  // Same estimates as the controller (charging assumes 90 % efficiency).
  const cap = s.BATTERY_CAPACITY_WH;
  const full = soc != null && soc < s.CHARGE_FULL_SOC && s.CHARGE_RESERVE_W > 0 ? (s.CHARGE_FULL_SOC - soc) / 100 * cap / 0.9 / s.CHARGE_RESERVE_W : null;
  const night = soc != null && soc > s.NIGHT_MIN_SOC && s.NIGHT_MAX_W > 0 ? (soc - s.NIGHT_MIN_SOC) / 100 * cap / s.NIGHT_MAX_W : null;
  $('p-full').textContent = full != null ? `~${fx(full, 1)} h` : soc != null && soc >= s.CHARGE_FULL_SOC ? 'voll' : '–';
  $('p-night').textContent = night != null ? `~${fx(night, 1)} h` : '–';
}

/* ---------- read-only .env ---------- */
const LOCK = '<svg class="lock" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-label="maskiert"><rect x="4" y="11" width="16" height="9" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/></svg>';
async function loadEnv() {
  try {
    const groups = await (await fetch('/api/env')).json();
    $('envgrid').innerHTML = groups.map((g) =>
      `<div class="grp"><div class="cap">${esc(g.title)}</div>` + g.items.map((i) => {
        const v = i.value === '' ? (i.source === 'unset' ? 'nicht gesetzt' : '–') : esc(i.value);
        const cls = i.secret && i.value ? ' mask' : i.source === 'unset' || i.value === '' ? ' unset' : '';
        const tag = i.source === 'default' ? '<span class="tag">Standard</span>' : '';
        return `<div class="ev"><span class="k">${esc(i.key)}</span><span class="r">${tag}<span class="v${cls}">${v}</span>${i.secret && i.value ? LOCK : ''}</span></div>`;
      }).join('') + '</div>'
    ).join('');
  } catch (e) { $('envgrid').innerHTML = '<div class="unit">.env konnte nicht geladen werden</div>'; }
}

function onSettingsControl() { if (!dirty) fillForm(ctl.settings); renderPreview(); }
PAGE.control = () => { renderControl(); onSettingsControl(); };
PAGE.live = () => { renderEst(); renderPreview(); };
loadEnv();

"""


_RAW_BODY = """
<main>
<section class="card">
  <div class="head lg">
    <div class="t">
      <svg class="ico" style="color:var(--inv);width:24px;height:24px" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 6h16M4 12h10M4 18h13"/></svg>
      <div><h2>Raw-Log</h2><p>Alles, was das Gerät per HTTP an <span style="color:var(--text)">/collect-service/collect/emsRealDataMinute/realTimeElectricFlow</span> schickt – unverändert, vor der Auswertung</p></div>
    </div>
    <span class="tag" id="raw-state">verbinde …</span>
  </div>

  <div class="rawbar">
    <button class="btn sm" type="button" id="raw-pause">Pause</button>
    <button class="btn sm" type="button" id="raw-clear">Leeren</button>
    <button class="btn sm" type="button" id="raw-dl">JSON herunterladen</button>
    <input type="search" id="raw-filter" placeholder="Log filtern (Text im Body) …" aria-label="Log filtern">
    <span class="stat2" id="raw-stats">–</span>
  </div>

  <div class="rawcols">
    <div class="card sub">
      <div class="head"><h2 style="font-size:16px">Felder</h2><span class="tag" id="fields-count">–</span></div>
      <p class="unit" style="margin-top:-6px">Jedes Feld im letzten Push. <span style="color:var(--inv)">●</span> = wird von der Bridge ausgewertet, sonst „ungenutzt“. Blinkt bei Wertänderung.</p>
      <div class="pane" id="fields"><div class="empty">warte auf den ersten Push …</div></div>
    </div>
    <div class="card sub">
      <div class="head"><h2 style="font-size:16px">Log</h2><span class="tag" id="log-count">–</span></div>
      <p class="unit" style="margin-top:-6px">Neueste oben · Zeile aufklappen für Body, Header und Antwort des Sunshare-Servers.</p>
      <div class="pane" id="log"><div class="empty">warte auf den ersten Push …</div></div>
    </div>
  </div>
</section>
</main>
"""


_RAW_JS = r"""
const USED = new Set(['time', 'pvPow', 'pv1Pow', 'pv2Pow', 'invPow', 'batPow', 'loadPow', 'gridPow', 'offGridPow', 'otherPow', 'soc', 'bhs']);
const MAX_DOM = 200;
let entries = [], byId = new Map(), fields = new Map(), paused = false, pending = [], bufSize = null, rawUp = false, filterText = '';
const hmsms = (t) => hms(t) + '.' + String(Math.floor((t % 1) * 1000)).padStart(3, '0');

function parseBody(e) {
  try { const o = JSON.parse(e.body); return o && typeof o === 'object' && !Array.isArray(o) ? o : null; } catch (err) { return null; }
}
function summary(e, o) {
  if (!o) return e.body.replace(/\s+/g, ' ').slice(0, 160) || '(leer)';
  return Object.entries(o).map(([k, v]) => `${k}=${typeof v === 'object' ? JSON.stringify(v) : v}`).join('  ');
}
function respLabel(e) { return e.resp_status == null ? '…' : String(e.resp_status); }
function respCls(e) { return e.resp_status == null ? '' : e.resp_status < 300 ? ' ok' : ' bad'; }

function ingest(e) {
  e._obj = parseBody(e);
  entries.push(e); byId.set(e.id, e);
  if (entries.length > (bufSize || 500)) byId.delete(entries.shift().id);
  if (!e._obj) return;
  for (const [k, v] of Object.entries(e._obj)) {
    const val = typeof v === 'string' ? v : JSON.stringify(v);
    let f = fields.get(k);
    if (!f) { f = {k, v: val, changes: 0, count: 0, flash: false}; fields.set(k, f); }
    else if (f.v !== val) { f.v = val; f.changes++; f.flash = true; }
    f.count++;
  }
}

function bodyHtml(e) {
  const pretty = e._obj ? JSON.stringify(e._obj, null, 2) : e.body;
  const hdr = Object.entries(e.headers).map(([k, v]) => `${k}: ${v}`).join('\n');
  return `<span class="lbl">Body · ${e.size} B${e.truncated ? ' (gekürzt)' : ''} · ${esc(e.method)} ${esc(e.path)} · von ${esc(e.remote ?? '?')}</span><pre>${esc(pretty)}</pre>` +
    `<span class="lbl">Header</span><pre>${esc(hdr) || '–'}</pre>` +
    `<span class="lbl">Antwort des Sunshare-Servers</span><pre id="rb-${e.id}">${e.resp_status == null ? 'noch offen …' : esc(e.resp_status + '\n' + (e.resp_body ?? ''))}</pre>`;
}
// Only the one-line summary is rendered up front; the (much larger) body opens on demand.
function entryHtml(e) {
  return `<details class="entry" data-id="${e.id}"><summary><span class="et">${hmsms(e.t)}</span>` +
    `<span class="es">${esc(summary(e, e._obj))}</span>` +
    (e._obj ? '' : '<span class="tag bad">kein JSON</span>') +
    `<span class="tag${respCls(e)}" id="rs-${e.id}">${respLabel(e)}</span></summary><div class="eb"></div></details>`;
}
const matches = (e) => !filterText || e.body.toLowerCase().includes(filterText);

function renderFields() {
  if (!fields.size) return;
  $('fields').innerHTML = [...fields.values()].map((f) => {
    const used = USED.has(f.k);
    const tag = used ? '<span style="color:var(--inv)" title="wird von der Bridge ausgewertet">●</span>' : '<span class="tag">ungenutzt</span>';
    const r = `<div class="frow${f.flash ? ' flash' : ''}"><span class="fk">${tag}${esc(f.k)}</span><span class="fv">${esc(f.v)}</span><span class="fc" title="Wertänderungen">${f.changes}×</span></div>`;
    f.flash = false;
    return r;
  }).join('');
  $('fields-count').textContent = fields.size + ' Felder';
}

function renderLogFull() {
  const rows = entries.filter(matches).slice(-MAX_DOM).reverse();
  $('log').innerHTML = rows.length ? rows.map(entryHtml).join('') : `<div class="empty">${entries.length ? 'kein Eintrag passt zum Filter' : 'warte auf den ersten Push …'}</div>`;
}
function renderStats() {
  const n = entries.length;
  let avg = null;
  if (n > 2) { const last = entries.slice(-21); avg = (last[last.length - 1].t - last[0].t) / (last.length - 1); }
  $('raw-stats').textContent = `${n} Einträge${bufSize ? ' (Puffer ' + bufSize + ')' : ''}${avg != null ? ' · Ø ' + fx(avg, 1) + ' s Abstand' : ''}`;
  $('log-count').textContent = filterText ? `${entries.filter(matches).length} / ${n}` : String(n);
  $('raw-state').textContent = paused ? 'pausiert' : rawUp ? 'live' : 'getrennt';
  $('raw-state').className = 'tag ' + (paused ? 'warn' : rawUp ? 'ok' : 'bad');
}

let scheduled = false;
function schedule() {
  if (scheduled) return; scheduled = true;
  requestAnimationFrame(() => { scheduled = false; renderFields(); renderStats(); });
}

function onAdd(e) {
  ingest(e);
  const log = $('log');
  if (matches(e)) {
    if (log.querySelector('.empty')) log.innerHTML = '';
    log.insertAdjacentHTML('afterbegin', entryHtml(e));
    while (log.children.length > MAX_DOM) log.lastElementChild.remove();
  }
  schedule();
}
function onResp(m) {
  const e = byId.get(m.id); if (!e) return;
  e.resp_status = m.resp_status; e.resp_body = m.resp_body;
  const rs = $('rs-' + m.id), rb = $('rb-' + m.id);
  if (rs) { rs.textContent = respLabel(e); rs.className = 'tag' + respCls(e); }
  if (rb) rb.textContent = e.resp_status + '\n' + (e.resp_body ?? '');
}
function reset() { entries = []; byId = new Map(); fields = new Map(); $('fields').innerHTML = '<div class="empty">warte auf den ersten Push …</div>'; $('fields-count').textContent = '–'; }

function handleLive(m) {
  if (m.type === 'add') onAdd(m.entry);
  else if (m.type === 'resp') onResp(m);
  else if (m.type === 'clear') { reset(); renderLogFull(); renderStats(); }
}

// (Re)connect: fetch the buffer over a normal, compressed request, then replay what the
// stream delivered meanwhile (entries the buffer already contains are skipped).
let syncing = false, buffered = [];
async function resync(m) {
  syncing = true; buffered = []; bufSize = m.size;
  let snap = [];
  try { snap = await (await fetch('/api/raw')).json(); } catch (err) {}
  reset(); snap.forEach(ingest);
  const lastId = snap.length ? snap[snap.length - 1].id : 0;
  renderFields(); renderLogFull(); renderStats();
  syncing = false;
  for (const ev of buffered) if (ev.type !== 'add' || ev.entry.id > lastId) handleLive(ev);
  buffered = [];
}
function handle(m) {
  if (m.type === 'hello') resync(m);
  else if (syncing) buffered.push(m);
  else handleLive(m);
}

$('raw-pause').onclick = () => {
  paused = !paused;
  $('raw-pause').textContent = paused ? 'Fortsetzen' : 'Pause';
  if (!paused) { pending.forEach(handle); pending = []; }
  renderStats();
};
$('raw-clear').onclick = () => fetch('/api/raw/clear', {method: 'POST'});
$('raw-filter').oninput = (ev) => { filterText = ev.target.value.trim().toLowerCase(); renderLogFull(); renderStats(); };
$('raw-dl').onclick = () => {
  const data = entries.map(({_obj, ...e}) => e);
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], {type: 'application/json'}));
  a.download = 'sunshare-raw-' + new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-') + '.json';
  document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 1000);
};

$('log').addEventListener('toggle', (ev) => {
  const d = ev.target;
  if (!d.open || d.dataset.filled) return;
  const e = byId.get(+d.dataset.id);
  if (e) { d.querySelector('.eb').innerHTML = bodyHtml(e); d.dataset.filled = '1'; }
}, true);

PAGE.pollLatest = true;
managedStream('/api/raw/stream', () => { rawUp = true; renderStats(); }, () => { rawUp = false; renderStats(); },
              (ev) => { const m = JSON.parse(ev.data); if (paused && m.type !== 'hello') pending.push(m); else handle(m); });
"""


def _page(title: str, active: str, body: str, js: str) -> str:
    return (
        '<!doctype html>\n<html lang="de">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{title}</title>\n<style>{_CSS}</style>\n</head>\n<body>\n"
        f"{_topbar(active)}{body}\n<script>{_COMMON_JS}{js}\nstart();\n</script>\n</body>\n</html>\n"
    )


INDEX_HTML = _page("Sunshare Bridge", "tele", _TELE_BODY, _TELE_JS)
FLOW_HTML = _page("Sunshare Bridge · Leistungsfluss", "flow", _FLOW_BODY, _FLOW_JS)
CONTROL_HTML = _page("Sunshare Bridge · Regler & Parameter", "control", _CONTROL_BODY, _CONTROL_JS)
RAW_HTML = _page("Sunshare Bridge · Raw", "raw", _RAW_BODY, _RAW_JS)
