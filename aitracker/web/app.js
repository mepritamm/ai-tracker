let cur=localStorage.getItem("sid")||"", timer=null;
// ponytail: one sprite + one helper; every emoji call site becomes ico(<name>).
function ico(name, cls){ return '<svg class="ico'+(cls?' '+cls:'')+'" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><use href="#i-'+name+'"/></svg>' }
window.ico = ico;
// Dark (default) / Light theme — the class is set pre-paint by the <head> script; sync button + meta here.
function setTheme(t){document.documentElement.classList.toggle("light",t==="light");try{localStorage.theme=t}catch(e){}var b=document.getElementById("themebtn");if(b)b.innerHTML=t==="light"?ico("moon"):ico("sun");var m=document.getElementById("themecolor");if(m)m.content=t==="light"?"#f4efe3":"#0c0f15";document.dispatchEvent(new CustomEvent("themechange",{detail:{theme:t}}));}
function toggleTheme(){setTheme(document.documentElement.classList.contains("light")?"dark":"light");}
setTheme(document.documentElement.classList.contains("light")?"light":"dark");
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
    const fm=l.match(/^\s*```\s*([A-Za-z0-9_+-]*)/);
    if(fm){ i++; const b=[]; while(i<L.length&&!/^\s*```/.test(L[i])){b.push(L[i]);i++;} i++;
      const src=b.join("\n");
      if(/^mermaid$/i.test(fm[1])){ const g=mermaidSvg(src);
        // Render the hand-rolled fallback SYNCHRONOUSLY first (so the page is correct
        // immediately, even offline, before the vendored asset loads) — g is the SVG when
        // this diagram's family is one of the 8 covered above, or null for a family only
        // real mermaid.js knows (gantt/mindmap/timeline/gitGraph/...). Either way it's
        // wrapped in a `.mmd-slot` carrying the raw source, so renderMermaid() (below)
        // can upgrade it in place once mermaid.js is available — see that function's own
        // comment for why the fallback stays rather than getting deleted.
        const b64=_mmdEncodeSrc(src);
        const fallback=g ? `<div class=mmd>${g}</div>`
          // unsupported diagram type — still readable, but LABEL it so the reader can see
          // it was an intended diagram (not a plain code fence) whose renderer isn't baked in yet
          : (()=>{ const t=(src.match(/^\s*(?:%%.*\n)*\s*([A-Za-z][A-Za-z0-9_-]*)/)||[,""])[1]||"unknown";
              return `<div class="cblock mmdfall"><div class=mmdftag>${ico("diagram")} mermaid: ${esc(t)}</div><button class=codecopy onclick="copyCode(this)" title="Copy this block">${ico('copy')} Copy</button><pre class=mdpre><code>${esc(src)}</code></pre></div>`; })();
        out.push(`<div class="mmd-slot" data-mmd-src="${b64}">${fallback}</div>`); continue; }
      out.push(`<div class=cblock><button class=codecopy onclick="copyCode(this)" title="Copy this block">${ico('copy')} Copy</button><pre class=mdpre><code>${esc(src)}</code></pre></div>`); continue; }
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
// ---- Mermaid → inline SVG, hand-rolled. No mermaid.js, no CDN: the whole app is
// one zero-dependency file and `make bundle` inlines web/ verbatim, so a 3 MB vendored
// library is off the table. Covers the diagram families that actually show up in
// agent-generated markdown, so a `stateDiagram-v2` or `classDiagram` no longer lands
// as raw code beside a rendered `flowchart`:
//   • flowchart|graph           (node shapes, edge labels, classDef colours — _mermaidSvgFlow)
//   • sequenceDiagram           (participants, messages, notes, alt/opt/loop/par — _mermaidSeqSvg)
//   • stateDiagram(-v2)         (states, [*] pseudostates, labelled transitions   — _mermaidStateSvg)
//   • classDiagram              (classes with members, typed relationships        — _mermaidClassSvg)
//   • erDiagram                 (entities with attributes, cardinality on edges   — _mermaidErSvg)
//   • journey                   (sections with tasks + happiness scores           — _mermaidJourneySvg)
//   • pie                       (labelled slices with legend + percentages        — _mermaidPieSvg)
//   • quadrantChart             (2×2 axes with plotted points                     — _mermaidQuadrantSvg)
// mermaidSvg() dispatches by the first non-blank keyword; state/class/er/journey are
// translated to flowchart syntax and reuse _mermaidSvgFlow so their labelled edges and
// layered layout come for free. Anything else (gantt, mindmap, timeline, gitGraph, …)
// returns null and mdBlock renders the fence as code with an icon + "mermaid: <type>" tag —
// still readable, but visibly an intended diagram whose renderer isn't baked in yet.
// ponytail: layered layout, straight bezier edges — no crossing minimisation.
const MMDSH={"[[":"rect","((":"circle","([":"stadium","[":"rect","(":"round","{":"diamond",">":"rect"};
const MMDW=13, MMDCW=6.9, MMDLH=17, MMDPX=14, MMDPY=9, MMDGX=26, MMDGY=56, MMDMAX=44;
function _mmdLines(s){
  const out=[];
  (s||"").replace(/<br\s*\/?>/gi,"\n").replace(/<\/?[a-z][^>]*>/gi,"").replace(/^\s*["'`]|["'`]\s*$/g,"")
   .split("\n").forEach(raw=>{
     let t=raw.trim(); if(!t){return;}
     while(t.length>MMDMAX){                       // soft-wrap on a word boundary
       let c=t.lastIndexOf(" ",MMDMAX); if(c<MMDMAX*0.5)c=MMDMAX;
       out.push(t.slice(0,c).trim()); t=t.slice(c).trim();
     }
     out.push(t);
   });
  return out.length?out:[""];
}
function _mmdStyle(s){
  const o={};
  (s||"").split(",").forEach(kv=>{ const j=kv.indexOf(":"); if(j>0)o[kv.slice(0,j).trim().toLowerCase()]=kv.slice(j+1).trim(); });
  return o;
}
function _mmdNode(tok,nodes,order){
  tok=(tok||"").trim(); if(!tok)return null;
  let cls=null; const cm=tok.match(/:::([A-Za-z0-9_-]+)\s*$/);
  if(cm){ cls=cm[1]; tok=tok.slice(0,cm.index).trim(); }
  const m=tok.match(/^([A-Za-z0-9_.-]+)\s*(\[\[|\(\(|\(\[|\[|\(|\{|>)([\s\S]*)$/);
  let id=tok, shape="rect", label=null;
  if(m){ id=m[1]; shape=MMDSH[m[2]]||"rect"; label=m[3].replace(/(\]\]|\)\)|\]\)|\]|\)|\})\s*$/,""); }
  else { id=tok.split(/\s/)[0]; }
  if(!/^[A-Za-z0-9_.-]+$/.test(id))return null;
  let n=nodes[id];
  if(!n){ n=nodes[id]={id:id,shape:shape,lines:_mmdLines(label==null?id:label),cls:cls}; order.push(id); }
  else { if(label!=null){ n.lines=_mmdLines(label); n.shape=shape; } if(cls)n.cls=cls; }
  return n;
}
const MMDARR=/^([\s\S]*?)\s*(-\.->|-\.-|={2,}>|={2,}|-{2,}>|--[xo]|-{2,})\s*(?:\|([^|]*)\|\s*)?/;
// Dispatch by diagram type — the shared seam every markdown surface calls through mdBlock.
// The order matters only where prefixes could overlap; keyword tests are anchored so they don't.
function mermaidSvg(src){ try{
  const s=(src||"").replace(/^\s*(?:%%.*\n)*/,"").trimStart();
  if(/^sequenceDiagram\b/i.test(s))          return _mermaidSeqSvg(src);
  if(/^stateDiagram(?:-v2)?\b/i.test(s))     return _mermaidStateSvg(src);
  if(/^classDiagram(?:-v2)?\b/i.test(s))     return _mermaidClassSvg(src);
  if(/^erDiagram\b/i.test(s))                return _mermaidErSvg(src);
  if(/^(?:journey|userJourney)\b/i.test(s))  return _mermaidJourneySvg(src);
  if(/^pie\b/i.test(s))                      return _mermaidPieSvg(src);
  if(/^quadrantChart\b/i.test(s))            return _mermaidQuadrantSvg(src);
  return _mermaidSvgFlow(src);
}catch(e){ return null; } }
function _mermaidSvgFlow(src){
  const nodes={}, order=[], edges=[], classes={}, assign={};
  let dir="TD", started=false;
  for(const rawline of (src||"").replace(/\r/g,"").split("\n")){
    let l=rawline.replace(/%%.*$/,"").trim();
    if(!l)continue;
    if(!started){
      const h=l.match(/^(?:flowchart|graph)(?:\s+(TD|TB|LR|RL|BT))?\b/i);
      if(!h)return null;                                   // not a flowchart → caller falls back to code
      dir=(h[1]||"TD").toUpperCase(); started=true;
      l=l.slice(h[0].length).trim(); if(!l)continue;
    }
    if(/^(subgraph\b|end\b|direction\b|linkStyle\b|style\b|click\b|accTitle\b|accDescr\b)/i.test(l))continue;
    const cd=l.match(/^classDef\s+(\S+)\s+(.*)$/i);
    if(cd){ cd[1].split(",").forEach(n=>{classes[n.trim()]=_mmdStyle(cd[2])}); continue; }
    const ca=l.match(/^class\s+([A-Za-z0-9_.,\s-]+?)\s+(\S+)\s*$/i);
    if(ca){ ca[1].split(",").forEach(n=>{assign[n.trim()]=ca[2]}); continue; }
    l=l.replace(/\s-{2,}\s+([^>|]+?)\s+-{2,}>/g," -->|$1|").replace(/\s-\.\s*([^>|]+?)\s*\.->/g," -.->|$1|");
    const seg=[], lab=[], sty=[]; let rest=l, m, guard=0;
    while((m=rest.match(MMDARR))&&guard++<32){ seg.push(m[1]); sty.push(m[2]); lab.push(m[3]||""); rest=rest.slice(m[0].length); }
    if(!seg.length){ _mmdNode(l,nodes,order); continue; }   // a bare node declaration
    seg.push(rest);
    for(let k=0;k<seg.length-1;k++){
      const a=_mmdNode(seg[k],nodes,order), b=_mmdNode(seg[k+1],nodes,order);
      if(a&&b)edges.push({a:a.id,b:b.id,label:lab[k].trim(),dash:sty[k].includes("."),thick:sty[k].includes("="),head:/[>xo]$/.test(sty[k])});
    }
  }
  const ids=order.filter(id=>nodes[id]);
  if(!started||!ids.length)return null;
  Object.keys(assign).forEach(id=>{ if(nodes[id])nodes[id].cls=assign[id]; });

  ids.forEach(id=>{ const n=nodes[id];
    n.w=Math.max(56,Math.max.apply(null,n.lines.map(t=>t.length))*MMDCW+MMDPX*2);
    n.h=n.lines.length*MMDLH+MMDPY*2;
    if(n.shape==="diamond"){ n.w+=26; n.h+=12; }
    if(n.shape==="circle"){ n.w=n.h=Math.max(n.w,n.h); }
  });
  const rank={}; ids.forEach(id=>rank[id]=0);
  for(let pass=0;pass<=ids.length;pass++){ let ch=false;
    edges.forEach(e=>{ if(rank[e.b]<rank[e.a]+1&&rank[e.a]+1<=ids.length){ rank[e.b]=rank[e.a]+1; ch=true; } });
    if(!ch)break;
  }
  const rows={}; ids.forEach(id=>{ (rows[rank[id]]=rows[rank[id]]||[]).push(id); });
  const keys=Object.keys(rows).map(Number).sort((a,b)=>a-b);
  const vert=(dir==="TD"||dir==="TB"||dir==="BT");
  // the gap after a rank has to hold that rank's edge labels: stacked (TD) or side by side (LR)
  const lab={}; edges.forEach(e=>{ if(e.label)(lab[rank[e.a]]=lab[rank[e.a]]||[]).push(e); });
  const gapOf=k=>{ const n=(lab[k]||[]).length; if(!n)return MMDGY;
    return vert?Math.max(MMDGY,26+22*n):Math.max(MMDGY,Math.max.apply(null,lab[k].map(e=>e.label.length*6+10))+22); };
  const gapAt={};
  let W=0,H=0,at=0;
  keys.forEach(k=>{
    const row=rows[k], gap=gapOf(k);
    if(vert){
      const rh=Math.max.apply(null,row.map(id=>nodes[id].h));
      let x=0; row.forEach(id=>{ const n=nodes[id]; n.x=x; n.y=at+(rh-n.h)/2; x+=n.w+MMDGX; });
      W=Math.max(W,x-MMDGX); gapAt[k]=at+rh; at+=rh+gap;
    }else{
      const rw=Math.max.apply(null,row.map(id=>nodes[id].w));
      let y=0; row.forEach(id=>{ const n=nodes[id]; n.y=y; n.x=at+(rw-n.w)/2; y+=n.h+MMDGX; });
      H=Math.max(H,y-MMDGX); gapAt[k]=at+rw; at+=rw+gap;
    }
    if(k===keys[keys.length-1]){ if(vert)H=at-gap; else W=at-gap; }
  });
  keys.forEach(k=>{ const row=rows[k];                       // centre each rank on the long axis
    if(vert){ const rw=row.reduce((s,id)=>s+nodes[id].w,0)+MMDGX*(row.length-1); row.forEach(id=>nodes[id].x+=(W-rw)/2); }
    else { const rh=row.reduce((s,id)=>s+nodes[id].h,0)+MMDGX*(row.length-1); row.forEach(id=>nodes[id].y+=(H-rh)/2); }
  });
  const P=18, sw=W+P*2, sh=H+P*2, g=[], labels=[];
  const seen={};
  edges.forEach(e=>{
    const a=nodes[e.a], b=nodes[e.b]; if(!a||!b)return;
    let x1,y1,x2,y2,c1,c2;
    if(vert){ x1=a.x+a.w/2; y1=a.y+a.h; x2=b.x+b.w/2; y2=b.y; c1=`${x1},${y1+Math.abs(y2-y1)/2}`; c2=`${x2},${y2-Math.abs(y2-y1)/2}`; }
    else { x1=a.x+a.w; y1=a.y+a.h/2; x2=b.x; y2=b.y+b.h/2; c1=`${x1+Math.abs(x2-x1)/2},${y1}`; c2=`${x2-Math.abs(x2-x1)/2},${y2}`; }
    g.push(`<path class="mmde${e.dash?" dash":""}${e.thick?" thick":""}" d="M${x1},${y1} C${c1} ${c2} ${x2},${y2}"${e.head?' marker-end="url(#mmdarrow)"':""}/>`);
    if(!e.label)return;
    // park the label in its rank's gap — one slot per label, so a fan-out's labels
    // ladder down the gap instead of piling onto each other or onto the target node
    const k=rank[e.a], j=(seen[k]=(seen[k]||0)+1)-1;
    let x,y;
    if(vert){ y=gapAt[k]+13+22*j; const t=y2===y1?0.5:Math.max(0,Math.min(1,(y-y1)/(y2-y1))); x=x1+(x2-x1)*t; }
    else { x=gapAt[k]+(gapOf(k)-2)/2; const t=x2===x1?0.5:Math.max(0,Math.min(1,(x-x1)/(x2-x1))); y=y1+(y2-y1)*t; }
    labels.push({x:x, y:y, w:e.label.length*6+10, text:e.label});
  });
  ids.forEach(id=>{ const n=nodes[id], st=classes[n.cls]||{};
    // inline style, not a fill= attribute: the .mmdn stylesheet rule would win over a
    // presentation attribute and silently drop every classDef colour
    const box=(st.fill?"fill:"+esc(st.fill)+";":"")+(st.stroke?"stroke:"+esc(st.stroke)+";":"");
    const bs=box?` style="${box}"`:"", tf=st.color?` style="fill:${esc(st.color)}"`:"";
    if(n.shape==="diamond"){
      const cx=n.x+n.w/2, cy=n.y+n.h/2;
      g.push(`<polygon class=mmdn points="${cx},${n.y} ${n.x+n.w},${cy} ${cx},${n.y+n.h} ${n.x},${cy}"${bs}/>`);
    } else {
      const rx=n.shape==="stadium"||n.shape==="circle"?n.h/2:(n.shape==="round"?12:6);
      g.push(`<rect class=mmdn x="${n.x}" y="${n.y}" width="${n.w}" height="${n.h}" rx="${rx}"${bs}/>`);
    }
    const top=n.y+n.h/2-(n.lines.length-1)*MMDLH/2+4;
    n.lines.forEach((t,j)=>g.push(`<text class=mmdt x="${(n.x+n.w/2).toFixed(1)}" y="${(top+j*MMDLH).toFixed(1)}"${tf}>${esc(t)}</text>`));
  });
  labels.forEach((l,j)=>{                                     // edge labels last: on top of the nodes, and nudged apart where they collide
    for(let tries=0;tries<8;tries++){
      const hit=labels.slice(0,j).some(o=>Math.abs(o.x-l.x)<(o.w+l.w)/2&&Math.abs(o.y-l.y)<20);
      if(!hit)break;
      l.y+=vert?20:-20;
    }
    g.push(`<rect class=mmdlb x="${(l.x-l.w/2).toFixed(1)}" y="${(l.y-9).toFixed(1)}" width="${l.w}" height="18" rx="4"/>`+
           `<text class=mmdlt x="${l.x.toFixed(1)}" y="${(l.y+4).toFixed(1)}">${esc(l.text)}</text>`);
  });
  return `<svg class=mmdsvg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${sw.toFixed(0)} ${sh.toFixed(0)}" width="${sw.toFixed(0)}" height="${sh.toFixed(0)}" role=img aria-label="diagram">`+
    `<defs><marker id=mmdarrow markerWidth="9" markerHeight="7" refX="8.5" refY="3.5" orient=auto><path d="M0,0 L9,3.5 L0,7 z"/></marker></defs>`+
    `<g transform="translate(${P},${P})" font-size="${MMDW}">${g.join("")}</g></svg>`;
}
// ---- Sequence-diagram sibling of _mermaidSvgFlow. Same zero-dep principle. Covers
// participant/actor decls, →/⇒/dashed/x/) message arrows, self-loops, Note over/left of/
// right of, alt/else/opt/loop/par/critical/break/rect blocks (nested — inner blocks
// tighten to the columns their events touch). Unknown lines are ignored so a stray
// mermaid extension doesn't kill the whole diagram. Autonumber/activate/deactivate skipped.
const MMSCW=6.9,MMSFS=13,MMSPH=30,MMSLANE=36,MMSSELF=52,MMSNPAD=10,MMSPX=14,MMSGAP=28,MMSBLKPAD=10,MMSMARGIN=22,MMSHEADGAP=18;
function _mmsLabel(s){return (s||"").replace(/<br\s*\/?>/gi," ").replace(/<\/?[a-z][^>]*>/gi,"").replace(/^\s*["'`]|["'`]\s*$/g,"").trim();}
function _mmsPart(pmap,order,id,label){
  if(!pmap[id]){ pmap[id]={id:id,label:label||id}; order.push(id); }
  else if(label&&pmap[id].label===pmap[id].id){ pmap[id].label=label; }
}
function _mermaidSeqSvg(src){
  const pmap={},order=[],events=[],stack=[]; let started=false;
  for(const raw of (src||"").replace(/\r/g,"").split("\n")){
    let l=raw.replace(/%%.*$/,"").trim(); if(!l)continue;
    if(!started){ if(!/^sequenceDiagram\b/i.test(l))return null;
      started=true; l=l.replace(/^sequenceDiagram\b\s*/i,""); if(!l)continue; }
    if(/^(autonumber|activate|deactivate|title|accTitle|accDescr|links|link|properties|details|box|end box)\b/i.test(l))continue;
    let m;
    if((m=l.match(/^(participant|actor)\s+([A-Za-z0-9_.-]+)(?:\s+as\s+(.+))?$/i))){
      _mmsPart(pmap,order,m[2],_mmsLabel(m[3])); continue; }
    if((m=l.match(/^Note\s+(over|left of|right of)\s+([^:]+?)\s*:\s*(.*)$/i))){
      const scope=m[1].toLowerCase().replace(/\s+/g,"_");
      const ids=m[2].split(",").map(s=>s.trim()).filter(Boolean);
      if(!ids.length)continue;
      ids.forEach(id=>_mmsPart(pmap,order,id,null));
      events.push({type:"note",scope:scope,ids:ids,text:_mmsLabel(m[3])}); continue; }
    if((m=l.match(/^(alt|opt|loop|par|critical|break|rect)\b\s*(.*)$/i))){
      events.push({type:"bstart",kind:m[1].toLowerCase(),cond:_mmsLabel(m[2])}); continue; }
    if((m=l.match(/^(?:else|and|option)\b\s*(.*)$/i))){
      events.push({type:"belse",cond:_mmsLabel(m[1])}); continue; }
    if(/^end\b\s*$/i.test(l)){ events.push({type:"bend"}); continue; }
    // messages: A->B / A-->B / A->>B / A-->>B / A-xB / A--xB / A-)B / A--)B.
    // The id charset forbids a trailing `-` (segment must end in a non-hyphen), so `CP-->>G`
    // parses as CP + `--` + `>>` + G, not as `CP-` + `-` + `>>` + G — a subtle greedy-`-` trap
    // that would otherwise turn every dashed-reply into an extra participant and drop the dash class.
    if((m=l.match(/^([A-Za-z0-9_.]+(?:-[A-Za-z0-9_.]+)*)\s*(-{1,2})(>{1,2}|[x)])[+-]?\s*([A-Za-z0-9_.]+(?:-[A-Za-z0-9_.]+)*)\s*:\s*(.*)$/))){
      _mmsPart(pmap,order,m[1],null); _mmsPart(pmap,order,m[4],null);
      events.push({type:"msg",from:m[1],to:m[4],dash:m[2].length===2,head:m[3],text:_mmsLabel(m[5])}); continue; }
    // unknown line — swallow rather than crash; keeps rendering robust to mermaid extensions
  }
  if(!started||!order.length)return null;

  const cols=order.map(id=>{ const n=pmap[id]; const w=Math.max(80,n.label.length*MMSCW+MMSPX*2);
    return {id:id,label:n.label,w:w}; });
  let cx=0; cols.forEach(c=>{ c.x=cx; c.cx=cx+c.w/2; cx+=c.w+MMSGAP; });
  const totalW=cx-MMSGAP; const colIx={}; cols.forEach((c,i)=>colIx[c.id]=i);

  const headBottom=MMSMARGIN+MMSPH; let y=headBottom+MMSHEADGAP;
  const blkStack=[];                                   // {ev,startY,minCol,maxCol,depth,elses:[]}
  events.forEach(ev=>{
    if(ev.type==="msg"){
      ev.y=y; y+=ev.from===ev.to?MMSSELF:MMSLANE;
      const a=colIx[ev.from],b=colIx[ev.to];
      blkStack.forEach(bl=>{ bl.minCol=Math.min(bl.minCol,a,b); bl.maxCol=Math.max(bl.maxCol,a,b); });
    } else if(ev.type==="note"){
      ev.y=y; ev.h=MMSPH; y+=ev.h+MMSNPAD;
      const idxs=ev.ids.map(id=>colIx[id]);
      blkStack.forEach(bl=>{ bl.minCol=Math.min.apply(null,[bl.minCol].concat(idxs));
                             bl.maxCol=Math.max.apply(null,[bl.maxCol].concat(idxs)); });
    } else if(ev.type==="bstart"){
      const bl={ev:ev,startY:y,minCol:cols.length,maxCol:-1,depth:blkStack.length,elses:[]};
      blkStack.push(bl); y+=22;                        // room for the label tab
    } else if(ev.type==="belse"){
      const bl=blkStack[blkStack.length-1]; if(bl){ ev.y=y; bl.elses.push({y:y,cond:ev.cond}); y+=22; }
    } else if(ev.type==="bend"){
      const bl=blkStack.pop(); if(bl){ ev.b=bl; ev.endY=y; y+=MMSBLKPAD; }
    }
  });
  const footTop=y+6; const H=footTop+MMSPH+MMSMARGIN; const W=totalW+MMSMARGIN*2;

  const blkOut=[],staticOut=[],noteOut=[],msgOut=[];
  // lifelines first (dashed, behind everything)
  cols.forEach(c=>staticOut.push(`<line class=mmsll x1="${c.cx.toFixed(1)}" y1="${headBottom}" x2="${c.cx.toFixed(1)}" y2="${footTop.toFixed(1)}"/>`));
  // participant boxes — mirrored top and bottom
  const drawPBox=yTop=>cols.forEach(c=>{
    staticOut.push(`<rect class=mmsp x="${c.x.toFixed(1)}" y="${yTop}" width="${c.w.toFixed(1)}" height="${MMSPH}" rx="4"/>`);
    staticOut.push(`<text class=mmspt x="${c.cx.toFixed(1)}" y="${(yTop+MMSPH/2+4).toFixed(1)}">${esc(c.label)}</text>`);
  });
  drawPBox(MMSMARGIN); drawPBox(footTop);

  events.forEach(ev=>{
    if(ev.type==="bend"&&ev.b){
      const bl=ev.b;
      const minC=bl.maxCol<0?0:bl.minCol, maxC=bl.maxCol<0?cols.length-1:bl.maxCol;
      const bx=cols[minC].x-MMSBLKPAD, bw=(cols[maxC].x+cols[maxC].w)-cols[minC].x+MMSBLKPAD*2;
      const by=bl.startY, bh=ev.endY-by;
      blkOut.push(`<rect class="mmsblk d${bl.depth}" x="${bx.toFixed(1)}" y="${by.toFixed(1)}" width="${bw.toFixed(1)}" height="${bh.toFixed(1)}" rx="4"/>`);
      const ttl=bl.ev.kind.toUpperCase()+(bl.ev.cond?"  "+bl.ev.cond:"");
      const tw=ttl.length*MMSCW+14;
      blkOut.push(`<rect class=mmsblkb x="${bx.toFixed(1)}" y="${by.toFixed(1)}" width="${tw.toFixed(1)}" height="18" rx="4"/>`);
      blkOut.push(`<text class=mmsblkt x="${(bx+tw/2).toFixed(1)}" y="${(by+13).toFixed(1)}">${esc(ttl)}</text>`);
      bl.elses.forEach(el=>{
        blkOut.push(`<line class=mmsblkls x1="${bx.toFixed(1)}" y1="${el.y.toFixed(1)}" x2="${(bx+bw).toFixed(1)}" y2="${el.y.toFixed(1)}"/>`);
        if(el.cond){ const et="ELSE  "+el.cond, etw=et.length*MMSCW+10;
          blkOut.push(`<rect class=mmsblkb x="${bx.toFixed(1)}" y="${el.y.toFixed(1)}" width="${etw.toFixed(1)}" height="18" rx="4"/>`);
          blkOut.push(`<text class=mmsblkt x="${(bx+etw/2).toFixed(1)}" y="${(el.y+13).toFixed(1)}">${esc(et)}</text>`);
        }
      });
    } else if(ev.type==="note"){
      const ixs=ev.ids.map(id=>colIx[id]).sort((a,b)=>a-b);
      let nx,nw;
      if(ev.scope==="over"){
        nx=cols[ixs[0]].cx-30;
        nw=cols[ixs[ixs.length-1]].cx-cols[ixs[0]].cx+60;
        nw=Math.max(nw,ev.text.length*MMSCW+MMSPX*2);
      } else if(ev.scope==="left_of"){
        nw=Math.max(80,ev.text.length*MMSCW+MMSPX*2);
        nx=cols[ixs[0]].cx-20-nw;
      } else {                                          // right_of
        nw=Math.max(80,ev.text.length*MMSCW+MMSPX*2);
        nx=cols[ixs[0]].cx+20;
      }
      // Note width already scales to the text (see the width computation above), so no truncation.
      noteOut.push(`<rect class=mmsnote x="${nx.toFixed(1)}" y="${ev.y.toFixed(1)}" width="${nw.toFixed(1)}" height="${ev.h}" rx="3"/>`);
      noteOut.push(`<text class=mmsnt x="${(nx+nw/2).toFixed(1)}" y="${(ev.y+ev.h/2+4).toFixed(1)}">${esc(ev.text)}</text>`);
    } else if(ev.type==="msg"){
      const a=cols[colIx[ev.from]], b=cols[colIx[ev.to]];
      const marker=ev.head===">>"?"mmsarrow":ev.head===">"?"mmsarrowo":ev.head==="x"?"mmsarrowx":"mmsarrowc";
      const dashCls=ev.dash?" dash":"";
      // Message text is emitted in full — no truncation. Real mermaid also lets
      // labels overflow the gap; the outer .mmd container is overflow-x:auto so a wide
      // diagram scrolls, and truncating here would silently drop information a search
      // over the modal expects to find.
      if(ev.from===ev.to){
        const cxs=a.cx, halfW=30, yMid=ev.y+14, yBot=ev.y+34;
        msgOut.push(`<path class="mmsm${dashCls}" d="M${cxs.toFixed(1)},${yMid.toFixed(1)} L${(cxs+halfW).toFixed(1)},${yMid.toFixed(1)} L${(cxs+halfW).toFixed(1)},${yBot.toFixed(1)} L${cxs.toFixed(1)},${yBot.toFixed(1)}" fill="none" marker-end="url(#${marker})"/>`);
        msgOut.push(`<text class=mmsmt x="${(cxs+halfW+6).toFixed(1)}" y="${(yMid+4).toFixed(1)}" text-anchor="start">${esc(ev.text)}</text>`);
      } else {
        const x1=a.cx, x2=b.cx, yTop=ev.y+18;
        msgOut.push(`<line class="mmsm${dashCls}" x1="${x1.toFixed(1)}" y1="${yTop.toFixed(1)}" x2="${x2.toFixed(1)}" y2="${yTop.toFixed(1)}" marker-end="url(#${marker})"/>`);
        msgOut.push(`<text class=mmsmt x="${((x1+x2)/2).toFixed(1)}" y="${(yTop-5).toFixed(1)}">${esc(ev.text)}</text>`);
      }
    }
  });

  const defs=`<defs>`+
    `<marker id=mmsarrow markerWidth="9" markerHeight="7" refX="8.5" refY="3.5" orient=auto><path d="M0,0 L9,3.5 L0,7 z"/></marker>`+
    `<marker id=mmsarrowo markerWidth="9" markerHeight="7" refX="8.5" refY="3.5" orient=auto><path d="M0,0 L9,3.5 L0,7" fill="none" stroke-width="1.4"/></marker>`+
    `<marker id=mmsarrowx markerWidth="10" markerHeight="10" refX="5" refY="5" orient=auto><path d="M1,1 L9,9 M9,1 L1,9" fill="none" stroke-width="1.4"/></marker>`+
    `<marker id=mmsarrowc markerWidth="9" markerHeight="9" refX="8" refY="4.5" orient=auto><path d="M0,1 A4 4 0 0 1 8,4.5 A4 4 0 0 1 0,8" fill="none" stroke-width="1.4"/></marker>`+
    `</defs>`;
  return `<svg class=mmdsvg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${W.toFixed(0)} ${H.toFixed(0)}" width="${W.toFixed(0)}" height="${H.toFixed(0)}" role=img aria-label="sequence diagram">`+
    defs+`<g transform="translate(${MMSMARGIN},0)" font-size="${MMSFS}">`+
    blkOut.join("")+staticOut.join("")+noteOut.join("")+msgOut.join("")+`</g></svg>`;
}

// ---- stateDiagram / stateDiagram-v2 → translate to flowchart syntax, then hand off to
// _mermaidSvgFlow. States are nodes, transitions are directed edges — semantically identical
// to a flowchart — so we get labelled edges, layered layout and (via classDef) themed
// start/end pseudostates for free. `[*]` becomes a small filled circle; `state "Long" as X`
// becomes an aliased node; composite `state Foo { ... }` blocks are flattened (the nested
// members render alongside the parent) so the diagram at least appears, even if the
// composite border is dropped — beats the raw fence, which was the alternative.
function _mermaidStateSvg(src){
  const lines=(src||"").replace(/\r/g,"").split("\n");
  let started=false, dir="TD", spN=0; const outL=[], psps=[];
  const psp=()=>{ const id=`__sp${spN++}`; psps.push(id); return id; };
  const nodeIdRe=/^(\[\*\]|[A-Za-z0-9_.-]+)$/;
  for(let raw of lines){
    let l=raw.replace(/%%.*$/,"").trim(); if(!l)continue;
    if(!started){
      const h=l.match(/^stateDiagram(?:-v2)?\b\s*(?:(TD|TB|LR|RL|BT))?\s*$/i);
      if(!h)return null;
      dir=(h[1]||"TD").toUpperCase(); started=true; continue;
    }
    // ignore lines the flow renderer can't use and mermaid-state's own decoration
    if(/^(note\b|hide\s|scale\b|accTitle|accDescr|classDef\b|class\s|link\b|click\b|style\b)/i.test(l))continue;
    if(/^direction\s+(TD|TB|LR|RL|BT)\b/i.test(l)){ dir=RegExp.$1.toUpperCase(); continue; }
    if(/^--\s*$/.test(l))continue;                     // composite-state separator
    if(/^\}\s*$/.test(l))continue;                     // closing brace of composite — flatten
    let m;
    // `state "Long label" as ID` — aliased state → single-quoted flowchart label preserves punctuation
    if((m=l.match(/^state\s+"([^"]+)"\s+as\s+([A-Za-z0-9_.-]+)\s*$/i))){
      outL.push(`${m[2]}["${m[1].replace(/"/g,"'")}"]`); continue;
    }
    // `state Name` or `state Name {` — bare declaration (flatten the opening brace)
    if((m=l.match(/^state\s+([A-Za-z0-9_.-]+)\s*\{?\s*$/i))){
      outL.push(m[1]); continue;
    }
    // Transition: `A --> B` or `A --> B : label`   (with optional whitespace / dotted arrow)
    if((m=l.match(/^(\[\*\]|[A-Za-z0-9_.-]+)\s*(-{2,}>|-\.->)\s*(\[\*\]|[A-Za-z0-9_.-]+)\s*(?::\s*(.+))?$/))){
      let a=m[1], b=m[3], arrow=m[2], label=(m[4]||"").trim();
      if(a==="[*]") a=psp();
      if(b==="[*]") b=psp();
      const arr=arrow==="-.->"?"-.->":"-->";
      // Edge label lives between pipes for the flowchart parser — strip `|` from the payload
      // so the parser can't misread the delimiter, and don't wrap in quotes (they'd render literally).
      if(label){ outL.push(`${a} ${arr}|${label.replace(/\|/g,"/")}| ${b}`); }
      else     { outL.push(`${a} ${arr} ${b}`); }
      continue;
    }
    // Bare state id on its own line (auto-declares it as a node)
    if(nodeIdRe.test(l) && l!=="[*]"){ outL.push(l); continue; }
    // Unknown line — swallow rather than kill the diagram (mirrors _mermaidSeqSvg)
  }
  if(!started||!outL.length)return null;
  const flow=[`flowchart ${dir}`, ...outL];
  if(psps.length){                                     // dot-style pseudostates: dark filled circle
    flow.push(`classDef ssp fill:#5b6474,stroke:#2b323e,color:#fff`);
    flow.push(`class ${psps.join(",")} ssp`);
    psps.forEach(id=>flow.push(`${id}(("·"))`));       // circle shape, tiny centre-dot label
  }
  return _mermaidSvgFlow(flow.join("\n"));
}

// ---- classDiagram → flowchart. Each class becomes a multi-line rectangle carrying its
// members (attributes + methods), and every relationship — inheritance, composition,
// aggregation, association, dependency, realisation — becomes a directed edge whose
// arrowhead points at the *base* class (mermaid draws A<|--B as B extending A, so we
// emit B → A). Cardinality / role labels ride the edge as its label. Internal attribute
// details (visibility markers, types) are preserved verbatim in the box.
function _mermaidClassSvg(src){
  const lines=(src||"").replace(/\r/g,"").split("\n");
  let started=false, curCls=null;
  const members={}, edges=[], seen=new Set();
  const touch=id=>{ if(!members[id]){ members[id]=[]; seen.add(id); } };
  for(let raw of lines){
    let l=raw.replace(/%%.*$/,"").trim(); if(!l)continue;
    if(!started){ if(!/^classDiagram(?:-v2)?\b/i.test(l))return null;
      started=true; continue; }
    if(/^(direction\b|namespace\b|link\b|click\b|style\b|cssClass\b|note\b|accTitle|accDescr)/i.test(l))continue;
    if(curCls){                                                       // inside `class X { ... }` block
      if(/^\}\s*$/.test(l)){ curCls=null; continue; }
      members[curCls].push(l.replace(/^[+#\-~]?\s*/, m=>m)); continue;
    }
    let m;
    if((m=l.match(/^class\s+([A-Za-z0-9_.]+)(?:\s*<<[^>]+>>)?\s*(\{)?\s*$/i))){
      touch(m[1]); if(m[2]) curCls=m[1]; continue;
    }
    // `ClassName : member text`  — attribute or method line
    if((m=l.match(/^([A-Za-z0-9_.]+)\s*:\s*(.+)$/))){
      touch(m[1]); members[m[1]].push(m[2].trim()); continue;
    }
    // Relationship: A <op> B  [: label]. Cardinality ("1", "*", "0..1") may sit before/after
    // each side; strip and preserve as label context. Supported ops:
    //   <|-- --|>   (inheritance)     *-- --*   (composition)   o-- --o   (aggregation)
    //   <..  ..>    (dep. realise)    <|..  ..|>  (realisation) --   ..   (link, no arrow)
    const relRe=/^([A-Za-z0-9_.]+)(?:\s+"([^"]*)")?\s*(<\|--|--\|>|<\|\.\.|\.\.\|>|\*--|--\*|o--|--o|<--|-->|<\.\.|\.\.>|--|\.\.)\s*(?:"([^"]*)"\s+)?([A-Za-z0-9_.]+)(?:\s*:\s*(.+))?$/;
    if((m=l.match(relRe))){
      const a=m[1], cardA=m[2]||"", op=m[3], cardB=m[4]||"", b=m[5], lab=(m[6]||"").trim();
      const reverse=["<|--","<--","<|..","<.."].includes(op);        // arrow lands on left side
      const from=reverse?b:a, to=reverse?a:b;
      const parts=[]; if(cardA) parts.push(reverse?cardB:cardA);
      if(lab) parts.push(lab);
      if(cardB) parts.push(reverse?cardA:cardB);
      touch(a); touch(b);
      edges.push({from,to,label:parts.filter(Boolean).join(" ")});
      continue;
    }
  }
  if(!started||!seen.size)return null;
  const flow=[`flowchart TD`];
  seen.forEach(id=>{
    const mems=(members[id]||[]).filter(Boolean);
    const label=mems.length?`${id}<br/>${mems.join("<br/>")}`:id;
    flow.push(`${id}["${label.replace(/"/g,"'")}"]`);
  });
  edges.forEach(e=>{
    // Same rule as the state renderer: don't quote the edge label — quotes would render literally
    if(e.label) flow.push(`${e.from} -->|${e.label.replace(/\|/g,"/")}| ${e.to}`);
    else        flow.push(`${e.from} --> ${e.to}`);
  });
  return _mermaidSvgFlow(flow.join("\n"));
}

// ---- erDiagram → flowchart. Entities are boxes carrying their attributes; the cardinality
// shorthand (`||--o{`) rides the edge label alongside the verb so the reader still sees
// "one-to-many" (or its symbolic equivalent) without a dedicated marker library.
function _mermaidErSvg(src){
  const lines=(src||"").replace(/\r/g,"").split("\n");
  let started=false, curEnt=null;
  const attrs={}, edges=[], seen=new Set();
  const touch=id=>{ if(!attrs[id]){ attrs[id]=[]; seen.add(id); } };
  for(let raw of lines){
    let l=raw.replace(/%%.*$/,"").trim(); if(!l)continue;
    if(!started){ if(!/^erDiagram\b/i.test(l))return null;
      started=true; continue; }
    if(curEnt){
      if(/^\}\s*$/.test(l)){ curEnt=null; continue; }
      // an attribute line is: `type name [PK|FK|UK] [ "comment" ]` — keep the whole thing
      attrs[curEnt].push(l.replace(/\s+/g," ")); continue;
    }
    if(/^(accTitle|accDescr)/i.test(l))continue;
    let m;
    if((m=l.match(/^([A-Za-z0-9_-]+)\s*\{\s*$/))){ touch(m[1]); curEnt=m[1]; continue; }
    // Relationship: NAME  <card><arrow><card>  NAME  [: verb]
    //   valid cardinality bookends: |o  o|  ||  }o  o{  }|  |{
    if((m=l.match(/^([A-Za-z0-9_-]+)\s+([|o}]{1,2})(--|\.\.)([|o{]{1,2})\s+([A-Za-z0-9_-]+)\s*(?::\s*(.+))?$/))){
      const a=m[1], cardA=m[2], line=m[3], cardB=m[4], b=m[5], verb=(m[6]||"").trim();
      touch(a); touch(b);
      const readable={"||":"one","|o":"zero-or-one","o|":"zero-or-one","}o":"zero-or-more","o{":"zero-or-more","}|":"one-or-more","|{":"one-or-more"};
      const card=`${readable[cardA]||cardA} → ${readable[cardB]||cardB}`;
      const label=verb?`${verb} · ${card}`:card;
      edges.push({from:a,to:b,label,dash:line==="."});
      continue;
    }
  }
  if(!started||!seen.size)return null;
  const flow=[`flowchart LR`];
  seen.forEach(id=>{
    const at=(attrs[id]||[]).filter(Boolean);
    const label=at.length?`${id}<br/>${at.join("<br/>")}`:id;
    flow.push(`${id}["${label.replace(/"/g,"'")}"]`);
  });
  edges.forEach(e=>{
    // Same rule as the other translators: no quote-wrap on edge labels — they'd render literally.
    const arr=e.dash?"-.->":"-->";
    if(e.label) flow.push(`${e.from} ${arr}|${e.label.replace(/\|/g,"/")}| ${e.to}`);
    else        flow.push(`${e.from} ${arr} ${e.to}`);
  });
  return _mermaidSvgFlow(flow.join("\n"));
}

// ---- journey → flowchart. Each `section` becomes a header node, and every task under it
// becomes a chained node carrying its happiness score (1-5) as a face emoji. Sections
// render as separate horizontal chains so the reader sees each phase as its own row.
function _mermaidJourneySvg(src){
  const lines=(src||"").replace(/\r/g,"").split("\n");
  let started=false, secN=0, taskN=0, curSec=null;
  const outL=[], secIds=[];
  // ponytail: a 5-dot meter, not emoji faces. This string is interpolated into
  // mermaid's own ["..."] label syntax, so ico()'s double-quoted SVG would end
  // the label early and corrupt the DSL -- plain ●/○ carry the score safely.
  const face=s=>(s>=1&&s<=5)?"●".repeat(s)+"○".repeat(5-s):"·";
  for(let raw of lines){
    let l=raw.replace(/%%.*$/,"").trim(); if(!l)continue;
    if(!started){ if(!/^(journey|userJourney)\b/i.test(l))return null;
      started=true; continue; }
    if(/^title\s/i.test(l))continue;
    let m;
    if((m=l.match(/^section\s+(.+)$/i))){
      const sid=`__sec${secN++}`; secIds.push(sid); curSec={id:sid,prev:sid};
      outL.push(`${sid}["${m[1].replace(/"/g,"'")}"]`); continue;
    }
    // task line: `TaskName : score : actor1, actor2`
    if((m=l.match(/^(.+?)\s*:\s*(\d+)\s*:\s*(.+)$/))){
      if(!curSec)continue;
      const name=m[1].trim(), score=parseInt(m[2],10), actors=m[3].trim();
      const tid=`__tk${taskN++}`;
      const label=`${name.replace(/"/g,"'")}<br/>${face(score)} ${score}<br/>${actors.replace(/"/g,"'")}`;
      outL.push(`${tid}["${label}"]`);
      outL.push(`${curSec.prev} --> ${tid}`);
      curSec.prev=tid; continue;
    }
  }
  if(!started||!outL.length)return null;
  const flow=[`flowchart LR`, ...outL];
  if(secIds.length){
    flow.push(`classDef jsec fill:#334155,stroke:#334155,color:#f8fafc`);
    flow.push(`class ${secIds.join(",")} jsec`);
  }
  return _mermaidSvgFlow(flow.join("\n"));
}

// ---- pie → dedicated small SVG (no flowchart reuse — a proportional slice with a percent
// legend is nothing the flow layout would give). Colours cycle a fixed palette so a
// repeated diagram stays visually stable; slice text goes to the legend, not the arc, so
// long labels don't overflow the wedge.
const MPIE_C=["#5b8def","#f59e0b","#22c55e","#a78bfa","#ec4899","#14b8a6","#ef4444","#eab308","#0ea5e9","#f97316"];
function _mermaidPieSvg(src){
  const lines=(src||"").replace(/\r/g,"").split("\n");
  let started=false, title="", slices=[];
  for(let raw of lines){
    let l=raw.replace(/%%.*$/,"").trim(); if(!l)continue;
    if(!started){
      const h=l.match(/^pie(?:\s+showData)?\s*(?:title\s+(.+))?$/i);
      if(!h)return null;
      if(h[1]) title=h[1].trim(); started=true; continue;
    }
    let m;
    if((m=l.match(/^title\s+(.+)$/i))){ title=m[1].trim(); continue; }
    if((m=l.match(/^"([^"]*)"\s*:\s*([0-9.]+)\s*$/))){
      slices.push({label:m[1], value:parseFloat(m[2])}); continue;
    }
  }
  if(!started||!slices.length)return null;
  const total=slices.reduce((s,x)=>s+x.value,0); if(total<=0)return null;
  const R=90, cx=110, cy=118;
  const arcs=[]; let angle=-Math.PI/2;
  slices.forEach((s,i)=>{
    const sweep=(s.value/total)*Math.PI*2;
    const x1=cx+R*Math.cos(angle), y1=cy+R*Math.sin(angle);
    const x2=cx+R*Math.cos(angle+sweep), y2=cy+R*Math.sin(angle+sweep);
    const large=sweep>Math.PI?1:0, fill=MPIE_C[i%MPIE_C.length];
    // Guard: a single-slice pie can't be drawn as an arc — render the full circle instead
    if(slices.length===1){ arcs.push(`<circle class=mmdn cx="${cx}" cy="${cy}" r="${R}" fill="${fill}"/>`); }
    else { arcs.push(`<path class=mmdn d="M${cx},${cy} L${x1.toFixed(1)},${y1.toFixed(1)} A${R},${R} 0 ${large} 1 ${x2.toFixed(1)},${y2.toFixed(1)} Z" fill="${fill}" stroke-width="1.5"/>`); }
    angle+=sweep;
  });
  const legX=225; let legY=32;
  const legend=slices.map((s,i)=>{
    const pct=(s.value/total*100).toFixed(1), fill=MPIE_C[i%MPIE_C.length];
    const row=`<rect x="${legX}" y="${legY-11}" width="14" height="14" fill="${fill}" rx="3"/>`+
              `<text class=mmdt x="${legX+20}" y="${legY+0}" text-anchor="start">${esc(s.label)} — ${pct}%</text>`;
    legY+=22; return row;
  }).join("");
  const W=Math.max(430, legX + 40 + Math.max.apply(null, slices.map(s=>s.label.length*7+70)));
  const H=Math.max(240, legY+16);
  const t=title?`<text class=mmdt x="${(W/2).toFixed(1)}" y="22" font-weight="700" font-size="14">${esc(title)}</text>`:"";
  return `<svg class=mmdsvg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role=img aria-label="pie chart">`+
    t + arcs.join("") + legend + `</svg>`;
}

// ---- quadrantChart → dedicated small SVG. Axes carry their labels, each quadrant its
// title, points drop as labelled dots at their [x,y] in the [0,1]² space (0,0 is bottom-left).
function _mermaidQuadrantSvg(src){
  const lines=(src||"").replace(/\r/g,"").split("\n");
  let started=false, title="", xAxis="", yAxis="", quads=["","","",""], points=[];
  for(let raw of lines){
    let l=raw.replace(/%%.*$/,"").trim(); if(!l)continue;
    if(!started){ if(!/^quadrantChart\b/i.test(l))return null;
      started=true; continue; }
    let m;
    if((m=l.match(/^title\s+(.+)$/i))){ title=m[1].trim(); continue; }
    if((m=l.match(/^x-axis\s+(.+)$/i))){ xAxis=m[1].trim(); continue; }
    if((m=l.match(/^y-axis\s+(.+)$/i))){ yAxis=m[1].trim(); continue; }
    if((m=l.match(/^quadrant-([1-4])\s+(.+)$/i))){ quads[parseInt(m[1],10)-1]=m[2].trim(); continue; }
    // point: `Label: [0.3, 0.7]`  (label may be quoted; values accept a leading `-` so a
    // rogue out-of-range coordinate still parses — the render pass clamps to the axes).
    if((m=l.match(/^"?([^":]+?)"?\s*:\s*\[\s*(-?[0-9.]+)\s*,\s*(-?[0-9.]+)\s*\]\s*$/))){
      points.push({label:m[1].trim(), x:parseFloat(m[2]), y:parseFloat(m[3])}); continue;
    }
  }
  if(!started)return null;
  const P=44, W=520, H=380, ix=P, iy=32+P, iw=W-P*2, ih=H-P*2-32;
  const cx=ix+iw/2, cy=iy+ih/2;
  const parts=[];
  if(title) parts.push(`<text class=mmdt x="${(W/2).toFixed(1)}" y="22" font-weight="700" font-size="14">${esc(title)}</text>`);
  // outer box + quadrant divider lines
  parts.push(`<rect class=mmdn x="${ix}" y="${iy}" width="${iw}" height="${ih}" fill="none"/>`);
  parts.push(`<line class=mmde x1="${cx.toFixed(1)}" y1="${iy}" x2="${cx.toFixed(1)}" y2="${(iy+ih).toFixed(1)}"/>`);
  parts.push(`<line class=mmde x1="${ix}" y1="${cy.toFixed(1)}" x2="${(ix+iw).toFixed(1)}" y2="${cy.toFixed(1)}"/>`);
  // quadrant labels (top-right=1, top-left=2, bottom-left=3, bottom-right=4 per mermaid docs)
  const qc=[{x:cx+iw/4,y:iy+ih/4},{x:cx-iw/4,y:iy+ih/4},{x:cx-iw/4,y:cy+ih/4},{x:cx+iw/4,y:cy+ih/4}];
  quads.forEach((q,i)=>{ if(q) parts.push(`<text class=mmdt x="${qc[i].x.toFixed(1)}" y="${qc[i].y.toFixed(1)}" font-size="12">${esc(q)}</text>`); });
  // axis labels
  if(xAxis) parts.push(`<text class=mmdt x="${cx.toFixed(1)}" y="${(iy+ih+26).toFixed(1)}" font-size="12">${esc(xAxis)}</text>`);
  if(yAxis){
    const ty=(cy).toFixed(1), tx=(ix-18).toFixed(1);
    parts.push(`<text class=mmdt x="${tx}" y="${ty}" font-size="12" transform="rotate(-90 ${tx} ${ty})">${esc(yAxis)}</text>`);
  }
  // points — y is inverted (mermaid's 0 is at bottom, SVG's is at top)
  points.forEach(pt=>{
    const px=ix+Math.max(0,Math.min(1,pt.x))*iw;
    const py=iy+ih-Math.max(0,Math.min(1,pt.y))*ih;
    parts.push(`<circle cx="${px.toFixed(1)}" cy="${py.toFixed(1)}" r="5" fill="#5b8def"/>`);
    parts.push(`<text class=mmdt x="${(px+9).toFixed(1)}" y="${(py+4).toFixed(1)}" text-anchor="start" font-size="11">${esc(pt.label)}</text>`);
  });
  return `<svg class=mmdsvg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role=img aria-label="quadrant chart">`+
    parts.join("") + `</svg>`;
}

// ---- Mermaid → REAL rendering, lazily vendored (product owner approved this one
// dependency; conventions rule 2: committed vendor file, loaded lazily, never at page
// load). The hand-rolled SVG renderers above (mermaidSvg() and its _mermaid*Svg()
// helpers) are NOT dead code — mdBlock() still renders every mermaid fence with them
// FIRST, synchronously, so the page is correct immediately: offline, before the
// ~3.4MB vendored asset loads, or if mermaid.js throws on syntax it doesn't recognise.
// renderMermaid() below then upgrades that fallback IN PLACE once the real library is
// available — mermaid wins whenever it loads and succeeds; the hand-rolled SVG (or, in
// the Control Room's inline diagram card, the node-pill row) wins otherwise, forever,
// on that one render. ONE renderer for BOTH UIs: app.js and every web/ext_*.js file
// are concatenated into a single <script> tag by page.py's build_page() (verified —
// index.html:186 is exactly one script tag holding the page's JS placeholder, which
// build_page() fills with read("app.js") + read_ext(".js"), sorted), so a plain
// top-level function declared here is a global
// both this file's mdBlock()/renderMdView()/openText() AND ext_cr_detail.js's
// entryHtml()/renderTimelineEntries() can call directly by name — no second
// implementation, per conventions rule 4.
let _mermaidAssetPromise=null;
function _loadMermaidAssets(){
  if(_mermaidAssetPromise) return _mermaidAssetPromise;
  _mermaidAssetPromise=new Promise((resolve,reject)=>{
    if(window.mermaid){ resolve(); return; }   // already loaded (2nd diagram)
    const s=document.createElement("script");
    s.src="/vendor/mermaid.min.js";
    s.onload=()=>resolve();
    s.onerror=()=>reject(new Error("failed to load /vendor/mermaid.min.js"));
    document.head.appendChild(s);
  });
  return _mermaidAssetPromise;
}
// UTF-8-safe base64 — used to smuggle a diagram's raw source through a data-* attribute
// (mdBlock/entryHtml build plain HTML strings, not DOM nodes with closures, so the
// source can't just be held in memory). Plain btoa()/atob() are Latin1-only, hence the
// encodeURIComponent/decodeURIComponent round-trip.
function _mmdEncodeSrc(s){ try{ return btoa(unescape(encodeURIComponent(s||""))); }catch(e){ return ""; } }
function _mmdDecodeSrc(b){ try{ return decodeURIComponent(escape(atob(b||""))); }catch(e){ return ""; } }
// Theme derived from the app's OWN CSS custom properties — never a hardcoded palette
// (conventions rule 5, "server owns policy, client renders it", applied to theme: read
// the ONE existing source of truth for whichever scope `el` sits in, don't invent a
// second palette). Two token vocabularies exist side by side in this app: the classic
// UI's --app/--text/--card/--line3/--muted/... (app.css :root / html.light, this
// file's own mermaidSvg() CSS already keys off these) and the Control Room's
// --surface-*/--text-*/--line-* (ext_cr.css .tracker-next / .tracker-next.is-dark).
// getComputedStyle(el) already resolves through whichever ancestor set those
// variables for the CURRENT theme (light/dark, or Control Room's own toggle on
// #nextRoot) — this only needs to pick the right variable NAMES for the scope `el`
// sits in, mirroring ext_vt.js's _xtermTheme(el).
function _mermaidThemeVars(el){
  const node=el||document.documentElement;
  const isNext=!!(node.closest && node.closest(".tracker-next"));
  const cs=getComputedStyle(node);
  const v=(name,fallback)=>{ const val=cs.getPropertyValue(name); return val?val.trim():fallback; };
  if(isNext){
    return {
      background: v("--surface-raised","#FFFFFF"),
      primaryColor: v("--surface-top","#FBFAF7"),
      primaryTextColor: v("--text-primary","#1E1B17"),
      primaryBorderColor: v("--line-default","#CFC7B7"),
      lineColor: v("--line-strong","#A89C8B"),
      secondaryColor: v("--surface-sunken","#F4F1E8"),
      tertiaryColor: v("--surface-note","#F7F4EA"),
      textColor: v("--text-primary","#1E1B17"),
    };
  }
  return {
    background: v("--app","#0c0f15"),
    primaryColor: v("--card","#0e121a"),
    primaryTextColor: v("--text","#e6edf3"),
    primaryBorderColor: v("--line3","#2c333f"),
    lineColor: v("--muted","#8b98a8"),
    secondaryColor: v("--side","#0a0d12"),
    tertiaryColor: v("--raised","#131a24"),
    textColor: v("--text","#e6edf3"),
  };
}
let _mermaidRenderSeq=0;
let _mermaidQueue=Promise.resolve();  // serialises mermaid.initialize()+render() pairs:
                                       // mermaid's config is process-global, so two
                                       // renders in flight at once (e.g. classic +
                                       // Control Room diagrams upgrading together) could
                                       // otherwise theme-clobber each other mid-render.
// THE shared renderer both UIs call: async function renderMermaid(code, el). Lazy-loads
// the vendored bundle on first use (memoized above, exactly like ext_vt.js's own
// _loadXtermAssets()), (re-)initialises mermaid with the CURRENT caller's theme, renders
// `code`, and injects the resulting SVG into `el` wrapped in the SAME `.mmd` card class
// the hand-rolled renderer already uses (app.css's `.mmd{background:var(--side);...}` —
// reused, not duplicated). Resolves `false` — touching `el` NOT AT ALL — if the asset
// fails to load or mermaid.js throws on this source, so whatever fallback markup was
// already sitting in `el` (hand-rolled SVG, unsupported-fence code block, or the
// Control Room's node-pill row) is exactly what stays visible.
async function renderMermaid(code, el){
  if(!el || !code) return false;
  const run=()=>_loadMermaidAssets().then(()=>{
    if(!window.mermaid) return false;
    window.mermaid.initialize({startOnLoad:false, securityLevel:"strict", theme:"base", themeVariables:_mermaidThemeVars(el)});
    const id="mmd-live-"+(_mermaidRenderSeq++);
    return window.mermaid.render(id, code).then(res=>{
      el.innerHTML=`<div class=mmd>${res.svg}</div>`;
      el.classList.add("mmd-live");
      return true;
    });
  }).catch(()=>false);
  const p=_mermaidQueue.then(run, run);
  _mermaidQueue=p.catch(()=>{});
  return p;
}
// Scans `root` (defaults to the whole document) for every diagram slot mdBlock()/
// ext_cr_detail.js's entryHtml() emitted — `.mmd-slot[data-mmd-src]`, holding the
// base64'd raw mermaid source — and upgrades each to the real render. Called once right
// after the HTML carrying them is injected (renderMdView/openText below, and
// ext_cr_detail.js's renderTimelineEntries), and again on every `themechange` so an
// already-live diagram repaints in the new palette instead of staying stuck in the old
// one (renderMermaid() is idempotent to call again — it just re-renders and replaces).
function upgradeMermaidIn(root){
  (root||document).querySelectorAll(".mmd-slot[data-mmd-src]").forEach(slot=>{
    const src=_mmdDecodeSrc(slot.getAttribute("data-mmd-src"));
    if(src) renderMermaid(src, slot);
  });
}
document.addEventListener("themechange", ()=>upgradeMermaidIn(document));

function ago(sec){sec=Math.max(0,sec|0);if(sec<60)return sec+"s ago";if(sec<3600)return(sec/60|0)+"m ago";if(sec<86400)return(sec/3600|0)+"h ago";return(sec/86400|0)+"d ago"}
function base(p){return (p||"").split("/").pop()}
const SRC={"claude-desktop":ico("desktop")+" Desktop","cli":ico('keyboard')+" CLI","sdk-cli":ico('gear')+" SDK","claude-vscode":ico('copy')+" VS Code","auggie":ico('diamond')+" Auggie","augment-vscode":ico('diamond')+" Augment (VS Code)","augment-cursor":ico('diamond')+" Augment (Cursor)"};
const srcLabel=v=>SRC[v]||v||"";
const CIRC=2*Math.PI*51; // progress-ring circumference

let sessions=[], searchResults=null, liveOnly=false;
// The sidebar's clock: set from /api/list's X-Server-Now header on every poll, so
// live/done here is computed from the SAME clock the detail pane uses (its `now`
// field, server-stamped too) -- never the browser's own Date.now(), which drifts on
// a phone/tablet over a tunnel or on any desktop with clock skew (conventions rule 5:
// server owns policy, client renders it -- one clock for liveness, not two).
let listNow=Date.now()/1000;   // seeded before the first poll lands; overwritten immediately after
const LIVE=300; // seconds since last activity a session stays "live" (5 min)
const EXT=[];   // feature modules (web/ext_*.js) push a fn(d); called at the end of every render
// Live terminal count for the sidebar's "Manage terminals" badge, read off /api/list's
// X-Term-Count response header (same header-not-body trick as X-Server-Now above -- see
// aitracker/server.py's _term_count() for why). null = the server omitted the header (terminal
// feature off, or gated off without TRACKER_AUTH) -- a feature module renders that as NO badge,
// never as "0". Server owns the policy; this file only carries the number, never re-derives it.
let termCount=null;
const SIDE_EXT=[];   // feature modules push a fn(); called after every SIDEBAR poll (loadSide),
                      // unlike EXT above which only fires while a session is selected (render(d))
function hl(text,q){
  const e=esc(text); if(!q)return e;
  const re=new RegExp("("+q.replace(/[.*+?^${}()|[\]\\]/g,"\\$&")+")","ig");
  return e.replace(re,"<b>$1</b>");
}
let selEntry=null;   // last list row seen for the selected session — pin it so a poll can't drop it
function renderSide(){
  const now=listNow;   // server clock (see listNow above) -- every live/done check below flows from this one value
  const sl=$("slist"), sc=sl?sl.scrollTop:0;   // preserve scroll: a background poll must not yank the list to the top
  if(searchResults!==null){       // search mode: show matches instead of the full list
    const q=$("q").value.trim();
    $("livecount").textContent=`${searchResults.length} match${searchResults.length==1?"":"es"}`;
    $("slist").innerHTML=searchResults.length?searchResults.map(s=>{
      const live=now-s.mtime<LIVE;
      return `<div class="sitem ${s.id===cur?'active':''}" onclick="pick('${s.id}')" title="${esc(s.title||'')}">`+
        `<div class=srow1><span class="dot ${live?'live':''}"></span><span class=nm>${s.agent?ico('agent')+' ':''}${esc(s.title||s.project||s.id.slice(0,8))}</span>`+
        `<span class=ren onclick="renameSession(event,'${s.id}')" title="Rename">${ico('edit')}</span></div>`+
        `<div class=smeta><span class=proj>${esc(s.project)}</span>${s.inQuery?' · <span class=smatch>your query</span>':''} · <span>${s.matches}×</span></div>`+
        (s.snippet?`<div class=ssnip>${hl(s.snippet,q)}</div>`:"")+
        `</div>`;
    }).join(""):`<div class=empty>no sessions match “${esc(q)}”</div>`;
    if(sl)sl.scrollTop=sc;
    return;
  }
  const liveN=sessions.filter(s=>now-s.mtime<LIVE).length;
  const lc=$("livecount");
  lc.innerHTML=liveOnly?`${liveN} live ${ico('close')}`:`${liveN} live`;
  lc.title=liveOnly?"Showing live only — click to show all":"Click to show live sessions only";
  lc.classList.toggle("on",liveOnly);
  const found=sessions.find(s=>s.id===cur); if(found)selEntry=found;
  let shown=liveOnly?sessions.filter(s=>now-s.mtime<LIVE):sessions;
  // never let the selected session fall off (top-N cap or live filter) — pin it so the selection persists
  if(cur && !shown.some(s=>s.id===cur) && selEntry && selEntry.id===cur) shown=[selEntry,...shown];
  // Nest each background-agent (SDK) session under its originating session (server attributes it
  // by worktree + who was live when it spawned). Orphans — no such parent in view — fall into a
  // per-repo/sandbox bucket so nothing is hidden. Both parent rows and buckets collapse by default.
  const shownIds=new Set(shown.map(s=>s.id));
  const kids={}, buckets={}, items=[];
  shown.forEach(s=>{
    // a pinned agent floats to the top like any pinned session — don't bury it in nesting/buckets
    if(!s.pinned && s.agent && s.parentId && shownIds.has(s.parentId)){ (kids[s.parentId]||(kids[s.parentId]=[])).push(s); return; }
    if(!s.pinned && s.agent && s.group){ (buckets[s.group]||(buckets[s.group]={key:s.group,label:s.groupLabel||s.group,kids:[]})).kids.push(s); return; }
    items.push({t:"s",mtime:s.mtime,s,pinned:s.pinned});
  });
  // parents carry their children; a live agent bubbles its parent up the recency sort. Collapse re-runs
  // of the same agent (same task) so the count isn't inflated — one row per task, ×N runs, newest opens.
  items.forEach(it=>{ if(it.t==="s" && kids[it.s.id]){ it.kids=collapseAgents(kids[it.s.id]);
    it.mtime=Math.max(it.mtime,...it.kids.map(k=>k.mtime)); }});
  Object.values(buckets).forEach(b=>{
    b.kids=collapseAgents(b.kids);
    b.mtime=Math.max(...b.kids.map(k=>k.mtime));
    b.live=b.kids.filter(k=>now-k.mtime<LIVE).length;
    items.push({t:"g",mtime:b.mtime,b,pinned:false});
  });
  items.sort((a,b)=>(b.pinned?1:0)-(a.pinned?1:0) || b.mtime-a.mtime);   // pinned first, then newest (matches the server)
  // Auto-expand the selected agent's container ONCE per selection change — covers page-load restore,
  // not just click, and uses the same `shown`-derived nesting the render does (so the live filter can't
  // point it at the wrong container). Fires once (guarded by autoExpandedFor) so the chevron stays
  // collapsible and this never persists — no localStorage growth from rendering.
  if(cur && cur!==autoExpandedFor){
    const cs=shown.find(x=>x.id===cur);
    if(cs && cs.agent){ const k=(cs.parentId&&shownIds.has(cs.parentId))?"sess:"+cs.parentId:cs.group; if(k)expandedGroups.add(k); }
    autoExpandedFor=cur;
  }
  // prune persisted keys for sessions/groups that no longer exist, so agrpOpen can't grow without bound
  const liveGroups=new Set(sessions.filter(s=>s.agent&&s.group).map(s=>s.group)), liveIds=new Set(sessions.map(s=>s.id));
  let pruned=false;
  for(const k of [...expandedGroups]){ if(!(k.startsWith("sess:")?liveIds.has(k.slice(5)):liveGroups.has(k))){ expandedGroups.delete(k); pruned=true; } }
  if(pruned) localStorage.setItem("agrpOpen",JSON.stringify([...expandedGroups]));
  const kidsBlock=ks=>`<div class=agrpkids>${ks.slice().sort((x,y)=>y.mtime-x.mtime).map(k=>sessionRow(k,now)).join("")}</div>`;
  const hasPin=items.some(x=>x.pinned); let _sec=null;   // Pinned / Recent section labels (only when there are pins)
  const secDiv=it=>{ if(!hasPin)return ""; const s=it.pinned?"pin":"recent"; if(s===_sec)return ""; _sec=s; return `<div class=secband>${s==="pin"?ico('pin')+" Pinned":"Recent"}</div>`; };
  $("slist").innerHTML=items.length?items.map(it=>{
    const _d=secDiv(it);
    if(it.t==="s"){
      if(!it.kids) return _d+sessionRow(it.s,now);
      const gk="sess:"+it.s.id, open=expandedGroups.has(gk);
      const liveK=it.kids.filter(k=>now-k.mtime<LIVE).length;
      return _d+sessionRow(it.s,now,{gk,open,n:it.kids.length,live:liveK})+(open?kidsBlock(it.kids):"");
    }
    const b=it.b, open=expandedGroups.has(b.key);
    return _d+`<div class="agrp ${open?'open':''}">`+
      `<div class=agrphdr onclick="toggleGroup('${encodeURIComponent(b.key)}')" title="${esc(b.key)}">`+
        `<span class=agrpchev>${open?ico('chevron-down'):ico('chevron')}</span><span class=agrpname>${ico('agent')} Agents · ${esc(b.label)}</span>`+
        `<span class=agrpn>${b.live?b.live+" live / ":""}${b.kids.length}</span></div>`+
      (open?kidsBlock(b.kids):"")+
      `</div>`;
  }).join(""):`<div class=empty>${liveOnly?"no live sessions":"no sessions"}</div>`;
  if(sl)sl.scrollTop=sc;
}
// one session row — shared by the flat list, agent-group children, and expandable parents.
// ex (optional) = {gk,open,n,live}: this session originated N agents; render an expander + count.
function sessionRow(s,now,ex){
  const live=now-s.mtime<LIVE;
  const label=s.title||s.project||s.id.slice(0,8);
  const bits=[`<span class=proj>${s.title?esc(s.project):s.id.slice(0,8)}</span>`];
  if(s.source)bits.push(srcLabel(s.source));
  bits.push(ago(now-s.mtime));
  const chev=ex?`<span class="agtoggle${ex.open?' open':''}" onclick="toggleGroup('${encodeURIComponent(ex.gk)}');event.stopPropagation()" title="${ex.open?'Collapse':'Expand'} agent sessions">${ico('agent')}</span>`:"";
  const kidchip=ex?` · <span class=agentbadge title="agent sessions this one spawned">${ico('agent')} ${ex.live?ex.live+" live / ":""}${ex.n} agent${ex.n==1?"":"s"}</span>`:"";
  // in-transcript background agents (Task/Workflow) running now — they spawn no separate session, so this is their only sidebar cue
  const bgchip=s.bg?` · <span class="agentbadge live" title="${s.bg} background agent${s.bg==1?'':'s'} running now">${ico('agent')} ${s.bg} running</span>`:"";
  // a parent row: clicking the title toggles its agents too (not just the agent-toggle button) while still opening it
  const onclick=ex?`pickToggle('${s.id}','${encodeURIComponent(ex.gk)}')`:`pick('${s.id}')`;
  const noteBadge=s.note_count?`<span class=notebadge title="${s.note_count} note${s.note_count==1?'':'s'}">${ico('note')}${s.note_count}</span>`:"";
  // open flag count (server-owned, from flags.json) — without it a flag on a session you aren't
  // looking at is invisible, which is how two of them sat unnoticed.
  const flagBadge=s.open_flags?`<span class=flagbadge title="${s.open_flags} open flag${s.open_flags==1?'':'s'}">${ico('flag')}${s.open_flags}</span>`:"";
  // end-state: waiting on your answer (wins, even while still live) > completed its last run.
  // "done" is gated to the live window (a session that JUST finished) — not every stale idle
  // session — so the checkmark marks fresh completions instead of flooding the list green.
  const status=s.waiting?"waiting":(s.ended&&live?"done":"");
  const statusBadge=status==="waiting"
    ?`<span class="statusbadge waiting" title="waiting for your answer — respond in the session">${ico('hourglass')} answer</span>`
    :status==="done"?`<span class="statusbadge done" title="completed its last run">${ico('check')} done</span>`:"";
  return `<div class="sitem ${s.id===cur?'active':''}${s.pinned?' pinned':''}${s.agent?' agentrow':''}${ex?' hasagents':''}${status?' '+status:''}${s.open_flags?' flagged':''}" onclick="${onclick}" title="${esc((s.prompt||s.title||'(no prompt)')+'\n'+(s.cwd||''))}">`+
    `<div class=srow1>${chev}<span class="dot ${live?'live':''}"></span><span class=nm>${s.agent?ico('agent')+' ':''}${esc(label)}</span>`+
    `${statusBadge}${flagBadge}${noteBadge}`+
    (s._runs>1?`<span class="agentbadge runs" title="ran ${s._runs}× — collapsed; opens the latest">×${s._runs}</span>`:"")+
    `<span class="pin${s.pinned?' on':''}" onclick="togglePin(event,'${s.id}')" title="${s.pinned?'Unpin':'Pin to top'}">${ico('pin')}</span>`+
    `<span class=ren onclick="renameSession(event,'${s.id}')" title="Rename this session">${ico('edit')}</span></div>`+
    `<div class=smeta>${s.agent?'<span class=agentbadge>'+ico('agent')+' Agent</span> · ':''}${bits.join(" · ")}${kidchip}${bgchip}</div></div>`;
}
// collapse agent sessions that are re-runs of the same task (first prompt) into one row, newest as
// representative, with _runs=N — so a finding re-executed 12× shows once, not twelve times.
function collapseAgents(arr){
  const by=new Map();
  for(const s of arr){
    const key=s.prompt||s.title||s.id, g=by.get(key);
    if(!g){ by.set(key,Object.assign({},s,{_runs:1})); }
    else { const r=g._runs+1; if(s.mtime>=g.mtime)Object.assign(g,s); g._runs=r; }
  }
  return [...by.values()];
}
let expandedGroups=new Set(JSON.parse(localStorage.getItem("agrpOpen")||"[]"));
let autoExpandedFor=null;   // last selection we auto-expanded a container for (fires once per change)
function toggleGroup(k){
  k=decodeURIComponent(k);
  if(expandedGroups.has(k))expandedGroups.delete(k); else expandedGroups.add(k);
  localStorage.setItem("agrpOpen",JSON.stringify([...expandedGroups]));
  renderSide();
}
// clicking an originating session's title both opens it and toggles its agent list
function pickToggle(id,encGk){
  const k=decodeURIComponent(encGk);
  if(expandedGroups.has(k))expandedGroups.delete(k); else expandedGroups.add(k);
  localStorage.setItem("agrpOpen",JSON.stringify([...expandedGroups]));
  pick(id);   // pick() re-renders
}
function toggleLiveOnly(){liveOnly=!liveOnly;renderSide();}
// In-flight guard: /api/list can be slow (cold cache, load). Without this, setInterval keeps
// firing every 5s regardless of whether the previous call finished, and slow calls stack up
// unboundedly, eating the browser's 6-socket-per-host budget until nothing else on the page can
// load (see the bug this guards against, described where the poller is registered). A single
// boolean caps loadSide() at 1 in-flight request — no backoff needed, since 1 is already small
// relative to the 6-socket budget and a plain guard recovers immediately once a call returns,
// slow or not. sideBusy is cleared in `finally` so a rejected/erroring fetch can't wedge it stuck.
let sideBusy=false;
async function loadSide(){
  if(sideBusy)return;
  sideBusy=true;
  try{
    const res=await fetch("/api/list");
    const t=res.headers.get("X-Server-Now");   // the same clock /api/session's `now` uses
    if(t)listNow=+t;
    const tc=res.headers.get("X-Term-Count");   // absent -> null -> no badge (see termCount above)
    termCount=tc!==null?+tc:null;
    sessions=await res.json();
  }catch(e){return}
  finally{sideBusy=false;}
  renderSide();
  SIDE_EXT.forEach(f=>{try{f()}catch(e){console.error("side ext render",e)}});
  loadFlags();   // flags were only fetched by poll(), i.e. never until a session was selected
}
function pick(id){$("sid").value=id;track();renderSide();closeDrawer();}   // renderSide auto-expands the selected agent's container; closeDrawer no-ops off-phone
// mobile Sessions drawer (phones only; CSS gates the affordances to ≤600px)
function toggleDrawer(){document.querySelector(".app").classList.toggle("draweropen");}
function closeDrawer(){document.querySelector(".app").classList.remove("draweropen");}
// ---- Background-work drawer (agents + shells, relocated off the main column) ----
let bgTab="agents";
function openBgDrawer(tab){ bgTab=tab||bgTab; const d=$("bgdrawer"); if(!d)return; d.setAttribute("data-tab",bgTab); d.classList.add("open"); const sc=$("bgscrim"); if(sc)sc.classList.add("show"); setBgTabUI(); }
function setBgTab(tab){ bgTab=tab; const d=$("bgdrawer"); if(d)d.setAttribute("data-tab",tab); setBgTabUI(); }
function setBgTabUI(){ const a=$("bgtab_agents"),s=$("bgtab_shells"); if(a)a.classList.toggle("on",bgTab==="agents"); if(s)s.classList.toggle("on",bgTab==="shells"); }
function closeBgDrawer(){ const d=$("bgdrawer"); if(d)d.classList.remove("open"); const sc=$("bgscrim"); if(sc)sc.classList.remove("show"); }
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

// in-session search — find text across THIS session's narration/prompts/files/commands/todos.
// Server searches the full parsed detail (both providers, one endpoint); each hit carries full
// text so a click opens the existing modal (diff/output for files/commands, text otherwise).
let dHits=null, dSid=null, dTimer=null;
const DKIND={narration:ico('chat')+" narration",prompt:ico('keyboard')+" prompt",file:ico('file')+" file",command:"$ command",todo:ico('circle')+" todo"};
function doDetailSearch(){ clearTimeout(dTimer); dTimer=setTimeout(runDetailSearch,180); }
async function runDetailSearch(){
  const q=$("dq").value.trim();
  $("dqclear").style.display=q?"":"none";
  if(!q||!cur){ dHits=null; $("dsc").textContent=""; $("dresults").style.display="none"; return; }
  $("dresults").style.display="";
  $("dresults").innerHTML="<div class=empty>searching…</div>";
  try{ const r=await(await fetch(`/api/session_search?id=${encodeURIComponent(cur)}&q=${encodeURIComponent(q)}`)).json(); dHits=r.hits||[]; }
  catch(e){ dHits=[]; }
  renderDetailSearch(q);
}
function renderDetailSearch(q){
  if(dHits===null){ $("dsc").textContent=""; $("dresults").style.display="none"; return; }
  $("dresults").style.display="";
  $("dsc").textContent=dHits.length?`${dHits.length} match${dHits.length==1?"":"es"}`:"";
  if(!dHits.length){ $("dresults").innerHTML=`<div class=empty>no matches for “${esc(q)}” in this session</div>`; return; }
  $("dresults").innerHTML=dHits.map((h,i)=>
      `<div class="item dsr clk" onclick="openHit(${i})"><span class=dsrk>${DKIND[h.kind]||h.kind}</span>`+
      `<span class=dsrt>${h.t?ago(Math.floor(listNow)-Date.parse(h.t)/1000):""}</span>`+
      `<div class=dsrsnip>${dhl(h.snippet,q)}</div><span class=chev>›</span></div>`).join("");
}
function openHit(i){
  const h=dHits[i]; if(!h)return;
  if(h.kind==="file"){ const j=curFiles.findIndex(f=>f.path===h.text); if(j>=0)return openDiff(j); }
  if(h.kind==="command"){ const j=curCmds.findIndex(c=>c.cmd===h.text); if(j>=0)return openCmd(j); }
  openText(DKIND[h.kind]?DKIND[h.kind].replace(/^(?:<svg[\s\S]*?<\/svg>|\S+)\s*/,""):h.kind, h.t?tago(h.t):"", h.text);
}
function clearDetailSearch(){ $("dq").value=""; dHits=null; $("dqclear").style.display="none"; $("dsc").textContent=""; $("dresults").style.display="none"; }
function toggleDetailSearch(){   // header 🔍 reveals/hides the full-width search card, like the flag card
  const c=$("dsearchcard"); if(!c)return;
  const show=c.style.display==="none";
  c.style.display=show?"":"none";
  const b=$("dsearchbtn"); if(b)b.classList.toggle("on",show);
  if(show){ c.scrollIntoView({behavior:"smooth",block:"nearest"}); $("dq").focus(); }
  else clearDetailSearch();
}
function dhl(s,q){   // highlight matched terms inside an escaped snippet
  let out=esc(s);
  q.trim().split(/\s+/).forEach(t=>{ if(t){ const re=new RegExp("("+t.replace(/[.*+?^${}()|[\]\\]/g,"\\$&")+")","ig"); out=out.replace(re,"<mark>$1</mark>"); } });
  return out;
}
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
async function togglePin(e,id){
  e.stopPropagation();
  const s=sessions.find(x=>x.id===id)||{};
  await fetch("/api/pin",{method:"POST",headers:{"Content-Type":"application/json"},
    body:JSON.stringify({session:id,pinned:!s.pinned})});
  await loadSide();   // server re-sorts pinned-first; scroll is preserved by renderSide
}
async function start(){
  const _hl=$("hostlbl");if(_hl)_hl.textContent=location.host;   // real host, not the baked "localhost:8790" (matters on phone/tunnel)
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
function setBell(){const b=$("bell");if(b){b.innerHTML=soundOn?ico("bell"):ico("bell-off");b.title="Completion sound: "+(soundOn?"on":"muted");}}
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
  el.innerHTML=`<span class=tk>${ico('check')}</span><div><div class=tt>${esc(msg)}</div>${sub?`<div class=tsub>${esc(sub)}</div>`:""}</div>`;
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
// Same in-flight guard as loadSide's sideBusy, kept as a separate flag: poll() (session detail,
// every 2s) and loadSide() (session list, every 5s) hit different endpoints and must not block
// each other — a slow /api/list must not stall /api/session refreshes, or vice versa. Cleared in
// `finally` so a rejected fetch can't leave poll() permanently unable to start again.
// pollBusy only limits how many fetches are in flight at once — it does NOT prove the fetch that
// eventually resolves is still the one we want to paint. Selecting a new session (pick->track->
// poll) while a previous poll's fetch is still in flight can't be stopped, so instead every call
// is tagged with the session id it was issued for + a monotonic sequence number; the response is
// applied only if BOTH still match when it lands (id: are we still on that session; seq: is this
// the latest request issued, so an out-of-order reply for an older request on the SAME id can't
// clobber a newer one either). Anything else is a stale reply and is silently dropped.
let pollBusy=false, pollSeq=0;
async function poll(){
  if(!cur||pollBusy)return;
  pollBusy=true;
  const seq=++pollSeq, id=cur;
  let d;
  try{d=await(await fetch("/api/session?id="+encodeURIComponent(id))).json()}
  catch(e){return}
  finally{pollBusy=false;}
  if(seq!==pollSeq||id!==cur)return;   // superseded by a newer poll, or the selection moved on — discard
  if(d.error){$("hmeta").innerHTML=`<span class=dot></span> ${esc(d.error)}: ${esc(cur)}`;return}
  lastData=d;render(d);loadFlags();checkCompletions(d);
}
const KICON={commit:ico('branch'),test:ico('check'),install:ico('download'),build:ico('hammer'),git:ico('branch'),cmd:"$"};
// Fork lineage banners (registry.py: d.continued_as/d.continued_from, on every provider's
// detail dict). index.html has no static slot for this — it's an optional, provider-
// agnostic feature — so the two banner elements are created once here and reused on every
// render, inserted right after #srcnote (near the top of the detail view, same spot as the
// other session-level notices). #forkas: this session was forked — the live work moved to
// a new session, click to follow it (reuses `pick()`, the same nav the sidebar uses — no
// second navigation path). #forkfrom: this session IS a fork of another one — a quieter
// line with a link back. The server ships ids only (not titles, see registry.parse_any's
// comment); the label falls back to the id's short form when the target isn't in the
// already-polled `sessions` list yet.
// Resolve a session id to its display title from the top-level `sessions` list,
// falling back to the id's short form when the target isn't in it yet. Shared with
// Control Room, which used to keep its own copy of this lookup.
function sessionLabel(id){const hit=sessions.find(s=>s.id===id);return hit?(hit.title||hit.project||id.slice(0,8)):id.slice(0,8);}
function renderForkLinks(d){
  let as=$("forkas"), from=$("forkfrom");
  if(!as){
    as=document.createElement("div");
    as.id="forkas"; as.className="forkbanner"; as.style.display="none";
    $("srcnote").insertAdjacentElement("afterend",as);
  }
  if(!from){
    from=document.createElement("div");
    from.id="forkfrom"; from.className="forkbanner quiet"; from.style.display="none";
    as.insertAdjacentElement("afterend",from);
  }
  const label=sessionLabel;
  if(d.continued_as){
    const cid=d.continued_as;
    as.style.display="flex";
    as.onclick=()=>pick(cid);
    as.innerHTML='<span class=dot></span><div style="min-width:0;flex:1"><div class=lbl>Continued in a new session</div>'+
      `<div class=txt>Resumed as a fork — the live work is in <b>${esc(label(cid))}</b>.</div></div><span class=chev>open ›</span>`;
  }else{
    as.style.display="none"; as.onclick=null;
  }
  if(d.continued_from){
    const pid=d.continued_from;
    from.style.display="flex";
    from.onclick=null;
    from.innerHTML=`<span class=txt>${ico('return')} Forked from <span class="link blue" onclick="pick('${pid}')">${esc(label(pid))}</span></span>`;
  }else{
    from.style.display="none";
  }
}

function render(d){
  if(dSid!==cur){   // switching sessions closes the search card and drops stale results
    clearDetailSearch();
    const c=$("dsearchcard"); if(c)c.style.display="none";
    const sb=$("dsearchbtn"); if(sb)sb.classList.remove("on");
    dSid=cur;
  }
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

  // title + active badge. Server-owned `waiting` (an unanswered question) wins over both
  // live and idle — the same precedence the sidebar hourglass icon uses. A session blocked on the user
  // isn't idle, and calling it "idle 26m ago" is what hid that it needed an answer.
  $("htitle").textContent=title;
  $("activebadge").style.display="inline-flex";
  if(d.waiting){
    $("activebadge").innerHTML='<span class="dot amber"></span>'+ico("hourglass")+' waiting on you · '+ago(idle).replace(" ago","");
    $("activebadge").style.color="var(--amber)";$("activebadge").style.background="var(--amber-deep)";$("activebadge").style.borderColor="var(--amber-line)";
  }else if(!live){
    $("activebadge").innerHTML='<span class=dot></span>idle '+ago(idle);
    $("activebadge").style.color="var(--muted)";$("activebadge").style.background="var(--chipbg)";$("activebadge").style.borderColor="var(--line3)";
  }else{
    $("activebadge").innerHTML='<span class="dot live"></span>active';
    $("activebadge").style.color="var(--green)";$("activebadge").style.background="var(--green-deep)";$("activebadge").style.borderColor="var(--green-line)";
  }

  // meta line
  const meta=[];
  if(m.cwd)meta.push(ico('folder')+" "+esc(base(m.cwd)));
  if(m.gitBranch)meta.push(ico('branch')+" "+esc(m.gitBranch));
  if(src)meta.push(ico('keyboard')+" "+src);
  meta.push(`${(d.tokens.in/1000|0)}k in / ${(d.tokens.out/1000|0)}k out`);
  if(m.version)meta.push("v"+esc(m.version));
  $("hmeta").innerHTML=meta.map(x=>`<span>${x}</span>`).join("");

  const chip=(n,v,cls,tgt)=>v?`<span class="chip ${cls||''} ${tgt?'clk':''}"${tgt?` onclick="flashTo('${tgt}')"`:''}><span class=lbl>${n}</span><b>${v}</b></span>`:"";
  // agents & shells → open the right-side Background-work drawer (both already on the shared shape)
  const bgchip=(n,v,tab,run)=>v?`<span class="chip bgchip clk" onclick="openBgDrawer('${tab}')" title="Open background ${tab}"><span class=lbl>${n}</span><b>${run?run+" / ":""}${v}</b></span>`:"";
  const nAgents=(d.agents_bg||[]).length+(d.agent_sessions||[]).length, nAgentsRun=(d.agents_bg||[]).filter(a=>a.running).length+(d.agent_sessions||[]).filter(a=>a.running).length;
  const nShells=(d.shells||[]).length, nShellsRun=(d.shells||[]).filter(s=>s.running).length;
  $("chips").innerHTML=
    chip(ico('check')+" done",`${c.done}/${c.todos}`,"good","card_todos")+chip(ico('plus')+" created",c.created,"blue","card_files")+chip(ico('edit')+" edited",c.edited,"","card_files")+
    chip(ico('eye')+" read",c.read,"","card_files")+chip(ico('branch')+" commits",c.commits,"","card_cmds")+chip("tests",c.tests,"","card_cmds")+
    chip(ico('x')+" failed",c.tests_failed,"bad","card_cmds")+chip(ico('alert')+" errors",c.errors,"bad","card_cmds")+
    bgchip(ico('agent')+" agents",nAgents,"agents",nAgentsRun)+bgchip(ico('keyboard')+" shells",nShells,"shells",nShellsRun)+chip("searches",c.searches);

  // background agents (click to read full narration)
  // background agents — running shown; finished tucked behind a disclosure
  const bg=d.agents_bg||[];
  const asx=d.agent_sessions||[];   // spawned SDK/worktree agent SESSIONS — open one in the main view
  curAgents=bg;
  $("bgpanel").style.display=(bg.length||asx.length)?"flex":"none";
  if(bg.length||asx.length){
    const runN=bg.filter(a=>a.running).length+asx.filter(a=>a.running).length;
    $("bgc").textContent=runN?`${runN} running`:"all finished";
    let html="";
    if(asx.length){
      // live agent sessions shown; finished ones tucked behind a disclosure (they can number in the dozens)
      const asCard=a=>
        `<div class="agent clk agentrow" onclick="pick('${a.id}')" title="Open this agent session${a.runs>1?' ('+a.runs+' runs — opens the latest)':''}">`+
        `<div class=top><span class="dot ${a.running?'live':''}"></span><span class=nm>${ico('agent')} ${esc(a.title||a.wt||a.id.slice(0,8))}</span>`+
        (a.runs>1?` <span class=tag title="ran ${a.runs}× — collapsed">×${a.runs}</span>`:"")+
        (a.wt?` <span class=tag>${esc(a.wt.slice(0,16))}</span>`:"")+`<span class=chev>open ›</span></div>`+
        `<div class=ft><span>agent session</span><span>·</span><span style=color:${a.running?'var(--green2)':'var(--dim)'}>${a.running?'running':'done'}</span>`+
        `${a.mtime?"<span>·</span><span>"+ago(d.now-a.mtime)+"</span>":""}</div></div>`;
      const asRun=asx.filter(a=>a.running), asDone=asx.filter(a=>!a.running);
      html+=asRun.map(asCard).join("");
      if(asDone.length){
        html+=`<div class=disclosure onclick=toggleAgentSessDone()>${showAgentSessDone?ico('chevron-down')+" Hide":ico('chevron')+" Show"} ${asDone.length} finished agent session${asDone.length==1?"":"s"}</div>`;
        if(showAgentSessDone)html+=asDone.map(asCard).join("");
      }
    }
    const card=(a,i)=>
      `<div class="agent clk" onclick="openAgent(${i})"><div class=top><span class="dot ${a.running?'amber':''}"></span><span class=nm>${esc(a.task||a.id)}</span>`+
      (a.wf?` <span class=tag>${esc(a.wf.slice(0,12))}</span>`:"")+`<span class=chev>›</span></div>`+
      `<div class=last>${esc(a.last||"")}</div>`+
      `<div class=ft><span>${a.tools} tools</span><span>·</span><span style=color:${a.running?'var(--amber)':'var(--dim)'}>${a.running?'running':'done'}</span>`+
      `${a.ts?"<span>·</span><span>"+ago(d.now-Date.parse(a.ts)/1000)+"</span>":""}</div></div>`;
    const run=[],done=[];
    bg.forEach((a,i)=>(a.running?run:done).push(card(a,i)));
    if(bg.length) html+=run.length?run.join(""):(asx.length?"":"<div class=empty>No agents running right now.</div>");
    if(done.length){
      html+=`<div class=disclosure onclick=toggleAgentsDone()>${showAgentsDone?ico('chevron-down')+" Hide":ico('chevron')+" Show"} ${done.length} finished</div>`;
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
      `<div class=ft><span>${esc(s.id)}</span><span>·</span><span style=color:${s.running?'var(--amber)':'var(--dim)'}>${s.running?'running':'done'}</span>`+
      `${s.ts?"<span>·</span><span>"+ago(d.now-Date.parse(s.ts)/1000)+"</span>":""}</div></div>`;
    const run=[],done=[];
    shl.forEach((s,i)=>(s.running?run:done).push(card(s,i)));
    let html=run.length?run.join(""):"<div class=empty>No shells running right now.</div>";
    if(done.length){
      html+=`<div class=disclosure onclick=toggleShellsDone()>${showShellsDone?ico('chevron-down')+" Hide":ico('chevron')+" Show"} ${done.length} finished</div>`;
      if(showShellsDone)html+=done.join("");
    }
    $("sh").innerHTML=html;
  }

  $("srcnote").style.display=d.note?"block":"none";
  $("srcnote").textContent=d.note||"";

  renderForkLinks(d);   // fork lineage banner(s) — see function def for why

  // per-session notes stack (plan-ahead notes the user wrote, newest-first display)
  renderNotes(d.notes||[]);

  // summary (markdown + click to read full)
  const ov=d.overview||{};
  curOv=ov;
  $("ov_goal").innerHTML=md(ov.goal||"—");
  $("ov_now").innerHTML=ico('play')+" "+md(ov.now||(live?"working…":"idle"));
  $("ov_sofar").innerHTML=md(ov.sofar||"—");
  const ocm=ov.commits||[];
  $("ov_crow").style.display=ocm.length?"flex":"none";
  $("ov_commits").textContent=ocm.join("  ·  ");

  // now banner: live → what it's working on (blue, blinking cursor); idle → the last thing
  // it completed (green, no cursor); waiting → it stopped ON a question, so neither label
  // fits ("Completed last task" reads as finished when it's actually blocked on you).
  $("nowbanner").style.display=ov.now?"flex":"none";
  $("nowbanner").classList.toggle("done",!live&&!d.waiting);
  $("nowbanner").classList.toggle("waiting",!!d.waiting);
  const nowClean=(ov.now||"").replace(/^(?:▶|⚙|✓|⧖)\s+/,"").replace(/^Idle — last said:\s*/,"");
  $("nowlbl").textContent=d.waiting?"Waiting on your answer":(live?"Now working on":"Completed last task");
  $("nowtext").innerHTML=(d.waiting?ico('hourglass')+' ':live?ico('play')+" ":ico('check')+" ")+md(nowClean)+(live&&!d.waiting?'<span class=cursor>▍</span>':"");
  // the last file touched — click jumps to the Files panel and opens its diff
  const lastFile=(d.files||[])[0];
  $("nowfile").style.display=lastFile?"":"none";
  if(lastFile)$("nowfile").innerHTML=`${ico('file')} <span class=nfn>${esc(base(lastFile.path))}</span>`;

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
  winList("prs", prs, (p,i)=>{
    const st=p.state||"";  // "merged"/"closed" when the session's logs revealed it; else open
    const badge=st?` <span class="prstate ${st}">${st}</span>`:"";
    const atag=p.agent?' <span class=agenttag title="opened by a background agent">'+ico('agent')+' agent</span>':'';
    return `<div class="item prrow"><a class=prlink href="${esc(p.url)}" target=_blank rel=noopener title="${esc(p.url)}">`+
    `<span class="kind ${p.created?'new':''}">${p.created?'created':'worked on'}</span>${badge}${atag} `+
    `<b>${esc((p.repo?p.repo+' ':'')+'#'+p.num)}</b><span class=prurl>${esc(p.url)}</span>`+
    `<span class=prtime>${p.t?ago(d.now-Date.parse(p.t)/1000):""}</span><span class=chev>${st||'open'} ›</span></a></div>`;},
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
      ? `<div class="decans open">${ico('hourglass')} awaiting your answer — decide in the session</div>`
      : `<div class=decans><span class=deck>${ico('check')} decided</span> ${md(x.answer||"")}</div>`;
    return `<div class="decitem${x.open?' isopen':''}">${qs}${foot}`+
           `<div class=dectime>${x.t?ago(d.now-Date.parse(x.t)/1000):""}</div></div>`;
  }).join(""):"<div class=empty>no questions asked</div>";

  // todos
  const td=d.todos||[];
  const order={completed:0,in_progress:1,pending:2};
  const sorted=[...td].sort((a,b)=>(order[a.status]??3)-(order[b.status]??3));
  const TICON={completed:ico('check'),in_progress:ico('play'),pending:ico('circle')};
  $("todoc").textContent=td.length?c.done+"/"+td.length:"";
  curTodos=sorted;
  winList("todos", sorted, (t,i)=>
    `<div class="todo t-${t.status} clk" onclick="openTodo(${i})"><span class=ic>${TICON[t.status]||ico('circle')}</span><span class=tx>${md(t.content)}</span></div>`, "no todos in this session");

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
    `<div class="item filerow" onclick="openDiff(${i})" title="View diff"><div class=fpath><span class="kind ${f.created?'new':''}">${f.created?'created':'edited'}</span>${f.agent?' <span class=agenttag title="edited by a background agent">'+ico('agent')+' agent</span>':''} <b>${esc(base(f.path))}</b><span class=chev>diff ›</span></div>`+
    `<div class="muted mono" style=font-size:11px;margin-top:3px>${esc(f.path.replace("/"+base(f.path),""))} · ${f.ops}× · ${ago(d.now-Date.parse(f.last)/1000)}</div></div>`, "no files written yet");

  // commands (click to see output)
  curCmds=d.commands||[];
  $("cmdc").textContent=curCmds.length||"";
  winList("cmds", curCmds, (x,i)=>
    `<div class="item clk" onclick="openCmd(${i})"><span class="${x.ok?'ok':'bad'}">${x.ok?ico('check'):ico('x')}</span> <span class=muted>${KICON[x.kind]||'$'}</span> `+
    `<span class="cmd mono">${esc(x.cmd)}</span> <span class=chev style=float:right;color:var(--dim)>output ›</span></div>`, "—");

  syncModal();   // keep an open narration/request modal live with this poll

  EXT.forEach(f=>{try{f(d)}catch(e){console.error("ext render",e)}});
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
           btn.innerHTML=diffMode==="md"?ico('layout')+" Diff":ico('layout')+" Rendered"; }
  const ab=$("diffall");   // expand-all only makes sense in diff mode with edits to expand
  if(ab){ ab.style.display=(diffMode==="diff"&&curDiffOps.length)?"":"none";
          ab.innerHTML=diffAllExpanded?ico('expand-vertical')+" Collapse":ico('expand-vertical')+" Expand all"; }
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
         `${dir==='up'?ico('arrow-up'):ico('arrow-down')} ${n} more line${n===1?'':'s'} ${dir==='up'?'above':'below'}</div>`;
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
  upgradeMermaidIn($("diffbody"));
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
  curModal={open:open,i:i,n:n,fromEnd:n-1-i,len:opts.len||(()=>n),live:!!opts.live,refresh:opts.refresh};
  const pos=n>1?(i+1)+" / "+n:"";
  const a=$("msgnav"), b=$("diffnav");
  if(a)a.textContent=pos; if(b)b.textContent=pos;
}
function navModal(d){ if(!curModal)return; const j=curModal.i+d; if(j>=0&&j<curModal.n) curModal.open(j); }
function navFirst(){ if(curModal&&curModal.i>0) curModal.open(0); }   // jump to the current/latest entry (index 0 = newest)
// Keep an open text modal in sync with the 2s poll — re-render the entry being read
// with fresh data (content, "time ago", the N/total counter). Pinned by distance-
// from-end so prepended entries don't yank it, EXCEPT when they were on the newest
// (i=0) where it follows the latest, like a chat sticking to the top. Called from
// render(); only the in-memory text modal opts in (fetch-based ones would re-fetch).
function syncModal(){
  if(!curModal||!curModal.live)return;
  if($("msgmodal").style.display!=="flex")return;
  if(curModal.refresh){curModal.refresh();return;}   // fetch-based (agent/shell): re-fetch quietly
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
  upgradeMermaidIn($("msgbody"));
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
// the last-file chip in the banner → scroll to the Files panel, flash it, open the newest file's diff
function openLastFile(e){
  if(e) e.stopPropagation();            // don't also trigger the banner's openNow
  if(!curFiles.length) return;
  const el=$("card_files");
  if(el){ el.scrollIntoView({behavior:"smooth", block:"center"});
          el.classList.remove("flash"); void el.offsetWidth; el.classList.add("flash");
          setTimeout(()=>el.classList.remove("flash"), 1500); }
  openDiff(0);                          // curFiles[0] = most recently updated file
}
function openReq(i){const r=curReqs[i]; if(!r)return; _setNav(openReq,i,curReqs.length,{len:()=>curReqs.length,live:true}); openText("Prompt",tago(r.t),r.text);}
async function openCmd(i){
  const x=curCmds[i]; if(!x||!cur)return;
  _setNav(openCmd,i,curCmds.length);
  $("msgtitle").textContent="Command";
  $("msgwhen").textContent=tago(x.t);
  $("msgbody").className="msgbody cmdmode";
  $("msgbody").innerHTML=`<div class=cmdcode><span class="${x.ok?'ok':'bad'}">${x.ok?ico('check'):ico('x')}</span> ${esc(x.cmd)}</div><div class=empty>loading output…</div>`;
  $("msgmodal").style.display="flex";
  let d;
  try{d=await(await fetch(`/api/output?id=${encodeURIComponent(cur)}&cmd=${encodeURIComponent(x.id)}`)).json()}
  catch(e){d={}}
  $("msgbody").innerHTML=`<div class=cmdcode><span class="${x.ok?'ok':'bad'}">${x.ok?ico('check'):ico('x')}</span> ${esc(d.cmd||x.cmd)}</div>`+
    (d.out?`<pre class=cmdout>${esc(d.out)}</pre>`:"<div class=empty>no output captured</div>");
}
let curShells=[], curAgents=[], curTodos=[];
let showAgentsDone=false, showShellsDone=false, showAgentSessDone=false;
function toggleAgentsDone(){showAgentsDone=!showAgentsDone; if(lastData)render(lastData);}
function toggleShellsDone(){showShellsDone=!showShellsDone; if(lastData)render(lastData);}
function toggleAgentSessDone(){showAgentSessDone=!showAgentSessDone; if(lastData)render(lastData);}
function openTodo(i){
  const t=curTodos[i]; if(!t)return;
  _setNav(openTodo,i,curTodos.length);
  openText("Task",t.status,"**"+(t.content||"")+"**"+(t.desc?"\n\n"+t.desc:""));
}
async function openShell(i,quiet){
  const s=curShells[i]; if(!s||!cur)return;
  _setNav(openShell,i,curShells.length,{live:!!s.running,refresh:()=>openShell(i,true)});
  const body=$("msgbody"), st=quiet?body.scrollTop:0;
  $("msgtitle").textContent="Shell · "+s.id;
  $("msgwhen").textContent=(s.running?"running":"done")+(s.ts?" · "+tago(s.ts):"");
  $("msgbody").className="msgbody cmdmode";
  if(!quiet)$("msgbody").innerHTML=`<div class=cmdcode>${esc(s.cmd)}</div><div class=empty>loading output…</div>`;
  $("msgmodal").style.display="flex";
  let d;try{d=await(await fetch(`/api/shell?id=${encodeURIComponent(cur)}&shell=${encodeURIComponent(s.id)}`)).json()}catch(e){d={}}
  $("msgbody").innerHTML=`<div class=cmdcode>${esc(d.cmd||s.cmd)}</div>`+
    (d.out?`<pre class=cmdout>${esc(d.out)}</pre>`:"<div class=empty>no output yet</div>");
  if(quiet)body.scrollTop=st;
}
async function openAgent(i,quiet){
  const a=curAgents[i]; if(!a||!cur)return;
  _setNav(openAgent,i,curAgents.length,{live:!!a.running,refresh:()=>openAgent(i,true)});
  const body=$("msgbody"), st=quiet?body.scrollTop:0;
  $("msgtitle").textContent="Agent";
  $("msgwhen").textContent=(a.running?"running":"done")+(a.ts?" · "+tago(a.ts):"");
  $("msgbody").className="msgbody";
  if(!quiet)$("msgbody").innerHTML="<div class=empty>loading…</div>";
  $("msgmodal").style.display="flex";
  let d;try{d=await(await fetch(`/api/agent?id=${encodeURIComponent(cur)}&agent=${encodeURIComponent(a.aid||a.id)}`)).json()}catch(e){d={}}
  $("msgbody").innerHTML=(d.task?`<div class=cmdcode>${esc(d.task)}</div>`:"")+
    `<div class="muted mono" style=margin-bottom:10px>${d.tools||0} tool calls · ${d.running?'running':'done'}</div>`+
    (d.narration?md(d.narration):"<div class=empty>no narration recorded</div>");
  if(quiet)body.scrollTop=st;
}
function closeMsg(){$("msgmodal").style.display="none";}
function copyModal(bodyId,btn){
  const el=$(bodyId); if(!el)return;
  const text=el.innerText||el.textContent||"";
  const done=()=>{if(btn){const o=btn.innerHTML;btn.innerHTML=ico('check')+" Copied";setTimeout(()=>btn.innerHTML=o,1200);}};
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
// per-code-block copy button (like docs sites) — copies just that block's raw text
function copyCode(btn){
  const code=btn.parentNode.querySelector("code")||btn.parentNode.querySelector(".mdpre");
  if(!code)return;
  const text=code.innerText||code.textContent||"";
  const done=()=>{const o=btn.innerHTML;btn.classList.add("ok");btn.innerHTML=ico('check')+" Copied";setTimeout(()=>{btn.innerHTML=o;btn.classList.remove("ok");},1200);};
  if(navigator.clipboard&&navigator.clipboard.writeText){navigator.clipboard.writeText(text).then(done).catch(()=>fallbackCopy(code,done));}
  else fallbackCopy(code,done);
}
function popOut(titleId,bodyId){
  const body=$(bodyId); if(!body)return;
  const title=($(titleId)&&$(titleId).textContent)||"Tracker";
  const head=[...document.querySelectorAll("style, link[rel=stylesheet]")].map(e=>e.outerHTML).join("");
  const w=window.open("","_blank");
  if(!w){alert("Popup blocked — allow popups for this page to open in a new tab.");return;}
  const theme=document.documentElement.classList.contains("light")?" class=light":"";   // carry dark/light into the new tab
  w.document.write(
    `<!doctype html><html${theme}><head><meta charset=utf-8>`+
    `<meta name=viewport content="width=device-width, initial-scale=1">`+   // else mobile renders the tab at desktop width
    `<title>${esc(title)}</title>${head}`+
    `</head>`+
    `<body><div class=pw><h1>${esc(title)}</h1><div class="${body.className}" style="overflow:visible;max-height:none">${body.innerHTML}</div></div></body></html>`);
  w.document.close();
  w.focus();   // move keyboard focus to the popped-out tab, not the parent window
}
function flashTo(id){
  const el=$(id); if(!el||el.style.display==="none")return;
  el.scrollIntoView({behavior:"smooth",block:"start"});
  el.classList.remove("flash"); void el.offsetWidth; el.classList.add("flash");
  setTimeout(()=>el.classList.remove("flash"),1400);
}
document.addEventListener("keydown",e=>{if(e.key==="Escape"){closeDiff();closeMsg();closeBgDrawer();}});
// ---- per-session notes stack ----
// What the server says will actually happen to a pushed note — never guessed here.
// "turn" = live, its next turn-end delivers; "wake" = idle, waits for the next prompt
// or resume; "none" = this tool has no drain hook at all.
const PUSH_SAYS={
  turn:{toast:"Queued — lands when the session finishes this turn",
        tip:"Queued — the session picks it up when it finishes this turn. Click to un-queue.",
        chip:ico('hourglass')+" queued"},
  wake:{toast:"Queued — this session is idle, so it lands the next time it runs",
        tip:"Queued — this session is idle. It has no turn to finish, so the note lands the next time you prompt it or resume it. Click to un-queue.",
        chip:ico('hourglass')+" queued · on wake"},
  none:{toast:"Queued — this tool can't auto-deliver, use copy",
        tip:"Queued, but this tool has no hook to deliver it — use copy. Click to un-queue.",
        chip:ico('hourglass')+" queued · copy it"}};
function pushSays(){return PUSH_SAYS[(lastData&&lastData.push_when)||"turn"]||PUSH_SAYS.turn}
function renderNotes(notes){
  const el=$("notes_list"), nc=$("notec");
  if(!el)return;
  nc.textContent=notes.length||"";
  const says=pushSays();
  // display newest-first (server stores in append order; reverse for display)
  const rev=[...notes].reverse();
  el.innerHTML=rev.length?rev.map((n,ri)=>{
    const idx=notes.length-1-ri;   // actual index in the server's array (for delete)
    const push=n.pushed
      ?`<span class="link amber" onclick="pushNote(${idx})" title="${esc(says.tip)}">${says.chip}</span>`
      :`<span class="link green" onclick="pushNote(${idx})" title="Send this into the live session">${ico('play')} push</span>`;
    return `<div class="noteitem${n.pushed?" queued":""}">`+
      `<div class=ntxt>${esc(n.text||"")}</div>`+
      `<div class=nft>`+
        `<span class="link blue" onclick="copyNote(${idx})" title="Copy to clipboard">${ico('copy')} copy</span>`+
        push+
        `<span class="link grey" onclick="removeNote(${idx})">${ico('close')} remove</span>`+
      `</div></div>`;
  }).join(""):`<div class=empty>no notes yet</div>`;
}
async function addNote(){
  if(!cur){alert("Pick a session first");return}
  const inp=$("noteinput");
  const text=(inp.value||"").trim();
  if(!text)return;
  const r=await fetch("/api/notes",{method:"POST",headers:{"Content-Type":"application/json"},
    body:JSON.stringify({session:cur,text})});
  if(r.ok){inp.value="";if(lastData)lastData.notes=(await r.json()).notes||[];renderNotes(lastData.notes||[]);renderSide();}
}
async function removeNote(idx){
  if(!cur)return;
  const r=await fetch("/api/notes/delete",{method:"POST",headers:{"Content-Type":"application/json"},
    body:JSON.stringify({session:cur,index:idx})});
  if(r.ok){const j=await r.json();if(lastData)lastData.notes=j.notes||[];renderNotes(lastData.notes||[]);renderSide();}
}
async function pushNote(idx){
  if(!cur)return;
  const r=await fetch("/api/notes/push",{method:"POST",headers:{"Content-Type":"application/json"},
    body:JSON.stringify({session:cur,index:idx})});
  if(!r.ok)return;
  const j=await r.json();
  if(lastData)lastData.notes=j.notes||[];
  renderNotes(lastData?lastData.notes||[]:[]);renderSide();
  const now=(j.notes||[])[idx];
  if(now&&now.pushed) toast(pushSays().toast,"");
}
function copyNote(idx){
  if(!lastData)return;
  const txt=((lastData.notes||[])[idx]||{}).text||"";
  if(!txt)return;
  const done=()=>{};
  if(navigator.clipboard){navigator.clipboard.writeText(txt).catch(()=>{});}
  else{const el=document.createElement("textarea");el.value=txt;document.body.appendChild(el);el.select();try{document.execCommand("copy");}catch(e){}document.body.removeChild(el);}
  toast("Note copied","");
}
let flags=[], flagRevealedFor=null;   // which session we've already auto-revealed the panel for
async function loadFlags(){try{flags=await(await fetch("/api/flags")).json()}catch(e){return}renderFlags()}
// one flag row — shared by the per-session panel and the cross-session list, so both
// inherit resolve/reopen/delete instead of the list growing its own half-working copy.
function flagRow(f,now,withWho){
  const s=sessions.find(x=>x.id===f.session);
  const who=withWho?`<div class=who onclick="jumpToFlag('${f.session}')" title="Open this session">`+
    `${esc((s&&(s.title||s.project))||f.project||f.session.slice(0,8))}</div>`:"";
  return `<div class="flag ${f.resolved?'done':'open'}">${who}`+
    `<div class=note>${f.resolved?ico('check')+' ':ico('flag')+' '}${esc(f.note)}</div>`+
    (f.context?`<div class=ctx>while: ${esc(f.context)}</div>`:"")+
    `<div class=ft><span>${ago(now-f.ts)}</span>`+
    `<span class="link blue" onclick="resolveFlag(${f.id})">${f.resolved?'reopen':ico('check')+' resolve'}</span>`+
    `<span class="link grey" onclick="delFlag(${f.id})">delete</span></div></div>`;
}
function renderFlags(){
  const mine=flags.filter(f=>f.session===cur).sort((a,b)=>(a.resolved-b.resolved)||b.ts-a.ts);
  const open=mine.filter(f=>!f.resolved).length;
  $("flagc").textContent=mine.length?`${open} open / ${mine.length}`:"";
  const bc=$("flagbtnc"); if(bc)bc.textContent=open?" · "+open:"";   // header button shows the open-flag count
  const now=listNow;
  $("flags").innerHTML=mine.length?mine.map(f=>flagRow(f,now,false)).join(""):
    "<div class=empty>no flags yet</div>";
  // an open flag on the session you're looking at shouldn't need a click to find: reveal the
  // (otherwise opt-in) panel. ONCE per selection — guarded like autoExpandedFor, else the 2s
  // poll would keep re-opening a panel you just closed.
  if(open&&cur&&flagRevealedFor!==cur){
    flagRevealedFor=cur;
    const c=$("flagcard"); if(c&&c.style.display==="none"){c.style.display="";const b=$("flagbtn"); if(b)b.classList.add("on");}
  }
  renderAllFlags();
}
// every session's flags in one list — the panel that makes a flag findable at all.
function renderAllFlags(){
  const openN=flags.filter(f=>!f.resolved).length;
  const n=$("allflagsn"); if(n)n.textContent=openN?openN:"";
  const btn=$("allflagsbtn"); if(btn){btn.classList.toggle("has",!!openN);
    btn.title=openN?`${openN} open flag${openN==1?'':'s'} across all sessions`:"Open flags across every session";}
  const box=$("allflags"); if(!box)return;
  const now=listNow;
  const all=flags.slice().sort((a,b)=>(a.resolved-b.resolved)||b.ts-a.ts);
  box.innerHTML=all.length?all.map(f=>flagRow(f,now,true)).join(""):
    "<div class=empty>no flags yet</div>";
}
// jump from the cross-session list to the flagged session (and open its Flags panel)
function jumpToFlag(sid){
  pick(sid);
  closeDrawer();
  const c=$("flagcard"); if(c){c.style.display="";const b=$("flagbtn"); if(b)b.classList.add("on");
    c.scrollIntoView({behavior:"smooth",block:"nearest"});}
}
function toggleAllFlags(){
  const box=$("allflags"); if(!box)return;
  const show=box.style.display==="none";
  box.style.display=show?"":"none";
  const b=$("allflagsbtn"); if(b)b.classList.toggle("on",show);
  if(show)renderAllFlags();
}
async function addFlag(){
  if(!cur){alert("Pick a session first");return}
  const note=prompt("Flag an issue or gap to resolve:");
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
// the Flags panel is opt-in: hidden until the header "Flag an issue" button reveals it
function toggleFlags(){
  const c=$("flagcard"); if(!c)return;
  const show=c.style.display==="none";
  c.style.display=show?"":"none";
  const b=$("flagbtn"); if(b)b.classList.toggle("on",show);
  if(show)c.scrollIntoView({behavior:"smooth",block:"nearest"});
}
function resolveFlag(id){flagAction("/api/flags/resolve",id)}
function delFlag(id){if(confirm("Delete this flag?"))flagAction("/api/flags/delete",id)}
function toggleRaw(){const r=$("raw");
  if(r.style.display==="none"){r.textContent=lastData?JSON.stringify(lastData,null,2):"no data yet";r.style.display="block"}
  else r.style.display="none";
}
$("q").addEventListener("keydown",e=>{if(e.key==="Enter")doSearch();if(e.key==="Escape")clearSearch();});
$("dq").addEventListener("keydown",e=>{if(e.key==="Escape"){clearDetailSearch();e.stopPropagation();}});
setBell();
start();

// Collapsible panels: the chevron in each card header toggles its body. State lives on the
// static .card element, so it survives the 2s re-render (which only rewrites inner content) —
// no persistence needed. One delegated handler covers every panel: State, Activity, background.
function toggleCard(h){const on=h.parentElement.classList.toggle("collapsed");h.setAttribute("aria-expanded",!on);}
document.querySelectorAll(".card>h2").forEach(h=>{h.tabIndex=0;h.setAttribute("role","button");h.setAttribute("aria-expanded","true");});
document.addEventListener("click",e=>{if(e.target.closest("button,a,input,textarea,select"))return;const h=e.target.closest(".card>h2");if(h)toggleCard(h);});
document.addEventListener("keydown",e=>{if(e.key!=="Enter"&&e.key!==" ")return;const h=e.target.closest&&e.target.closest(".card>h2");if(h&&e.target===h){e.preventDefault();toggleCard(h);}});

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
  if(older>0) html+=`<div class=loadmore>${ico('arrow-down')} ${older} older — scroll to load</div>`;
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
