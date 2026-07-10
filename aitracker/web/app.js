let cur=localStorage.getItem("sid")||"", timer=null;
const $=id=>document.getElementById(id);
const esc=s=>(s||"").replace(/[&<>]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;"}[c]));
// tiny inline markdown for narration/requests: escape first, then `code`,
// **bold**, *italic*, [text](url). No `_` italics — identifiers use underscores.
function md(s){
  let h=esc(s);
  h=h.replace(/`([^`]+)`/g,(m,c)=>`<code>${c}</code>`);
  h=h.replace(/\*\*([^*]+)\*\*/g,"<strong>$1</strong>");
  h=h.replace(/(^|[^*])\*(?!\s)([^*\n]+?)\*/g,"$1<em>$2</em>");
  h=h.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,'<a href="$2" target=_blank rel=noopener>$1</a>');
  return h;
}
// block-level markdown for the full-text modal: headers, tables, lists, code fences
function mdBlock(s){
  const L=(s||"").replace(/\r/g,"").split("\n"), out=[]; let i=0;
  const sep=l=>/^[\s|:-]+$/.test(l)&&l.includes("-")&&l.includes("|");
  const cells=l=>l.trim().replace(/^\|/,"").replace(/\|$/,"").split("|").map(c=>c.trim());
  while(i<L.length){
    const l=L[i];
    if(/^\s*```/.test(l)){ i++; const b=[]; while(i<L.length&&!/^\s*```/.test(L[i])){b.push(L[i]);i++;} i++;
      out.push(`<pre class=mdpre><code>${esc(b.join("\n"))}</code></pre>`); continue; }
    const hm=l.match(/^(#{1,6})\s+(.*)$/);
    if(hm){ const lv=Math.min(hm[1].length,4)+1; out.push(`<h${lv} class=mdh>${md(hm[2])}</h${lv}>`); i++; continue; }
    if(l.includes("|")&&i+1<L.length&&sep(L[i+1])){
      const hd=cells(l); i+=2; const rs=[];
      while(i<L.length&&L[i].includes("|")&&L[i].trim()){ rs.push(cells(L[i])); i++; }
      out.push("<table class=mdt><thead><tr>"+hd.map(c=>`<th>${md(c)}</th>`).join("")+"</tr></thead><tbody>"+
        rs.map(r=>"<tr>"+r.map(c=>`<td>${md(c)}</td>`).join("")+"</tr>").join("")+"</tbody></table>"); continue; }
    if(/^\s*[-*+]\s+/.test(l)){ const it=[];
      while(i<L.length&&/^\s*[-*+]\s+/.test(L[i])){ it.push(`<li>${md(L[i].replace(/^\s*[-*+]\s+/,""))}</li>`); i++; }
      out.push("<ul class=mdul>"+it.join("")+"</ul>"); continue; }
    if(/^\s*\d+\.\s+/.test(l)){ const it=[];
      while(i<L.length&&/^\s*\d+\.\s+/.test(L[i])){ it.push(`<li>${md(L[i].replace(/^\s*\d+\.\s+/,""))}</li>`); i++; }
      out.push("<ol class=mdul>"+it.join("")+"</ol>"); continue; }
    if(!l.trim()){ i++; continue; }
    const p=[];
    while(i<L.length&&L[i].trim()&&!/^#{1,6}\s/.test(L[i])&&!/^\s*[-*+]\s+/.test(L[i])&&!/^\s*\d+\.\s+/.test(L[i])&&!/^\s*```/.test(L[i])&&!(L[i].includes("|")&&i+1<L.length&&sep(L[i+1]))){ p.push(L[i]); i++; }
    out.push(`<p class=mdp>${md(p.join(" "))}</p>`);
  }
  return out.join("");
}
function ago(sec){sec=Math.max(0,sec|0);if(sec<60)return sec+"s ago";if(sec<3600)return(sec/60|0)+"m ago";if(sec<86400)return(sec/3600|0)+"h ago";return(sec/86400|0)+"d ago"}
function base(p){return (p||"").split("/").pop()}
const SRC={"claude-desktop":"🖥 Desktop","cli":"⌨ CLI","claude-vscode":"⧉ VS Code","auggie":"◆ Auggie"};
const srcLabel=v=>SRC[v]||v||"";
const CIRC=2*Math.PI*51; // progress-ring circumference

