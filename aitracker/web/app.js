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
let selEntry=null;   // last list row seen for the selected session — pin it so a poll can't drop it
function renderSide(){
  const now=Date.now()/1000;
  const sl=$("slist"), sc=sl?sl.scrollTop:0;   // preserve scroll: a background poll must not yank the list to the top
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
    if(sl)sl.scrollTop=sc;
    return;
  }
  const liveN=sessions.filter(s=>now-s.mtime<LIVE).length;
  const lc=$("livecount");
  lc.textContent=liveOnly?`${liveN} live ✕`:`${liveN} live`;
  lc.title=liveOnly?"Showing live only — click to show all":"Click to show live sessions only";
  lc.classList.toggle("on",liveOnly);
  const found=sessions.find(s=>s.id===cur); if(found)selEntry=found;
  let shown=liveOnly?sessions.filter(s=>now-s.mtime<LIVE):sessions;
  // never let the selected session fall off (top-N cap or live filter) — pin it so the selection persists
  if(cur && !shown.some(s=>s.id===cur) && selEntry && selEntry.id===cur) shown=[selEntry,...shown];
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
  if(sl)sl.scrollTop=sc;
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
function toggleSound(){soundOn=!soundOn;localStorage.setItem("soundOff",soundOn?"0":"1");setBell();if(soundOn){beep();primeNotify();}}
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
// Browsers only allow Notification.requestPermission() and audio to start from a real
// user gesture — prime both on the first interaction so a completion can alert you even
// when this tab is backgrounded (where the WebAudio beep is suspended).
function primeNotify(){
  try{audioCtx=audioCtx||new (window.AudioContext||window.webkitAudioContext)();if(audioCtx.state==="suspended")audioCtx.resume();}catch(e){}
  if(soundOn && "Notification" in window && Notification.permission==="default"){try{Notification.requestPermission();}catch(e){}}
}
addEventListener("pointerdown",primeNotify,{once:true});
function toast(msg,sub){
  const el=document.createElement("div");
  el.className="toast";
  el.innerHTML=`<span class=tk>✓</span><div><div class=tt>${esc(msg)}</div>${sub?`<div class=tsub>${esc(sub)}</div>`:""}</div>`;
  el.onclick=()=>el.remove();
  $("toasts").appendChild(el);
  requestAnimationFrame(()=>el.classList.add("show"));
  setTimeout(()=>{el.classList.remove("show");setTimeout(()=>el.remove(),300);},7000);
}
function notifyDone(title,sub){
  toast(title,sub);                                   // in-page banner (seen when you're on the tab)
  if(soundOn)beep();                                  // WebAudio — reliable only while the tab is focused
  // an OS notification reaches you in another tab or app, where the beep + toast can't
  if(document.hidden && soundOn && "Notification" in window && Notification.permission==="granted"){
    try{const n=new Notification(title,{body:sub||""});n.onclick=()=>{window.focus();n.close();};}catch(e){}
  }
}
function checkCompletions(d){
  const items=[...(d.agents_bg||[]).map(a=>({id:"a:"+a.id,name:a.task||a.id,kind:"agent",run:a.running})),
               ...(d.shells||[]).map(s=>({id:"s:"+s.id,name:s.desc||s.cmd,kind:"shell",run:s.running}))];
  const running=new Set(items.filter(x=>x.run).map(x=>x.id));
  // reset baseline (no notify) on session switch or first poll
  if(notifSession!==cur||notifRunning===null){notifSession=cur;notifRunning=running;return;}
  for(const x of items){
    if(!x.run && notifRunning.has(x.id)){
      notifyDone(x.kind==="shell"?"Background shell finished":"Background agent finished", (x.name||"").slice(0,90));
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

  // now banner: live → what it's working on (blue, blinking cursor); idle → the last thing
  // it completed (green, no cursor). Click opens the newest narration entry in the
  // live-following modal — so an active session is tracked as it works.
  $("nowbanner").style.display=ov.now?"flex":"none";
  $("nowbanner").classList.toggle("done",!live);
  const nowClean=(ov.now||"").replace(/^(?:▶|⚙|✓)\s+/,"").replace(/^Idle — last said:\s*/,"");
  $("nowlbl").textContent=live?"Now working on":"Completed last task";
  $("nowtext").innerHTML=(live?"▶ ":"✓ ")+md(nowClean)+(live?'<span class=cursor>▍</span>':"");

  // narration — unbounded, server-paginated. The poll ships only the newest page
  // (d.narrative) + the full count (d.narrative_total); we keep an accumulator so
  // scrolled-in older entries survive, and prepend whatever's genuinely new.
  const fresh=d.narrative||[], total=d.narrative_total!=null?d.narrative_total:fresh.length;
  if(narrState.id!==cur){ narrState={id:cur,items:fresh.slice(),total}; _win.narr=30; }
  else {
    const delta=total-narrState.total;     // new entries since last poll (<= page size at 2s cadence)
    if(delta>0) narrState.items=fresh.slice(0,delta).concat(narrState.items);
    else if(!narrState.items.length) narrState.items=fresh.slice();
    narrState.total=total;
  }
  curNarr=narrState.items;
  const moreNarr=async()=>{
    if(narrState.items.length>=narrState.total) return null;
    const r=await fetch(`/api/narration?id=${encodeURIComponent(cur)}&offset=${narrState.items.length}&limit=60`);
    if(!r.ok) return null;
    const j=await r.json();
    narrState.items=narrState.items.concat(j.items||[]);
    narrState.total=j.total!=null?j.total:narrState.total;
    curNarr=narrState.items;
    return {items:narrState.items,total:narrState.total};
  };
  winList("narr", narrState.items, (x,i)=>
    `<div class=narr onclick="openMsg(${i})" title="Read full message"><span class=t>${x.t?ago(d.now-Date.parse(x.t)/1000):""}</span><span class=x>${md(x.text)}</span><span class=chev>›</span></div>`,
    "no narration yet", {total:narrState.total,more:moreNarr});

  // pull requests — clickable links to the PRs this session generated (server sends created-only)
  const prs=d.prs||[];
  $("prpanel").style.display=prs.length?"":"none";
  $("prc").textContent=prs.length||"";
  winList("prs", prs, (p,i)=>
    `<div class="item prrow"><a class=prlink href="${esc(p.url)}" target=_blank rel=noopener title="${esc(p.url)}">`+
    `<span class="kind new">created</span> `+
    `<b>${esc((p.repo?p.repo+' ':'')+'#'+p.num)}</b><span class=prurl>${esc(p.url)}</span>`+
    `<span class=prtime>${p.t?ago(d.now-Date.parse(p.t)/1000):""}</span><span class=chev>open ›</span></a></div>`,
    "no pull requests created in this session");

  // decisions / open questions the session asked the user for (Claude AskUserQuestion, Auggie ask-user)
  const dec=d.decisions||[], nOpen=dec.filter(x=>x.open).length;
  $("decpanel").style.display=dec.length?"":"none";
  $("decc").textContent=dec.length?(nOpen?nOpen+" open · "+dec.length:dec.length):"";
  $("dec").innerHTML=dec.length?dec.map(x=>{
    const qs=(x.questions||[]).map(q=>
      (q.header?`<span class=dechd>${esc(q.header)}</span>`:"")+
      `<div class=decq>${md(q.q||"")}</div>`+
      (q.options&&q.options.length?`<div class=decopts>${q.options.map(o=>`<span class=decopt>${esc(o)}</span>`).join("")}</div>`:"")
    ).join("");
    const foot=x.open
      ? `<div class="decans open">⏳ awaiting your answer — decide in the session</div>`
      : `<div class=decans><span class=deck>✓ decided</span> ${md(x.answer||"")}</div>`;
    return `<div class="decitem${x.open?' isopen':''}">${qs}${foot}`+
           `<div class=dectime>${x.t?ago(d.now-Date.parse(x.t)/1000):""}</div></div>`;
  }).join(""):"<div class=empty>no questions asked</div>";

  // todos
  const td=d.todos||[];
  const order={completed:0,in_progress:1,pending:2};
  const sorted=[...td].sort((a,b)=>(order[a.status]??3)-(order[b.status]??3));
  const TICON={completed:"✓",in_progress:"▶",pending:"○"};
  $("todoc").textContent=td.length?c.done+"/"+td.length:"";
  curTodos=sorted;
  winList("todos", sorted, (t,i)=>
    `<div class="todo t-${t.status} clk" onclick="openTodo(${i})"><span class=ic>${TICON[t.status]||"○"}</span><span class=tx>${md(t.content)}</span></div>`, "no todos in this session");

  // requests (markdown + click to read full)
  curReqs=[...(d.requests||[])].reverse();
  $("reqc").textContent=curReqs.length||"";
  winList("reqs", curReqs, (r,i)=>
    `<div class="item clk" onclick="openReq(${i})"><div class="mdtext clamp3">${md(r.text)}</div><div class="muted mono" style=font-size:11px;margin-top:3px>${r.t?ago(d.now-Date.parse(r.t)/1000):""}</div></div>`, "—");

  // files
  const fs=d.files||[];
  curFiles=fs;
  $("filec").textContent=fs.length||"";
  winList("files", fs, (f,i)=>
    `<div class="item filerow" onclick="openDiff(${i})" title="View diff"><div class=fpath><span class="kind ${f.created?'new':''}">${f.created?'created':'edited'}</span>${f.agent?' <span class=agenttag title="edited by a background agent">🤖 agent</span>':''} <b>${esc(base(f.path))}</b><span class=chev>diff ›</span></div>`+
    `<div class="muted mono" style=font-size:11px;margin-top:3px>${esc(f.path.replace("/"+base(f.path),""))} · ${f.ops}× · ${ago(d.now-Date.parse(f.last)/1000)}</div></div>`, "no files written yet");

  // commands (click to see output)
  curCmds=d.commands||[];
  $("cmdc").textContent=curCmds.length||"";
  winList("cmds", curCmds, (x,i)=>
    `<div class="item clk" onclick="openCmd(${i})"><span class="${x.ok?'ok':'bad'}">${x.ok?'✓':'✗'}</span> <span class=muted>${KICON[x.kind]||'$'}</span> `+
    `<span class="cmd mono">${esc(x.cmd)}</span> <span class=chev style=float:right;color:#5b6573>output ›</span></div>`, "—");

  syncModal();   // keep an open narration/request modal live with this poll
}
let curFiles=[], curDiffFile=null, curDiffOps=[], diffMode="diff", diffExpand=[], curDiffText=null, diffAllExpanded=false;
const isMd=p=>/\.(md|markdown|mdx)$/i.test(p||"");
async function openDiff(i){
  const f=curFiles[i]; if(!f||!cur)return;
  _setNav(openDiff,i,curFiles.length);
  curDiffFile=f; curDiffOps=[]; diffExpand=[]; curDiffText=null; diffAllExpanded=false;
  diffMode=isMd(f.path)?"md":"diff";   // markdown files render by default
  $("diffname").textContent=base(f.path);
  $("diffpath").textContent=f.path;
  updateMdToggle();
  $("diffbody").innerHTML="<div class=empty>loading…</div>";
  $("diffmodal").style.display="flex";
  try{const d=await(await fetch(`/api/diff?id=${encodeURIComponent(cur)}&file=${encodeURIComponent(f.path)}`)).json();
      curDiffOps=(d.ops||[]).reverse();}   // newest edit first
  catch(e){curDiffOps=[];}
  try{const r=await(await fetch("/api/file?path="+encodeURIComponent(f.path))).json();
      if(!r.error) curDiffText=r.content||"";}catch(e){}   // full file → GitHub-style context expansion
  renderDiffView();
}
function updateMdToggle(){
  const btn=$("diffmd");
  if(btn){ btn.style.display=isMd(curDiffFile&&curDiffFile.path)?"":"none";
           btn.textContent=diffMode==="md"?"◧ Diff":"◧ Rendered"; }
  const ab=$("diffall");   // expand-all only makes sense in diff mode with edits to expand
  if(ab){ ab.style.display=(diffMode==="diff"&&curDiffOps.length)?"":"none";
          ab.textContent=diffAllExpanded?"⇕ Collapse":"⇕ Expand all"; }
}
function toggleDiffMd(){ diffMode=diffMode==="md"?"diff":"md"; updateMdToggle(); renderDiffView(); }
function toggleDiffAll(){
  diffAllExpanded=!diffAllExpanded;
  if(diffAllExpanded){
    const N=(curDiffText!=null?curDiffText:"").split("\n").length;   // enough to clamp to the whole file
    diffExpand=curDiffOps.map(()=>({up:N,down:N}));
  } else diffExpand=[];
  renderDiffView();
}
async function renderDiffView(){
  updateMdToggle();   // sync the header buttons now that ops/mode are known
  if(diffMode==="md"){ await renderMdView(); return; }
  const now=Date.now()/1000;
  const fileLines=curDiffText!=null?curDiffText.split("\n"):[];
  $("diffbody").innerHTML=curDiffOps.length?curDiffOps.map((op,idx)=>
    `<div class=diffop><div class=diffhd><span class="kind ${op.kind==='created'?'new':''}">${op.kind}</span>`+
    `${op.ts?`<span>${ago(now-Date.parse(op.ts)/1000)}</span>`:""}</div>`+
    `<div class=diff>${renderOpDiff(op,idx,fileLines)}</div></div>`).join(""):
    "<div class=empty>no recorded edits for this file</div>";
}
// The recorded diff is just the edit's snippet; anchor its after-text uniquely in the
// real file so up/down can reveal the true surrounding lines (GitHub-style). A superseded
// or non-unique edit can't be anchored — then we show the snippet alone, no expander.
function _afterLines(op){
  let a=(op.diff||"").split("\n")
    .filter(l=>!/^(@@|\+\+\+|---)/.test(l) && l[0]!=="-")
    .map(l=> (l[0]==="+"||l[0]===" ") ? l.slice(1) : l);
  while(a.length && a[a.length-1]==="") a.pop();
  return a;
}
function _anchorIdx(a,f){
  if(!a.length || a.length>f.length) return -1;
  let hit=-1;
  for(let i=0;i+a.length<=f.length;i++){
    let ok=true; for(let j=0;j<a.length;j++){ if(f[i+j]!==a[j]){ok=false;break;} }
    if(ok){ if(hit>=0) return -1; hit=i; }   // ambiguous → don't guess a location
  }
  return hit;
}
function _expBar(idx,dir,n){
  return `<div class=diffexp onclick="diffExpandMore(${idx},'${dir}')" title="show more of the file">`+
         `${dir==='up'?'↑':'↓'} ${n} more line${n===1?'':'s'} ${dir==='up'?'above':'below'}</div>`;
}
function renderOpDiff(op,idx,fileLines){
  const hunk=renderDiff(op.diff);
  const after=_afterLines(op), at=_anchorIdx(after,fileLines);
  if(at<0) return hunk;                              // no reliable anchor → snippet only
  const st=diffExpand[idx]||{up:0,down:0}, end=at+after.length;
  const upStart=Math.max(0,at-st.up), downEnd=Math.min(fileLines.length,end+st.down);
  const ctx=(a,b)=>fileLines.slice(a,b).map(l=>`<span class="dl dctx">${esc(l)||" "}</span>`).join("");
  return (upStart>0?_expBar(idx,'up',upStart):"")+ctx(upStart,at)+hunk+
         ctx(end,downEnd)+(downEnd<fileLines.length?_expBar(idx,'down',fileLines.length-downEnd):"");
}
function diffExpandMore(idx,dir){
  const e=diffExpand[idx]||(diffExpand[idx]={up:0,down:0});
  e[dir]+=20; renderDiffView();
}
async function renderMdView(){
  const content=(curDiffText!=null?curDiffText:"")||reconstructAfter(curDiffOps);
  $("diffbody").innerHTML=content
    ? `<div class="msgbody mdmode" style=overflow:visible>${mdBlock(content)}</div>`
    : "<div class=empty>could not read the file to render</div>";
}
function reconstructAfter(ops){ return ops.length?_afterLines(ops[0]).join("\n"):""; }
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
let narrState={id:null,items:[],total:0};   // accumulator for server-paginated narration
// ---- modal navigation: prev/next across the list that opened the dialog ----
let curModal=null;
function _setNav(open,i,n,opts){
  opts=opts||{};
  curModal={open:open,i:i,n:n,fromEnd:n-1-i,len:opts.len||(()=>n),live:!!opts.live};
  const pos=n>1?(i+1)+" / "+n:"";
  const a=$("msgnav"), b=$("diffnav");
  if(a)a.textContent=pos; if(b)b.textContent=pos;
}
function navModal(d){ if(!curModal)return; const j=curModal.i+d; if(j>=0&&j<curModal.n) curModal.open(j); }
// Keep an open text modal in sync with the 2s poll — re-render the entry being read
// with fresh data (content, "time ago", the N/total counter). Pinned by distance-
// from-end so prepended entries don't yank it, EXCEPT when they were on the newest
// (i=0) where it follows the latest, like a chat sticking to the top. Called from
// render(); only the in-memory text modal opts in (fetch-based ones would re-fetch).
function syncModal(){
  if(!curModal||!curModal.live)return;
  if($("msgmodal").style.display!=="flex")return;
  const newN=curModal.len();
  if(!newN){closeMsg();return;}                    // the list emptied out
  const newI=curModal.i===0?0:Math.max(0,Math.min(newN-1,newN-1-curModal.fromEnd));
  const body=$("msgbody"), st=body?body.scrollTop:0;
  curModal.open(newI);
  if(body)body.scrollTop=st;                        // don't jump the reader mid-entry
}
const tago=t=>t?ago(Date.now()/1000-Date.parse(t)/1000):"";
// generic readable modal: title + optional time + markdown body
function openText(title,when,text){
  $("msgtitle").textContent=title;
  $("msgwhen").textContent=when||"";
  $("msgbody").className="msgbody mdmode";
  $("msgbody").innerHTML=mdBlock(text)||"<span class=muted>(empty)</span>";
  $("msgmodal").style.display="flex";
}
function openMsg(i){const n=curNarr[i]; if(!n)return; _setNav(openMsg,i,curNarr.length,{len:()=>curNarr.length,live:true}); openText("Narration",tago(n.t),n.text);}
// the Now banner → jump to the panel that reflects the CURRENT activity (server says which via
// now_kind), flash it so you see WHERE it's happening, AND open that item's live dialog.
function openNow(){
  const k=curOv.now_kind||"narration";
  const el=$({agents:"bgpanel", shells:"shpanel", todo:"card_todos", narration:"card_narr"}[k]||"card_narr");
  if(el && el.style.display!=="none"){
    el.scrollIntoView({behavior:"smooth", block:"center"});
    el.classList.remove("flash"); void el.offsetWidth; el.classList.add("flash");   // re-trigger the flash
    setTimeout(()=>el.classList.remove("flash"), 1500);
  }
  // open the dialog of the item that's actually active (running agent/shell, in-progress todo, newest narration)
  if(k==="agents" && curAgents.length){ const i=curAgents.findIndex(a=>a.running); openAgent(i<0?0:i); }
  else if(k==="shells" && curShells.length){ const i=curShells.findIndex(s=>s.running); openShell(i<0?0:i); }
  else if(k==="todo"){ const i=curTodos.findIndex(t=>t.status==="in_progress"); if(i>=0) openTodo(i); }
  else if(curNarr && curNarr.length){ openMsg(0); }
}
function openReq(i){const r=curReqs[i]; if(!r)return; _setNav(openReq,i,curReqs.length,{len:()=>curReqs.length,live:true}); openText("Request",tago(r.t),r.text);}
async function openCmd(i){
  const x=curCmds[i]; if(!x||!cur)return;
  _setNav(openCmd,i,curCmds.length);
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
  _setNav(openTodo,i,curTodos.length);
  openText("Task",t.status,"**"+(t.content||"")+"**"+(t.desc?"\n\n"+t.desc:""));
}
async function openShell(i){
  const s=curShells[i]; if(!s||!cur)return;
  _setNav(openShell,i,curShells.length);
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
  _setNav(openAgent,i,curAgents.length);
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

document.addEventListener("keydown",e=>{
  const open=$("msgmodal").style.display==="flex"||$("diffmodal").style.display==="flex";
  if(!open)return;
  if(e.key==="ArrowLeft"){navModal(-1);e.preventDefault();}
  else if(e.key==="ArrowRight"){navModal(1);e.preventDefault();}
});

// ---- generic windowed list: render a growing window, reveal +30 on scroll,
// survive the 2s poll (persisted window + preserved scroll position). Used by
// every list panel so "scroll to load older" works app-wide.
// opts (optional): {total, more}. total = full count incl. entries not yet loaded
// (server-paginated panels); more() = async ()=>{items,total}|null fetching the
// next batch. Omit both for fully in-memory panels.
let _win={};
// Advance a windowed panel by one batch: reveal the next 30 already-loaded items,
// or fetch the next server page when the local window is exhausted. Both triggers
// (scroll + IntersectionObserver) call this — keep the load path in one place.
function _winAdvance(elId){
  const el=$(elId); if(!el||!el._items||!el._items.length) return;
  const n=_win[elId]||30;
  if(n<el._items.length){ _win[elId]=n+30; winList(elId, el._items, el._render, el._empty, el._opts); }
  else if(el._opts && el._opts.more && !el._loading){   // window exhausted: fetch older from the server
    el._loading=true;
    el._opts.more().then(res=>{ el._loading=false;
      if(res){ _win[elId]=(_win[elId]||30)+30; el._opts.total=res.total; winList(elId, res.items, el._render, el._empty, el._opts); }
    }, ()=>{ el._loading=false; });
  }
}
function winList(elId, items, render, empty, opts){
  opts=opts||{};
  const el=$(elId); if(!el)return;
  el._render=render; el._empty=empty; el._opts=opts;
  if(!items||!items.length){ el.innerHTML="<div class=empty>"+empty+"</div>"; _win[elId]=30; el._items=[]; return; }
  el._items=items;
  const total=opts.total!=null?opts.total:items.length;
  const shown=Math.min(_win[elId]||30, items.length);
  const top=el.scrollTop;
  let html=items.slice(0,shown).map(render).join("");
  const older=total-shown;                 // local window + server-side not-yet-loaded
  if(older>0) html+=`<div class=loadmore>↓ ${older} older — scroll to load</div>`;
  el.innerHTML=html;
  el.scrollTop=top;
  // Load the next batch as the "↓ older" sentinel nears the bottom of THIS box.
  // Two triggers, for reliability: a scroll handler (fires on every scroll) and an
  // IntersectionObserver with a prefetch margin (visibility-driven — catches the
  // momentum / sub-pixel / trackpad cases the scroll math can miss).
  if(!el._wired){ el._wired=true;
    el.addEventListener("scroll",()=>{ if(el.scrollTop+el.clientHeight>=el.scrollHeight-64) _winAdvance(elId); });
    if(window.IntersectionObserver)
      el._io=new IntersectionObserver(es=>{ if(es.some(e=>e.isIntersecting)) _winAdvance(elId); },
                                      {root:el, rootMargin:"0px 0px 240px 0px"});
  }
  if(el._io){ el._io.disconnect();             // last render's sentinel is gone; watch the new one
    const sentinel=el.querySelector(".loadmore");
    if(sentinel) el._io.observe(sentinel);
  }
}
