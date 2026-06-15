// Lumi Studio — 3D brand galaxy · cinematic glossy tiles (Three.js, progressive enhancement)
import * as THREE from 'https://unpkg.com/three@0.160.0/build/three.module.js';

const canvas = document.getElementById('bg3d');
const apps   = (window.APPS || []);
const reduce = matchMedia('(prefers-reduced-motion:reduce)').matches;

function boot(){
  if(!canvas || reduce || apps.length === 0) return;            // keep 2D hero
  let renderer;
  try { renderer = new THREE.WebGLRenderer({ canvas, alpha:true, antialias:true, powerPreference:'high-performance' }); }
  catch(e){ return; }                                           // no WebGL → 2D hero
  if(!renderer) return;

  const root  = document.documentElement;
  root.classList.add('has3d');
  const small = innerWidth < 720;

  try {
    renderer.setPixelRatio(Math.min(small ? 1.6 : 2, window.devicePixelRatio || 1));
    if('outputColorSpace' in renderer) renderer.outputColorSpace = THREE.SRGBColorSpace;

    const hero   = canvas.closest('.hero');
    const sizeOf = () => [hero.clientWidth, hero.clientHeight];
    let [W,H]    = sizeOf();
    renderer.setSize(W, H, false);

    const scene  = new THREE.Scene();
    scene.fog    = new THREE.FogExp2(0xfff3df, 0.020);
    const camera = new THREE.PerspectiveCamera(46, W/H, 0.1, 200);
    camera.position.set(0, 0, 22);

    // ── warm studio environment → real glossy reflections ──
    const pmrem  = new THREE.PMREMGenerator(renderer);
    const envSrc = makeEnvTexture();
    scene.environment = pmrem.fromEquirectangular(envSrc).texture;
    envSrc.dispose(); pmrem.dispose();

    // ── cinematic lighting ──
    scene.add(new THREE.HemisphereLight(0xfff3da, 0x7a5a2e, 0.9));
    const key = new THREE.DirectionalLight(0xfff0d2, 1.4);  key.position.set(6, 8, 10); scene.add(key);
    const rim = new THREE.DirectionalLight(0xffd2a0, 0.6);  rim.position.set(-7, -3, 4);  scene.add(rim);
    const cursorLight = new THREE.PointLight(0xffdca6, 0.6, 70, 2); cursorLight.position.set(3, 0, 13); scene.add(cursorLight);

    // ── atmosphere: layered warm particles ──
    const glow   = makeGlowTexture();

    const N  = small ? 300 : 540;
    const pg = new THREE.BufferGeometry();
    const pos = new Float32Array(N*3);
    for(let i=0;i<N;i++){ pos[i*3]=(Math.random()-0.5)*54; pos[i*3+1]=(Math.random()-0.5)*32; pos[i*3+2]=(Math.random()-0.5)*38; }
    pg.setAttribute('position', new THREE.BufferAttribute(pos,3));
    const points  = new THREE.Points(pg, new THREE.PointsMaterial({ color:0xefa53a, size:0.10, map:glow, transparent:true, opacity:0.9,  depthWrite:false, blending:THREE.AdditiveBlending }));
    const pointsB = new THREE.Points(pg, new THREE.PointsMaterial({ color:0xf6c66e, size:0.6,  map:glow, transparent:true, opacity:0.16, depthWrite:false, blending:THREE.AdditiveBlending }));
    scene.add(points, pointsB);

    // ── glossy icon tiles on a fibonacci sphere ──
    const OFFX = 5.6, R = 4.7, CARD = 1.5;
    const shape   = roundedRectShape(CARD, CARD, CARD*0.224);
    const bezelGeo = new THREE.ExtrudeGeometry(shape, { depth:0.16, bevelEnabled:true, bevelThickness:0.06, bevelSize:0.06, bevelSegments:4, steps:1, curveSegments:18 });
    bezelGeo.center();
    const iconGeo = new THREE.PlaneGeometry(CARD*0.94, CARD*0.94);
    const FRONTZ  = 0.16;

    const cards = [];
    const n = apps.length;
    apps.forEach((a,i)=>{
      const y    = 1 - (i/(n-1))*2;
      const radx = Math.sqrt(Math.max(0,1-y*y));
      const phi  = i * Math.PI * (3 - Math.sqrt(5));
      const base = new THREE.Vector3(Math.cos(phi)*radx*R, y*R, Math.sin(phi)*radx*R);

      const group = new THREE.Group();
      const halo  = new THREE.Sprite(new THREE.SpriteMaterial({ map:glow, color:0xffce82, transparent:true, opacity:0.30, depthWrite:false, blending:THREE.AdditiveBlending }));
      halo.scale.set(CARD*2.6, CARD*2.6, 1); halo.position.z = -0.3; group.add(halo);

      const bezel = new THREE.Mesh(bezelGeo, new THREE.MeshPhysicalMaterial({
        color:0xf2b265, metalness:0.35, roughness:0.17, clearcoat:1.0, clearcoatRoughness:0.06, envMapIntensity:1.0, reflectivity:0.6,
        sheen:1.0, sheenColor:new THREE.Color(0xfff2d4) }));
      group.add(bezel);

      const iconMat = new THREE.MeshPhysicalMaterial({ transparent:true, roughness:0.3, clearcoat:1.0, clearcoatRoughness:0.08, envMapIntensity:0.5, metalness:0.0, visible:false });
      loadRoundedIcon(iconMat, a.icon);
      const icon = new THREE.Mesh(iconGeo, iconMat); icon.position.z = FRONTZ; group.add(icon);

      scene.add(group);
      cards.push({ group, icon, halo, base, url:a.url, sc:1, i });
    });

    // ── interaction state ──
    let tmx=0, tmy=0, mx=0, my=0, spin=0, intro=0;
    addEventListener('mousemove', e=>{ tmx=e.clientX/innerWidth-0.5; tmy=e.clientY/innerHeight-0.5; }, {passive:true});
    const ray = new THREE.Raycaster(), mouse = new THREE.Vector2(-2,-2);
    let hovered = null;
    canvas.addEventListener('mousemove', e=>{ const r=canvas.getBoundingClientRect();
      mouse.x=((e.clientX-r.left)/r.width)*2-1; mouse.y=-((e.clientY-r.top)/r.height)*2+1; });
    canvas.addEventListener('mouseleave', ()=> mouse.set(-2,-2));
    canvas.addEventListener('click', ()=>{ if(hovered && hovered.url) window.open(hovered.url,'_blank','noopener'); });

    let scrollFade = 1;
    addEventListener('scroll', ()=>{ scrollFade=Math.max(0,1-scrollY/(innerHeight*0.8)); }, {passive:true});
    addEventListener('resize', ()=>{ [W,H]=sizeOf(); camera.aspect=W/H; camera.updateProjectionMatrix(); renderer.setSize(W,H,false); });

    const iconMeshes = cards.map(c=>c.icon);
    const clock = new THREE.Clock();
    function animate(){
      requestAnimationFrame(animate);
      const t = clock.getElapsedTime();
      if(scrollFade <= 0.001){ renderer.domElement.style.opacity = 0; return; }  // hero offscreen → pause heavy work
      intro += (1-intro)*0.018;
      mx += (tmx-mx)*0.05; my += (tmy-my)*0.05;
      spin += 0.0016;

      camera.position.x = mx*3.4;
      camera.position.y = -my*2.4;
      camera.position.z = 22 - intro*7;
      camera.lookAt(OFFX*0.42, 0, 0);

      cursorLight.position.set(OFFX + mx*16, -my*12, 12);
      cursorLight.intensity = 0.55 + Math.min(Math.abs(mx)+Math.abs(my), 0.6);

      points.rotation.y = t*0.02; pointsB.rotation.y = t*0.02; points.rotation.x = pointsB.rotation.x = my*0.12;

      const ca=Math.cos(spin), sa=Math.sin(spin);
      for(const c of cards){
        const b=c.base;
        c.group.position.set(b.x*ca - b.z*sa + OFFX, b.y + Math.sin(t*0.6+b.x)*0.12, b.x*sa + b.z*ca);
        c.group.quaternion.copy(camera.quaternion);       // billboard: +Z faces the camera (icon front visible)
        c.group.rotateY(Math.sin(t*0.45 + c.i)*0.16);     // gentle wobble → glossy highlight travels
        c.group.rotateX(Math.cos(t*0.38 + c.i)*0.10);
      }

      ray.setFromCamera(mouse, camera);
      const hit = ray.intersectObjects(iconMeshes, false)[0];
      const card = hit ? cards.find(c=>c.icon===hit.object) : null;
      if(card !== hovered){ hovered = card; document.body.style.cursor = card ? 'pointer' : ''; }
      for(const c of cards){
        const tgt = (c===hovered) ? 1.4 : 1;
        c.sc += (tgt-c.sc)*0.16; c.group.scale.setScalar(c.sc);
        const ho = (c===hovered) ? 0.72 : 0.30;
        c.halo.material.opacity += (ho - c.halo.material.opacity)*0.12;
      }

      renderer.domElement.style.opacity = scrollFade;
      renderer.render(scene, camera);
    }
    animate();

  } catch(err){
    root.classList.remove('has3d');                            // graceful fallback → 2D phones
    try { renderer.dispose(); } catch(_){}
    if(window.console && console.warn) console.warn('3D hero disabled:', err);
  }

  // ── helpers ──
  function roundedRectShape(w,h,r){
    const s = new THREE.Shape(), x=-w/2, y=-h/2;
    s.moveTo(x+r, y);
    s.lineTo(x+w-r, y);   s.quadraticCurveTo(x+w, y, x+w, y+r);
    s.lineTo(x+w, y+h-r); s.quadraticCurveTo(x+w, y+h, x+w-r, y+h);
    s.lineTo(x+r, y+h);   s.quadraticCurveTo(x, y+h, x, y+h-r);
    s.lineTo(x, y+r);     s.quadraticCurveTo(x, y, x+r, y);
    return s;
  }
  function loadRoundedIcon(material, src){
    const S = 512, r = S*0.224;                                // iOS-style squircle radius
    function build(paint){
      const cv = document.createElement('canvas'); cv.width = cv.height = S;
      const cx = cv.getContext('2d');
      cx.beginPath();
      cx.moveTo(r,0); cx.arcTo(S,0,S,S,r); cx.arcTo(S,S,0,S,r); cx.arcTo(0,S,0,0,r); cx.arcTo(0,0,S,0,r);
      cx.closePath(); cx.clip();
      paint(cx);
      const tex = new THREE.CanvasTexture(cv);
      if('colorSpace' in tex) tex.colorSpace = THREE.SRGBColorSpace;
      tex.anisotropy = 4; material.map = tex; material.visible = true; material.needsUpdate = true;
    }
    const img = new Image();
    img.onload  = () => build(cx => cx.drawImage(img, 0, 0, S, S));
    img.onerror = () => build(cx => { const g=cx.createLinearGradient(0,0,S,S);
      g.addColorStop(0,'#ffc24e'); g.addColorStop(1,'#f3895a'); cx.fillStyle=g; cx.fillRect(0,0,S,S); });
    img.src = src;
  }
  function makeEnvTexture(){
    const w=512, h=256, cv=document.createElement('canvas'); cv.width=w; cv.height=h;
    const cx=cv.getContext('2d');
    const g=cx.createLinearGradient(0,0,0,h);
    g.addColorStop(0.00,'#fffef9'); g.addColorStop(0.45,'#ffe7bd');
    g.addColorStop(0.72,'#ffc983'); g.addColorStop(1.00,'#f3a455');
    cx.fillStyle=g; cx.fillRect(0,0,w,h);
    const sun=cx.createRadialGradient(w*0.32,h*0.30,0, w*0.32,h*0.30,h*0.55);
    sun.addColorStop(0,'rgba(255,255,255,0.95)'); sun.addColorStop(1,'rgba(255,255,255,0)');
    cx.fillStyle=sun; cx.fillRect(0,0,w,h);
    const t=new THREE.CanvasTexture(cv); t.mapping=THREE.EquirectangularReflectionMapping;
    if('colorSpace' in t) t.colorSpace=THREE.SRGBColorSpace;
    return t;
  }
  function makeGlowTexture(){
    const S=128, cv=document.createElement('canvas'); cv.width=cv.height=S;
    const cx=cv.getContext('2d');
    const g=cx.createRadialGradient(S/2,S/2,0, S/2,S/2,S/2);
    g.addColorStop(0,'rgba(255,242,214,1)'); g.addColorStop(0.25,'rgba(255,206,130,0.7)'); g.addColorStop(1,'rgba(255,206,130,0)');
    cx.fillStyle=g; cx.fillRect(0,0,S,S);
    const t=new THREE.CanvasTexture(cv); if('colorSpace' in t) t.colorSpace=THREE.SRGBColorSpace; return t;
  }
}
boot();
