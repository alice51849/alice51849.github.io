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
        node.textContent.split(/(\s+)/).forEach(tok=>{
          if(tok === '') return;
          if(/^\s+$/.test(tok)){ frag.appendChild(document.createTextNode(tok)); return; }
          const word = document.createElement('span');
          word.className = 'word';
          [...tok].forEach(ch=>{
            const s = document.createElement('span');
            s.className = 'ltr';
            s.textContent = ch;
            word.appendChild(s);
          });
          frag.appendChild(word);
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

  /* 5 ── kinetic magnetic hero letters (cursor pushes the headline) ── */
  if(fine && !reduce){
    setTimeout(()=>{
      const h1 = document.querySelector('.hero-copy h1'); if(!h1) return;
      h1.classList.add('lit');
      const letters = [...h1.querySelectorAll('.ltr')]; if(!letters.length) return;
      const hero = document.querySelector('.hero'); if(!hero) return;
      const R = 130; let cx = 0, cy = 0, on = false, raf = 0;
      function frame(){ raf = 0;
        for(const l of letters){
          const r = l.getBoundingClientRect();
          const lx = r.left + r.width/2, ly = r.top + r.height/2;
          const dx = lx - cx, dy = ly - cy, d = Math.hypot(dx, dy);
          if(on && d < R){ const f = 1 - d/R, a = Math.atan2(dy, dx);
            l.style.transform = `translate(${Math.cos(a)*f*22}px,${Math.sin(a)*f*22}px) scale(${1 + f*0.13})`;
            l.style.textShadow = `0 6px 20px rgba(251,154,38,${0.4*f})`;
          } else { l.style.transform = ''; l.style.textShadow = ''; }
        }
      }
      hero.addEventListener('mousemove', e=>{ cx = e.clientX; cy = e.clientY; on = true; if(!raf) raf = requestAnimationFrame(frame); }, {passive:true});
      hero.addEventListener('mouseleave', ()=>{ on = false; if(!raf) raf = requestAnimationFrame(frame); });
    }, 1500);
  }

  /* 6 ── decode / scramble reveal for section eyebrows ── */
  if(!reduce){
    const seen = new WeakSet();
    const charset = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789·•※★◇—';
    function scramble(el){
      const final = el.textContent; if(!final) return;
      const arr = [...final], dur = 700 + arr.length*24, start = performance.now();
      (function tick(now){
        const p = Math.min(1, (now - start)/dur), reveal = p * arr.length;
        let out = '';
        for(let i=0;i<arr.length;i++){ const ch = arr[i];
          out += (ch === ' ' || ch === '\u00a0') ? ch : (i < reveal ? ch : charset[(Math.random()*charset.length)|0]); }
        el.textContent = out;
        if(p < 1) requestAnimationFrame(tick); else el.textContent = final;
      })(start);
    }
    const sio = new IntersectionObserver(es=> es.forEach(e=>{
      if(e.isIntersecting && !seen.has(e.target)){ seen.add(e.target); scramble(e.target); sio.unobserve(e.target); }
    }), {threshold:.6});
    setTimeout(()=> document.querySelectorAll('.eyebrow').forEach(el=> sio.observe(el)), 320);
  }

  /* 7 ── ambient sound: opt-in background music + UI sfx ── */
  (function(){
    const SPK = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 5 6 9H2v6h4l5 4V5Z"/><path d="M15.5 8.5a5 5 0 0 1 0 7M19 4.5a9 9 0 0 1 0 15"/></svg>';
    const MUTE = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 5 6 9H2v6h4l5 4V5Z"/><path d="m22 9-6 6M16 9l6 6"/></svg>';
    const btn = document.createElement('button');
    btn.id = 'sound-toggle'; btn.type = 'button';
    btn.setAttribute('aria-label', 'Toggle music & sound'); btn.innerHTML = MUTE;
    document.body.appendChild(btn);

    const bgm = new Audio('assets/bgm.mp3'); bgm.loop = true; bgm.preload = 'none'; bgm.volume = 0;
    let on = false, fadeRAF = 0, actx = null, popBuf = null;

    function ensureCtx(){
      if(actx) return;
      try {
        actx = new (window.AudioContext || window.webkitAudioContext)();
        fetch('assets/pop.m4a').then(r=>r.arrayBuffer()).then(b=>actx.decodeAudioData(b)).then(buf=>{ popBuf = buf; }).catch(()=>{});
      } catch(e){}
    }
    function pop(v){
      if(!on || !actx || !popBuf) return;
      try { const s = actx.createBufferSource(); s.buffer = popBuf;
        const g = actx.createGain(); g.gain.value = v || 0.18;
        s.connect(g).connect(actx.destination); s.start(); } catch(e){}
    }
    function fade(to){
      cancelAnimationFrame(fadeRAF);
      const from = bgm.volume, t0 = performance.now(), dur = 650;
      (function step(now){ const p = Math.min(1, (now - t0)/dur); bgm.volume = from + (to - from)*p;
        if(p < 1) fadeRAF = requestAnimationFrame(step); else if(to === 0){ try{ bgm.pause(); }catch(e){} } })(t0);
    }
    function setOn(state){
      on = state; btn.classList.toggle('playing', on); btn.classList.remove('hint');
      btn.innerHTML = on ? SPK : MUTE;
      try { localStorage.setItem('lumi-sound', on ? '1' : '0'); } catch(e){}
      if(on){ ensureCtx(); if(actx && actx.state === 'suspended') actx.resume();
        const p = bgm.play(); if(p && p.then) p.then(()=>fade(0.32)).catch(()=>{}); else fade(0.32); }
      else fade(0);
    }
    btn.addEventListener('click', ()=> setOn(!on));

    let pref = null; try { pref = localStorage.getItem('lumi-sound'); } catch(e){}
    if(pref == null) btn.classList.add('hint');            // invite first-time visitors
    if(pref === '1'){                                       // resume on first gesture (autoplay policy)
      const arm = ()=>{ setOn(true); removeEventListener('pointerdown', arm); removeEventListener('keydown', arm); };
      addEventListener('pointerdown', arm, {once:true}); addEventListener('keydown', arm, {once:true});
    }
    document.addEventListener('pointerdown', e=>{ if(e.target.closest('a,button,.card,.lk,.lang>button')) pop(0.2); }, {passive:true});
  })();
})();