let sessions=[], searchResults=null, liveOnly=false;
const LIVE=300; // seconds since last activity a session stays "live" (5 min)
function hl(text,q){
  const e=esc(text); if(!q)return e;
  const re=new RegExp("("+q.replace(/[.*+?^${}()|[\]\\]/g,"\\$&")+")","ig");
  return e.replace(re,"<b>$1</b>");
}
function renderSide(){
  const now=Date.now()/1000;
  if(searchResults!==null){       // search mode: show matches instead of the full list
    const q=$("q").value.trim();
    $("livecount").textContent=`${searchResults.length} match${searchResults.length==1?"":"es"}`;
    $("slist").innerHTML=searchResults.length?searchResults.map(s=>{
      const live=now-s.mtime<LIVE;
      return `<div class="sitem ${s.id===cur?'active':''}" onclick="pick('${s.id}')" title="${esc(s.title||'')}">`+
        `<div class=srow1><span class="dot ${live?'live':''}"></span><span class=nm>${esc(s.title||s.project||s.id.slice(0,8))}</span>`+
        `<span class=ren onclick="renameSession(event,'${s.id}')" title="Rename">✎</span></div>`+
        `<div class=smeta><span class=proj>${esc(s.project)}</span>${s.inQuery?' · <span class=smatch>your query</span>':''} · <span>${s.matches}×</span></div>`+
        (s.snippet?`<div class=ssnip>${hl(s.snippet,q)}</div>`:"")+
        `</div>`;
    }).join(""):`<div class=empty>no sessions match “${esc(q)}”</div>`;
    return;
  }
  const liveN=sessions.filter(s=>now-s.mtime<LIVE).length;
  const lc=$("livecount");
  lc.textContent=liveOnly?`${liveN} live ✕`:`${liveN} live`;
  lc.title=liveOnly?"Showing live only — click to show all":"Click to show live sessions only";
  lc.classList.toggle("on",liveOnly);
  const shown=liveOnly?sessions.filter(s=>now-s.mtime<LIVE):sessions;
  $("slist").innerHTML=shown.length?shown.map(s=>{
    const live=now-s.mtime<LIVE;
    const label=s.title||s.project||s.id.slice(0,8);
    const bits=[`<span class=proj>${s.title?esc(s.project):s.id.slice(0,8)}</span>`];
    if(s.source)bits.push(srcLabel(s.source));
    bits.push(ago(now-s.mtime));
    return `<div class="sitem ${s.id===cur?'active':''}" onclick="pick('${s.id}')" title="${esc((s.prompt||s.title||'(no prompt)')+'\n'+(s.cwd||''))}">`+
      `<div class=srow1><span class="dot ${live?'live':''}"></span><span class=nm>${esc(label)}</span>`+
      `<span class=ren onclick="renameSession(event,'${s.id}')" title="Rename this session">✎</span></div>`+
      `<div class=smeta>${bits.join(" · ")}</div></div>`;
  }).join(""):`<div class=empty>${liveOnly?"no live sessions":"no sessions"}</div>`;
}
function toggleLiveOnly(){liveOnly=!liveOnly;renderSide();}
async function loadSide(){
  try{sessions=await(await fetch("/api/list")).json();}catch(e){return}
  renderSide();
}
function pick(id){$("sid").value=id;track();renderSide();}
async function doSearch(){
  const q=$("q").value.trim();
  if(!q){clearSearch();return}
  $("qclear").style.display="";
  $("slist").innerHTML="<div class=empty>searching…</div>";
  try{searchResults=await(await fetch("/api/search?q="+encodeURIComponent(q))).json()}
  catch(e){searchResults=[]}
  renderSide();
}
function clearSearch(){searchResults=null;$("q").value="";$("qclear").style.display="none";renderSide();}
async function renameSession(e,id){
  e.stopPropagation();
  const s=sessions.find(x=>x.id===id)||{};
  const t=prompt("Rename session (leave blank for the auto title):", s.title||"");
  if(t===null)return;
  await fetch("/api/title",{method:"POST",headers:{"Content-Type":"application/json"},
    body:JSON.stringify({session:id,title:t})});
  await loadSide();
  if(id===cur)poll();  // refresh the main header title too
}
async function start(){
  await loadSide();
  // fall back to the newest session if nothing is stored or the stored id is stale
  if((!cur||!sessions.some(s=>s.id===cur))&&sessions[0])cur=sessions[0].id;
  if(cur){$("sid").value=cur;track();renderSide();}
  setInterval(loadSide,5000);
}
function track(){
  cur=$("sid").value.trim();localStorage.setItem("sid",cur);
  if(timer)clearInterval(timer);
  if(!cur)return;
  poll();timer=setInterval(poll,2000);
}
let lastData=null;
// ---- completion notifications: agent/shell running -> done ----
let soundOn=localStorage.getItem("soundOff")!=="1";
let notifSession=null, notifRunning=null, audioCtx=null;
function setBell(){const b=$("bell");if(b){b.textContent=soundOn?"🔔":"🔕";b.title="Completion sound: "+(soundOn?"on":"muted");}}
function toggleSound(){soundOn=!soundOn;localStorage.setItem("soundOff",soundOn?"0":"1");setBell();if(soundOn)beep();}
function beep(){
  try{
    audioCtx=audioCtx||new (window.AudioContext||window.webkitAudioContext)();
    if(audioCtx.state==="suspended")audioCtx.resume();
    const t=audioCtx.currentTime;
    [784,1175].forEach((f,i)=>{                     // two-tone "ding"
      const o=audioCtx.createOscillator(),g=audioCtx.createGain();
      o.type="sine";o.frequency.value=f;o.connect(g);g.connect(audioCtx.destination);
      const s=t+i*0.13;
      g.gain.setValueAtTime(0,s);g.gain.linearRampToValueAtTime(0.16,s+0.02);
      g.gain.exponentialRampToValueAtTime(0.001,s+0.22);
      o.start(s);o.stop(s+0.24);
    });
  }catch(e){}
}
function toast(msg,sub){
  const el=document.createElement("div");
  el.className="toast";
  el.innerHTML=`<span class=tk>✓</span><div><div class=tt>${esc(msg)}</div>${sub?`<div class=tsub>${esc(sub)}</div>`:""}</div>`;
  el.onclick=()=>el.remove();
  $("toasts").appendChild(el);
  requestAnimationFrame(()=>el.classList.add("show"));
  setTimeout(()=>{el.classList.remove("show");setTimeout(()=>el.remove(),300);},7000);
}
function checkCompletions(d){
  const items=[...(d.agents_bg||[]).map(a=>({id:"a:"+a.id,name:a.task||a.id,kind:"agent",run:a.running})),
               ...(d.shells||[]).map(s=>({id:"s:"+s.id,name:s.desc||s.cmd,kind:"shell",run:s.running}))];
  const running=new Set(items.filter(x=>x.run).map(x=>x.id));
  // reset baseline (no notify) on session switch or first poll
  if(notifSession!==cur||notifRunning===null){notifSession=cur;notifRunning=running;return;}
  for(const x of items){
    if(!x.run && notifRunning.has(x.id)){
      toast(x.kind==="shell"?"Background shell finished":"Background agent finished", (x.name||"").slice(0,90));
      if(soundOn)beep();
    }
  }
  notifRunning=running;
}
async function poll(){
  if(!cur)return;
  let d;try{d=await(await fetch("/api/session?id="+encodeURIComponent(cur))).json()}catch(e){return}
  if(d.error){$("hmeta").innerHTML=`<span class=dot></span> ${esc(d.error)}: ${esc(cur)}`;return}
  lastData=d;render(d);loadFlags();checkCompletions(d);
}
const KICON={commit:"⎇",test:"✓",install:"⬇",build:"🔨",git:"⎇",cmd:"$"};
function render(d){
  const idle=d.now-d.mtime, live=idle<LIVE;
  const m=d.meta||{}, c=d.counts||{};
  const title=m.title||m.customTitle||m.aiTitle||cur.slice(0,8);
  const src=srcLabel(m.entrypoint);
  if(title)document.title=title+" · tracker";

  // progress ring
  const pct=c.todos?Math.round(c.done/c.todos*100):0;
  const ring=$("ring");
  ring.setAttribute("stroke-dasharray",CIRC.toFixed(1));
  ring.setAttribute("stroke-dashoffset",(CIRC*(1-pct/100)).toFixed(1));
  $("ringpct").textContent=pct;
  $("ringsub").textContent=`${c.done||0} of ${c.todos||0} tasks`;

  // title + active badge
  $("htitle").textContent=title;
  $("activebadge").style.display=live?"inline-flex":"none";
  if(!live){
    $("activebadge").style.display="inline-flex";
    $("activebadge").innerHTML='<span class=dot></span>idle '+ago(idle);
    $("activebadge").style.color="#8b949e";$("activebadge").style.background="#10141c";$("activebadge").style.borderColor="#2c333f";
  }else{
    $("activebadge").innerHTML='<span class="dot live"></span>active';
    $("activebadge").style.color="#29d398";$("activebadge").style.background="#0f2a20";$("activebadge").style.borderColor="#1c4634";
  }

  // meta line
  const meta=[];
  if(m.cwd)meta.push("📁 "+esc(base(m.cwd)));
  if(m.gitBranch)meta.push("⎇ "+esc(m.gitBranch));
  if(src)meta.push("⌨ "+esc(src));
  meta.push(`${(d.tokens.in/1000|0)}k in / ${(d.tokens.out/1000|0)}k out`);
  if(m.version)meta.push("v"+esc(m.version));
  $("hmeta").innerHTML=meta.map(x=>`<span>${x}</span>`).join("");

  const chip=(n,v,cls,tgt)=>v?`<span class="chip ${cls||''} ${tgt?'clk':''}"${tgt?` onclick="flashTo('${tgt}')"`:''}><span class=lbl>${n}</span><b>${v}</b></span>`:"";
  $("chips").innerHTML=
    chip("✓ done",`${c.done}/${c.todos}`,"good","card_todos")+chip("＋ created",c.created,"blue","card_files")+chip("✎ edited",c.edited,"","card_files")+
    chip("👁 read",c.read,"","card_files")+chip("⎇ commits",c.commits,"","card_cmds")+chip("tests",c.tests,"","card_cmds")+
    chip("✗ failed",c.tests_failed,"bad","card_cmds")+chip("⚠ errors",c.errors,"bad","card_cmds")+
    chip("agents",c.agents,"","bgpanel")+chip("searches",c.searches);

  // background agents (click to read full narration)
  // background agents — running shown; finished tucked behind a disclosure
  const bg=d.agents_bg||[];
  curAgents=bg;
  $("bgpanel").style.display=bg.length?"flex":"none";
  if(bg.length){
    const runN=bg.filter(a=>a.running).length;
    $("bgc").textContent=runN?`${runN} running`:"all finished";
    const card=(a,i)=>
      `<div class="agent clk" onclick="openAgent(${i})"><div class=top><span class="dot ${a.running?'amber':''}"></span><span class=nm>${esc(a.task||a.id)}</span>`+
      (a.wf?` <span class=tag>${esc(a.wf.slice(0,12))}</span>`:"")+`<span class=chev>›</span></div>`+
      `<div class=last>${esc(a.last||"")}</div>`+
      `<div class=ft><span>${a.tools} tools</span><span>·</span><span style=color:${a.running?'#f5b443':'#6b7585'}>${a.running?'running':'done'}</span>`+
      `${a.ts?"<span>·</span><span>"+ago(d.now-Date.parse(a.ts)/1000)+"</span>":""}</div></div>`;
    const run=[],done=[];
    bg.forEach((a,i)=>(a.running?run:done).push(card(a,i)));
    let html=run.length?run.join(""):"<div class=empty>No agents running right now.</div>";
    if(done.length){
      html+=`<div class=disclosure onclick=toggleAgentsDone()>${showAgentsDone?"▾ Hide":"▸ Show"} ${done.length} finished</div>`;
      if(showAgentsDone)html+=done.join("");
    }
    $("bg").innerHTML=html;
  }

  // background shells — same pattern (click a card to read full output)
  const shl=d.shells||[];
  curShells=shl;
  $("shpanel").style.display=shl.length?"flex":"none";
  if(shl.length){
    const shRun=shl.filter(s=>s.running).length;
    $("shc").textContent=shRun?`${shRun} running`:"all finished";
    const card=(s,i)=>
      `<div class="agent clk" onclick="openShell(${i})"><div class=top><span class="dot ${s.running?'amber':''}"></span><span class=nm>${esc(s.desc||s.cmd)}</span><span class=chev>›</span></div>`+
      `<div class="last mono" style=font-size:11px>${esc(s.last||s.cmd)}</div>`+
      `<div class=ft><span>${esc(s.id)}</span><span>·</span><span style=color:${s.running?'#f5b443':'#6b7585'}>${s.running?'running':'done'}</span>`+
      `${s.ts?"<span>·</span><span>"+ago(d.now-Date.parse(s.ts)/1000)+"</span>":""}</div></div>`;
    const run=[],done=[];
    shl.forEach((s,i)=>(s.running?run:done).push(card(s,i)));
    let html=run.length?run.join(""):"<div class=empty>No shells running right now.</div>";
    if(done.length){
      html+=`<div class=disclosure onclick=toggleShellsDone()>${showShellsDone?"▾ Hide":"▸ Show"} ${done.length} finished</div>`;
      if(showShellsDone)html+=done.join("");
    }
    $("sh").innerHTML=html;
  }

  $("srcnote").style.display=d.note?"block":"none";
  $("srcnote").textContent=d.note||"";

  // summary (markdown + click to read full)
  const ov=d.overview||{};
  curOv=ov;
  $("ov_goal").innerHTML=md(ov.goal||"—");
  $("ov_now").innerHTML="▶ "+md(ov.now||(live?"working…":"idle"));
  $("ov_sofar").innerHTML=md(ov.sofar||"—");
  const ocm=ov.commits||[];
  $("ov_crow").style.display=ocm.length?"flex":"none";
  $("ov_commits").textContent=ocm.join("  ·  ");

  // now banner (markdown + click to read full)
  $("nowbanner").style.display=ov.now?"flex":"none";
  $("nowtext").innerHTML="▶ "+md(ov.now||"")+'<span class=cursor>▍</span>';

  // narration
  const nr=d.narrative||[];
  curNarr=nr;
  $("narr").innerHTML=nr.length?nr.map((x,i)=>
    `<div class=narr onclick="openMsg(${i})" title="Read full message"><span class=t>${x.t?ago(d.now-Date.parse(x.t)/1000):""}</span><span class=x>${md(x.text)}</span><span class=chev>›</span></div>`).join(""):"<div class=empty>no narration yet</div>";

  // todos
  const td=d.todos||[];
  const order={completed:0,in_progress:1,pending:2};
  const sorted=[...td].sort((a,b)=>(order[a.status]??3)-(order[b.status]??3));
  const TICON={completed:"✓",in_progress:"▶",pending:"○"};
  $("todoc").textContent=td.length?c.done+"/"+td.length:"";
  curTodos=sorted;
  $("todos").innerHTML=td.length?sorted.map((t,i)=>
    `<div class="todo t-${t.status} clk" onclick="openTodo(${i})"><span class=ic>${TICON[t.status]||"○"}</span><span class=tx>${md(t.content)}</span></div>`).join(""):"<div class=empty>no todos in this session</div>";

  // requests (markdown + click to read full)
  curReqs=[...(d.requests||[])].reverse();
  $("reqc").textContent=curReqs.length||"";
  $("reqs").innerHTML=curReqs.length?curReqs.map((r,i)=>
    `<div class="item clk" onclick="openReq(${i})"><div class="mdtext clamp3">${md(r.text)}</div><div class="muted mono" style=font-size:11px;margin-top:3px>${r.t?ago(d.now-Date.parse(r.t)/1000):""}</div></div>`).join(""):"<div class=empty>—</div>";

  // files
  const fs=d.files||[];
  curFiles=fs;
  $("filec").textContent=fs.length||"";
  $("files").innerHTML=fs.length?fs.map((f,i)=>
    `<div class="item filerow" onclick="openDiff(${i})" title="View diff"><div class=fpath><span class="kind ${f.created?'new':''}">${f.created?'created':'edited'}</span> <b>${esc(base(f.path))}</b><span class=chev>diff ›</span></div>`+
    `<div class="muted mono" style=font-size:11px;margin-top:3px>${esc(f.path.replace("/"+base(f.path),""))} · ${f.ops}× · ${ago(d.now-Date.parse(f.last)/1000)}</div></div>`).join(""):"<div class=empty>no files written yet</div>";

  // commands (click to see output)
  curCmds=d.commands||[];
  $("cmdc").textContent=curCmds.length||"";
  $("cmds").innerHTML=curCmds.length?curCmds.map((x,i)=>
    `<div class="item clk" onclick="openCmd(${i})"><span class="${x.ok?'ok':'bad'}">${x.ok?'✓':'✗'}</span> <span class=muted>${KICON[x.kind]||'$'}</span> `+
    `<span class="cmd mono">${esc(x.cmd)}</span> <span class=chev style=float:right;color:#5b6573>output ›</span></div>`).join(""):"<div class=empty>—</div>";
}
let curFiles=[], curDiffFile=null, curDiffOps=[], diffMode="diff";
const isMd=p=>/\.(md|markdown|mdx)$/i.test(p||"");
async function openDiff(i){
  const f=curFiles[i]; if(!f||!cur)return;
  curDiffFile=f; curDiffOps=[];
  diffMode=isMd(f.path)?"md":"diff";   // markdown files render by default
  $("diffname").textContent=base(f.path);
  $("diffpath").textContent=f.path;
  updateMdToggle();
  $("diffbody").innerHTML="<div class=empty>loading…</div>";
  $("diffmodal").style.display="flex";
  try{const d=await(await fetch(`/api/diff?id=${encodeURIComponent(cur)}&file=${encodeURIComponent(f.path)}`)).json();
      curDiffOps=(d.ops||[]).reverse();}   // newest edit first
  catch(e){curDiffOps=[];}
  renderDiffView();
}
function updateMdToggle(){
  const btn=$("diffmd"); if(!btn)return;
  btn.style.display=isMd(curDiffFile&&curDiffFile.path)?"":"none";
  btn.textContent=diffMode==="md"?"◧ Diff":"◧ Rendered";
}
function toggleDiffMd(){ diffMode=diffMode==="md"?"diff":"md"; updateMdToggle(); renderDiffView(); }
async function renderDiffView(){
  if(diffMode==="md"){ await renderMdView(); return; }
  const now=Date.now()/1000;
  $("diffbody").innerHTML=curDiffOps.length?curDiffOps.map(op=>
    `<div class=diffop><div class=diffhd><span class="kind ${op.kind==='created'?'new':''}">${op.kind}</span>`+
    `${op.ts?`<span>${ago(now-Date.parse(op.ts)/1000)}</span>`:""}</div>`+
    `<div class=diff>${renderDiff(op.diff)}</div></div>`).join(""):
    "<div class=empty>no recorded edits for this file</div>";
}
async function renderMdView(){
  $("diffbody").innerHTML="<div class=empty>rendering…</div>";
  let content="";
  try{const r=await(await fetch("/api/file?path="+encodeURIComponent(curDiffFile.path))).json();
      if(!r.error) content=r.content||"";}catch(e){}
  if(!content) content=reconstructAfter(curDiffOps);   // fallback: rebuild from the diff
  $("diffbody").innerHTML=content
    ? `<div class="msgbody mdmode" style=overflow:visible>${mdBlock(content)}</div>`
    : "<div class=empty>could not read the file to render</div>";
}
function reconstructAfter(ops){
  if(!ops.length)return "";
  return (ops[0].diff||"").split("\n")
    .filter(l=>!/^(@@|\+\+\+|---)/.test(l) && l[0]!=="-")
    .map(l=> (l[0]==="+"||l[0]===" ") ? l.slice(1) : l).join("\n");
}
function renderDiff(t){
  return (t||"").split("\n").map(l=>{
    let cls="dl";
    if(l.startsWith("+++")||l.startsWith("---"))cls="dl dh";
    else if(l.startsWith("@@"))cls="dl dat";
    else if(l[0]==="+")cls="dl dadd";
    else if(l[0]==="-")cls="dl ddel";
    return `<span class="${cls}">${esc(l)||" "}</span>`;
  }).join("");
}
function closeDiff(){$("diffmodal").style.display="none";}
let curNarr=[], curCmds=[], curReqs=[], curOv={};
const tago=t=>t?ago(Date.now()/1000-Date.parse(t)/1000):"";
// generic readable modal: title + optional time + markdown body
function openText(title,when,text){
  $("msgtitle").textContent=title;
  $("msgwhen").textContent=when||"";
  $("msgbody").className="msgbody mdmode";
  $("msgbody").innerHTML=mdBlock(text)||"<span class=muted>(empty)</span>";
  $("msgmodal").style.display="flex";
}
function openMsg(i){const n=curNarr[i]; if(n)openText("Narration",tago(n.t),n.text);}
function openReq(i){const r=curReqs[i]; if(r)openText("Request",tago(r.t),r.text);}
async function openCmd(i){
  const x=curCmds[i]; if(!x||!cur)return;
  $("msgtitle").textContent="Command";
  $("msgwhen").textContent=tago(x.t);
  $("msgbody").className="msgbody cmdmode";
  $("msgbody").innerHTML=`<div class=cmdcode><span class="${x.ok?'ok':'bad'}">${x.ok?'✓':'✗'}</span> ${esc(x.cmd)}</div><div class=empty>loading output…</div>`;
  $("msgmodal").style.display="flex";
  let d;
  try{d=await(await fetch(`/api/output?id=${encodeURIComponent(cur)}&cmd=${encodeURIComponent(x.id)}`)).json()}
  catch(e){d={}}
  $("msgbody").innerHTML=`<div class=cmdcode><span class="${x.ok?'ok':'bad'}">${x.ok?'✓':'✗'}</span> ${esc(d.cmd||x.cmd)}</div>`+
    (d.out?`<pre class=cmdout>${esc(d.out)}</pre>`:"<div class=empty>no output captured</div>");
}
let curShells=[], curAgents=[], curTodos=[];
let showAgentsDone=false, showShellsDone=false;
function toggleAgentsDone(){showAgentsDone=!showAgentsDone; if(lastData)render(lastData);}
function toggleShellsDone(){showShellsDone=!showShellsDone; if(lastData)render(lastData);}
function openTodo(i){
  const t=curTodos[i]; if(!t)return;
  openText("Task",t.status,"**"+(t.content||"")+"**"+(t.desc?"\n\n"+t.desc:""));
}
async function openShell(i){
  const s=curShells[i]; if(!s||!cur)return;
  $("msgtitle").textContent="Shell · "+s.id;
  $("msgwhen").textContent=(s.running?"running":"done")+(s.ts?" · "+tago(s.ts):"");
  $("msgbody").className="msgbody cmdmode";
  $("msgbody").innerHTML=`<div class=cmdcode>${esc(s.cmd)}</div><div class=empty>loading output…</div>`;
  $("msgmodal").style.display="flex";
  let d;try{d=await(await fetch(`/api/shell?id=${encodeURIComponent(cur)}&shell=${encodeURIComponent(s.id)}`)).json()}catch(e){d={}}
  $("msgbody").innerHTML=`<div class=cmdcode>${esc(d.cmd||s.cmd)}</div>`+
    (d.out?`<pre class=cmdout>${esc(d.out)}</pre>`:"<div class=empty>no output yet</div>");
}
async function openAgent(i){
  const a=curAgents[i]; if(!a||!cur)return;
  $("msgtitle").textContent="Agent";
  $("msgwhen").textContent=(a.running?"running":"done")+(a.ts?" · "+tago(a.ts):"");
  $("msgbody").className="msgbody";
  $("msgbody").innerHTML="<div class=empty>loading…</div>";
  $("msgmodal").style.display="flex";
  let d;try{d=await(await fetch(`/api/agent?id=${encodeURIComponent(cur)}&agent=${encodeURIComponent(a.aid||a.id)}`)).json()}catch(e){d={}}
  $("msgbody").innerHTML=(d.task?`<div class=cmdcode>${esc(d.task)}</div>`:"")+
    `<div class="muted mono" style=margin-bottom:10px>${d.tools||0} tool calls · ${d.running?'running':'done'}</div>`+
    (d.narration?md(d.narration):"<div class=empty>no narration recorded</div>");
}
function closeMsg(){$("msgmodal").style.display="none";}
function copyModal(bodyId,btn){
  const el=$(bodyId); if(!el)return;
  const text=el.innerText||el.textContent||"";
  const done=()=>{if(btn){const o=btn.textContent;btn.textContent="✓ Copied";setTimeout(()=>btn.textContent=o,1200);}};
  if(navigator.clipboard&&navigator.clipboard.writeText){
    navigator.clipboard.writeText(text).then(done).catch(()=>fallbackCopy(el,done));
  }else{fallbackCopy(el,done);}
}
function fallbackCopy(el,done){
  const r=document.createRange();r.selectNodeContents(el);
  const s=getSelection();s.removeAllRanges();s.addRange(r);
  try{document.execCommand("copy");done();}catch(e){}
  s.removeAllRanges();
}
function popOut(titleId,bodyId){
  const body=$(bodyId); if(!body)return;
  const title=($(titleId)&&$(titleId).textContent)||"Tracker";
  const head=[...document.querySelectorAll("style, link[rel=stylesheet]")].map(e=>e.outerHTML).join("");
  const w=window.open("","_blank");
  if(!w){alert("Popup blocked — allow popups for this page to open in a new tab.");return;}
  w.document.write(
    `<!doctype html><html><head><meta charset=utf-8><title>${esc(title)}</title>${head}`+
    `</head>`+
    `<body><div class=pw><h1>${esc(title)}</h1><div class="${body.className}" style="overflow:visible;max-height:none">${body.innerHTML}</div></div></body></html>`);
  w.document.close();
}
function flashTo(id){
  const el=$(id); if(!el||el.style.display==="none")return;
  el.scrollIntoView({behavior:"smooth",block:"start"});
  el.classList.remove("flash"); void el.offsetWidth; el.classList.add("flash");
  setTimeout(()=>el.classList.remove("flash"),1400);
}
document.addEventListener("keydown",e=>{if(e.key==="Escape"){closeDiff();closeMsg();}});
let flags=[];
async function loadFlags(){try{flags=await(await fetch("/api/flags")).json()}catch(e){return}renderFlags()}
function renderFlags(){
  const mine=flags.filter(f=>f.session===cur).sort((a,b)=>(a.resolved-b.resolved)||b.ts-a.ts);
  const open=mine.filter(f=>!f.resolved).length;
  $("flagc").textContent=mine.length?`${open} open / ${mine.length}`:"";
  const now=Date.now()/1000;
  $("flags").innerHTML=mine.length?mine.map(f=>
    `<div class="flag ${f.resolved?'done':'open'}"><div class=note>${f.resolved?'✓ ':'🚩 '}${esc(f.note)}</div>`+
    (f.context?`<div class=ctx>while: ${esc(f.context)}</div>`:"")+
    `<div class=ft><span>${ago(now-f.ts)}</span>`+
    `<span class="link blue" onclick="resolveFlag(${f.id})">${f.resolved?'reopen':'✓ resolve'}</span>`+
    `<span class="link grey" onclick="delFlag(${f.id})">delete</span></div></div>`).join(""):
    "<div class=empty>no flags yet</div>";
}
async function addFlag(){
  if(!cur){alert("Pick a session first");return}
  const note=prompt("🚩 Flag an issue or gap to resolve:");
  if(!note||!note.trim())return;
  const s=sessions.find(x=>x.id===cur)||{};
  await fetch("/api/flags",{method:"POST",headers:{"Content-Type":"application/json"},
    body:JSON.stringify({session:cur,project:s.project||"",note,context:($("nowtext").textContent||"").replace(/[▶▍]/g,"").trim()})});
  loadFlags();
}
async function flagAction(path,id){
  await fetch(path,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({id})});
  loadFlags();
}
function resolveFlag(id){flagAction("/api/flags/resolve",id)}
function delFlag(id){if(confirm("Delete this flag?"))flagAction("/api/flags/delete",id)}
function toggleRaw(){const r=$("raw");
  if(r.style.display==="none"){r.textContent=lastData?JSON.stringify(lastData,null,2):"no data yet";r.style.display="block"}
  else r.style.display="none";
}
$("q").addEventListener("keydown",e=>{if(e.key==="Enter")doSearch();if(e.key==="Escape")clearSearch();});
setBell();
start();
