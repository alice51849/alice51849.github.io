// Lumi Studio — luxury interaction layer (progressive enhancement)
(function(){
  const fine = matchMedia('(pointer:fine)').matches;
  const reduce = matchMedia('(prefers-reduced-motion:reduce)').matches;

  /* 1 ── custom cursor (warm dot + trailing ring) ── */
  if(fine && !reduce){
    const dot = document.createElement('div'); dot.id = 'cursor-dot';
    const ring = document.createElement('div'); ring.id = 'cursor-ring';
    document.body.append(dot, ring);
    document.documentElement.classList.add('fx-cursor');
    let rx = innerWidth/2, ry = innerHeight/2, mx = rx, my = ry;
    addEventListener('mousemove', e=>{ mx = e.clientX; my = e.clientY;
      dot.style.transform = `translate(${mx}px,${my}px)`; }, {passive:true});
    (function loop(){ rx += (mx-rx)*0.2; ry += (my-ry)*0.2;
      ring.style.transform = `translate(${rx}px,${ry}px)`; requestAnimationFrame(loop); })();
    const hot = 'a,button,.card,.lang>button,.spot,.applink,.lk,.btn,summary';
    document.addEventListener('mouseover', e=>{ if(e.target.closest(hot)) ring.classList.add('grow'); });
    document.addEventListener('mouseout',  e=>{ if(e.target.closest(hot)) ring.classList.remove('grow'); });
    document.addEventListener('mousedown', ()=> ring.classList.add('down'));
    document.addEventListener('mouseup',   ()=> ring.classList.remove('down'));
    addEventListener('mouseleave', ()=>{ dot.style.opacity = ring.style.opacity = 0; });
    addEventListener('mouseenter', ()=>{ dot.style.opacity = ring.style.opacity = 1; });
  }

  /* 2 ── hero headline letter-by-letter reveal ── */
  if(!reduce){
    setTimeout(()=>{
      const h1 = document.querySelector('.hero-copy h1');
      const target = h1 ? (h1.querySelector('.bi-m') || h1) : null;
      if(target && !target.dataset.split){
        target.dataset.split = '1';
        splitNodes(target);
        target.querySelectorAll('.ltr').forEach((s,i)=> s.style.animationDelay = (i*0.035)+'s');
      }
    }, 240);
  }
  function splitNodes(el){
    [...el.childNodes].forEach(node=>{
      if(node.nodeType === 3){
        const frag = document.createDocumentFragment();
        [...node.textContent].forEach(ch=>{
          const s = document.createElement('span');
          s.className = 'ltr';
          s.textContent = (ch === ' ') ? '\u00a0' : ch;
          frag.appendChild(s);
        });
        node.replaceWith(frag);
      } else if(node.nodeType === 1){
        if(node.classList && node.classList.contains('grad')) node.classList.add('ltr');
        else splitNodes(node);
      }
    });
  }

  /* 3 ── back-to-top button ── */
  const toTop = document.createElement('button');
  toTop.id = 'toTop'; toTop.setAttribute('aria-label','Back to top');
  toTop.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M12 19V5M5 12l7-7 7 7"/></svg>';
  document.body.appendChild(toTop);
  toTop.addEventListener('click', ()=> scrollTo({top:0, behavior:'smooth'}));
  addEventListener('scroll', ()=> toTop.classList.toggle('show', scrollY > 680), {passive:true});

  /* 4 ── Konami easter egg → warm confetti burst ── */
  const seq = [38,38,40,40,37,39,37,39,66,65]; let pos = 0;
  addEventListener('keydown', e=>{
    pos = (e.keyCode === seq[pos]) ? pos+1 : (e.keyCode === seq[0] ? 1 : 0);
    if(pos === seq.length){ pos = 0; confetti(); }
  });
  function confetti(){
    const c = document.createElement('canvas'); c.id = 'confetti';
    Object.assign(c.style, {position:'fixed', inset:'0', zIndex:300, pointerEvents:'none'});
    document.body.appendChild(c);
    const ctx = c.getContext('2d');
    const W = c.width = innerWidth, H = c.height = innerHeight;
    const cols = ['#ffc24e','#f3895a','#e6b567','#fb9a26','#fff4e2','#f0a83c'];
    const P = Array.from({length:200}, ()=>({
      x: W/2, y: H*0.34, vx:(Math.random()-0.5)*17, vy:(Math.random()-1)*17-3,
      r: 4+Math.random()*7, c: cols[~~(Math.random()*cols.length)],
      rot: Math.random()*6, vr:(Math.random()-0.5)*0.5, life: 1
    }));
    (function frame(){
      ctx.clearRect(0,0,W,H); let alive = false;
      for(const p of P){
        p.vy += 0.34; p.x += p.vx; p.y += p.vy; p.rot += p.vr; p.life -= 0.0058;
        if(p.life > 0 && p.y < H+40){
          alive = true; ctx.save(); ctx.globalAlpha = Math.max(0,p.life);
          ctx.translate(p.x,p.y); ctx.rotate(p.rot); ctx.fillStyle = p.c;
          ctx.fillRect(-p.r/2, -p.r/2, p.r, p.r*0.62); ctx.restore();
        }
      }
      alive ? requestAnimationFrame(frame) : c.remove();
    })();
    const toast = document.createElement('div');
    toast.id = 'egg-toast';
    toast.textContent = '✨ 你發現了隱藏彩蛋 · You found the secret!';
    document.body.appendChild(toast);
    setTimeout(()=> toast.classList.add('show'), 50);
    setTimeout(()=>{ toast.classList.remove('show'); setTimeout(()=> toast.remove(), 400); }, 2800);
  }
})();
