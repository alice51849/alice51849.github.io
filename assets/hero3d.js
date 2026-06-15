// Lumi Studio — 3D brand galaxy (Three.js, progressive enhancement)
import * as THREE from 'https://unpkg.com/three@0.160.0/build/three.module.js';

const canvas = document.getElementById('bg3d');
const apps = (window.APPS || []);
const reduce = matchMedia('(prefers-reduced-motion:reduce)').matches;

function boot(){
  if(!canvas || reduce || apps.length === 0) return;        // keep 2D hero
  let renderer;
  try { renderer = new THREE.WebGLRenderer({ canvas, alpha:true, antialias:true }); }
  catch(e){ return; }                                       // no WebGL → 2D hero
  if(!renderer) return;

  const root = document.documentElement;
  root.classList.add('has3d');
  const hero = canvas.closest('.hero');
  const sizeOf = () => [hero.clientWidth, hero.clientHeight];
  let [W,H] = sizeOf();
  renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));
  renderer.setSize(W, H, false);

  const scene = new THREE.Scene();
  scene.fog = new THREE.FogExp2(0xfff3df, 0.028);
  const camera = new THREE.PerspectiveCamera(48, W/H, 0.1, 100);
  camera.position.set(0, 0, 15);

  // warm particle universe
  const N = 460;
  const pg = new THREE.BufferGeometry();
  const pos = new Float32Array(N*3), spd = new Float32Array(N);
  for(let i=0;i<N;i++){
    pos[i*3]   = (Math.random()-0.5)*44;
    pos[i*3+1] = (Math.random()-0.5)*26;
    pos[i*3+2] = (Math.random()-0.5)*30;
    spd[i] = 0.2 + Math.random()*0.8;
  }
  pg.setAttribute('position', new THREE.BufferAttribute(pos,3));
  const pm = new THREE.PointsMaterial({ color:0xefa53a, size:0.085, transparent:true,
    opacity:0.85, depthWrite:false, blending:THREE.AdditiveBlending });
  const points = new THREE.Points(pg, pm);
  scene.add(points);
  // soft glow sprites layer (bigger faint points)
  const pm2 = new THREE.PointsMaterial({ color:0xf6c66e, size:0.5, transparent:true,
    opacity:0.18, depthWrite:false, blending:THREE.AdditiveBlending });
  scene.add(new THREE.Points(pg, pm2));

  // icon galaxy (fibonacci sphere, billboarded)
  const OFFX = 3.6, R = 5.6, CARD = 1.55;
  const loader = new THREE.TextureLoader();
  const cards = [];
  const n = apps.length;
  apps.forEach((a,i)=>{
    const y = 1 - (i/(n-1))*2;
    const rad = Math.sqrt(Math.max(0,1-y*y));
    const phi = i * Math.PI * (3 - Math.sqrt(5));
    const base = new THREE.Vector3(Math.cos(phi)*rad*R, y*R, Math.sin(phi)*rad*R);
    const mat = new THREE.MeshBasicMaterial({ transparent:true, side:THREE.DoubleSide, visible:false });
    (function(material, src){
      const S = 512, r = S * 0.224;                 // iOS-style squircle radius (~22.4%)
      function roundedTexture(paint){
        const cv = document.createElement('canvas'); cv.width = cv.height = S;
        const cx = cv.getContext('2d');
        cx.beginPath();
        cx.moveTo(r,0); cx.arcTo(S,0,S,S,r); cx.arcTo(S,S,0,S,r); cx.arcTo(0,S,0,0,r); cx.arcTo(0,0,S,0,r);
        cx.closePath(); cx.clip();                  // clip → corners stay transparent
        paint(cx);
        const tex = new THREE.CanvasTexture(cv);
        if('colorSpace' in tex) tex.colorSpace = THREE.SRGBColorSpace;
        tex.anisotropy = 4; material.map = tex; material.visible = true; material.needsUpdate = true;
      }
      const img = new Image();
      img.onload  = () => roundedTexture(cx => cx.drawImage(img, 0, 0, S, S));
      img.onerror = () => roundedTexture(cx => { const g = cx.createLinearGradient(0,0,S,S);
        g.addColorStop(0,'#ffc24e'); g.addColorStop(1,'#f3895a'); cx.fillStyle = g; cx.fillRect(0,0,S,S); });
      img.src = src;
    })(mat, a.icon);
    const m = new THREE.Mesh(new THREE.PlaneGeometry(CARD, CARD), mat);
    m.userData = { base, url:a.url, sc:1 };
    scene.add(m);
    cards.push(m);
  });

  // interaction state
  let tmx=0, tmy=0, mx=0, my=0, spin=0;
  addEventListener('mousemove', e=>{ tmx = e.clientX/innerWidth - 0.5; tmy = e.clientY/innerHeight - 0.5; }, {passive:true});
  const ray = new THREE.Raycaster(), mouse = new THREE.Vector2(-2,-2);
  let hovered = null;
  canvas.addEventListener('mousemove', e=>{
    const r = canvas.getBoundingClientRect();
    mouse.x = ((e.clientX-r.left)/r.width)*2 - 1;
    mouse.y = -((e.clientY-r.top)/r.height)*2 + 1;
  });
  canvas.addEventListener('mouseleave', ()=>{ mouse.set(-2,-2); });
  canvas.addEventListener('click', ()=>{ if(hovered && hovered.userData.url) window.open(hovered.userData.url, '_blank','noopener'); });

  let scrollFade = 1;
  addEventListener('scroll', ()=>{ scrollFade = Math.max(0, 1 - scrollY/(innerHeight*0.75)); }, {passive:true});
  addEventListener('resize', ()=>{ [W,H]=sizeOf(); camera.aspect=W/H; camera.updateProjectionMatrix(); renderer.setSize(W,H,false); });

  const clock = new THREE.Clock();
  function animate(){
    requestAnimationFrame(animate);
    const t = clock.getElapsedTime();
    mx += (tmx - mx)*0.045; my += (tmy - my)*0.045;
    spin += 0.0017;

    camera.position.x = mx*3.2;
    camera.position.y = -my*2.2;
    camera.lookAt(OFFX*0.42, 0, 0);

    points.rotation.y = t*0.02;
    points.rotation.x = my*0.15;

    const ca = Math.cos(spin), sa = Math.sin(spin);
    for(const c of cards){
      const b = c.userData.base;
      c.position.set(b.x*ca - b.z*sa + OFFX, b.y + Math.sin(t*0.6 + b.x)*0.12, b.x*sa + b.z*ca);
      c.lookAt(camera.position);
    }
    // hover raycast
    ray.setFromCamera(mouse, camera);
    const hit = ray.intersectObjects(cards)[0];
    const top = hit ? hit.object : null;
    if(top !== hovered){ hovered = top; document.body.style.cursor = top ? 'pointer' : ''; }
    for(const c of cards){
      const tgt = (c === hovered) ? 1.42 : 1;
      c.userData.sc += (tgt - c.userData.sc)*0.16;
      c.scale.set(c.userData.sc, c.userData.sc, 1);
    }
    renderer.domElement.style.opacity = scrollFade;
    renderer.render(scene, camera);
  }
  animate();
}
boot();
