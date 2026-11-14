import React, { forwardRef, useEffect, useImperativeHandle, useRef, useState } from 'react';
import * as THREE from 'three'; // written for three r155+ (npm package, same as SpaceCraftScene)
import './SuitHelmetScene.css';
import { createRealEarth } from '../spaceShared/realEarth.js';

/* =====================================================================
   SuitHelmetScene  –  "Flame in Freefall · Suit helmet"
   Ported from suitHelmetScene_v6.html (three r128 CDN) to an ES-module React
   component that uses the npm `three` package.

   Usage
     <div style={{ width: '100vw', height: '100vh' }}>
       <SuitHelmetScene ref={suitRef} shape="real" alert={false} />
     </div>

   Props
     shape           'real' | 'wrap' | 'subnautica' | 'ironman' | 'artemis' | 'wide'   (default 'real')
     alert           boolean   fire alert (red HUD + warning text)
     accent          CSS colour for the HUD accent (default CONFIG.accent)
     hello           string    Ember's greeting in the comm panel
     reducedMotion   boolean   default: prefers-reduced-motion
     showDevPanel    boolean   shows Replay / shape / Fire-alert buttons and enables the
                               keyboard shortcuts (A = alert, 1-6 = shapes)
     className, style         applied to the host wrapper

   Imperative handle (ref)
     setAlert(bool), say(text), setShape(name), setAccent(css), replay(), getContext()
   ===================================================================== */

/* ============================ CONFIG ============================ */
export const CONFIG = {
    accent: '#7fb8ff',
    sun: [-0.5, 0.17, -0.85],                          // direction TOWARD the sun (low lunar sun, ahead-left)
    suit: { o2: 100, psi: 4.3 },                       // challenge brief: suit = 100% O2 at 4.3 psi
    hab: { o2: 30, psi: 10.2, pos: [-24, 0, -52] },    // Moon base: >=30% O2 at <=10.2 psi
    T: { fade: 1.8, hud: 2.2 },
    hello: 'Ember here. Your suit is pure oxygen at 4.3 psi - fire behaves differently out here. Keep hot tools away from fabric.',
    alertText: 'Smoke alarm in the habitat. Do not enter - high-O2 air feeds flames. Isolate ventilation and use CO2 suppression.',
    // three r155+ removed "legacy lights": intensities are now physical, so the r128 values
    // look ~PI times too dark. This factor compensates. Tune to taste.
    lightScale: parseInt(THREE.REVISION, 10) >= 155 ? Math.PI : 1,
};

/* ============================ helpers ============================ */
const clamp = (x, a = 0, b = 1) => Math.min(b, Math.max(a, x));
const lerp = (a, b, k) => a + (b - a) * k;
const ease = (k) => { k = clamp(k); return k * k * (3 - 2 * k); };
const cvs = (w, h) => { const c = document.createElement('canvas'); c.width = w; c.height = h; return c; };
const seeded = (s) => () => ((s = (s * 1664525 + 1013904223) >>> 0) / 4294967296);
const hash = (x, y) => { const s = Math.sin(x * 127.1 + y * 311.7) * 43758.5453; return s - Math.floor(s); };
const vnoise = (x, y) => {
    const i = Math.floor(x), j = Math.floor(y), fx = x - i, fy = y - j, u = fx * fx * (3 - 2 * fx), v = fy * fy * (3 - 2 * fy);
    return lerp(lerp(hash(i, j), hash(i + 1, j), u), lerp(hash(i, j + 1), hash(i + 1, j + 1), u), v);
};
const glowTex = () => {
    const c = cvs(128, 128), g = c.getContext('2d'), r = g.createRadialGradient(64, 64, 0, 64, 64, 64);
    r.addColorStop(0, 'rgba(255,255,255,1)'); r.addColorStop(0.25, 'rgba(255,255,255,.35)'); r.addColorStop(1, 'rgba(255,255,255,0)');
    g.fillStyle = r; g.fillRect(0, 0, 128, 128);
    return new THREE.CanvasTexture(c);
};

/* ============================ LUNAR WORLD ============================ */
function buildWorld(scene, track) {
    const LS = CONFIG.lightScale;
    const R = seeded(5), S = new THREE.Vector3(...CONFIG.sun).normalize(), HP = CONFIG.hab.pos;
    const craters = [];
    while (craters.length < 60) {
        const x = (R() - 0.5) * 700, z = (R() - 0.5) * 700, r = 4 + R() * R() * 40;
        if (Math.hypot(x, z) > 25 + r && Math.hypot(x - HP[0], z - HP[2]) > 38 + r) craters.push({ x, z, r, d: 0.25 + R() * 0.35 });
    }
    const H = (x, z) => {
        const m = Math.min(ease((Math.hypot(x, z) - 6) / 30), ease((Math.hypot(x - HP[0], z - HP[2]) - 16) / 18));
        let h = (vnoise(x * 0.02, z * 0.02) * 9 + vnoise(x * 0.1, z * 0.1) * 1.3 + vnoise(x * 0.45, z * 0.45) * 0.12) * m;
        for (const c of craters) {
            const d = Math.hypot(x - c.x, z - c.z) / c.r;
            if (d < 1.6) h += (d < 1 ? -c.r * c.d * 0.35 * (1 - d * d) : 0) + c.r * 0.05 * Math.exp(-Math.pow((d - 1) / 0.18, 2));
        }
        return h;
    };

    /* terrain */
    const geo = track(new THREE.PlaneGeometry(800, 800, 320, 320)); geo.rotateX(-Math.PI / 2);
    const p = geo.attributes.position;
    for (let i = 0; i < p.count; i++) p.setY(i, H(p.getX(i), p.getZ(i)) - 0.3);
    geo.computeVertexNormals();
    const n = geo.attributes.normal, col = new Float32Array(p.count * 3);
    for (let i = 0; i < p.count; i++) {
        const l = Math.max(0, n.getX(i) * S.x + n.getY(i) * S.y + n.getZ(i) * S.z), g = (0.1 + 1.25 * l) * (0.9 + 0.2 * hash(p.getX(i) * 3.1, p.getZ(i) * 3.1)) * 0.8;
        col.set([0.7 * g, 0.66 * g, 0.62 * g], i * 3);
    }
    geo.setAttribute('color', new THREE.BufferAttribute(col, 3));
    const dc = cvs(512, 512), dg = dc.getContext('2d'), di = dg.createImageData(512, 512);   // regolith grain
    for (let y = 0; y < 512; y++) for (let x = 0; x < 512; x++) {
        const v = (0.62 + (vnoise(x * 0.05, y * 0.05) * 0.45 + vnoise(x * 0.2, y * 0.2) * 0.3 + hash(x, y) * 0.25) * 0.5) * 255, k = (y * 512 + x) * 4;
        di.data[k] = v; di.data[k + 1] = v; di.data[k + 2] = v * 0.97; di.data[k + 3] = 255;
    }
    dg.putImageData(di, 0, 0);
    for (let i = 0; i < 500; i++) {
        const x = R() * 512, y = R() * 512, r = 0.8 + R() * 2.4;
        dg.fillStyle = 'rgba(0,0,0,.35)'; dg.beginPath(); dg.arc(x + r * 0.6, y + r * 0.7, r, 0, 6.3); dg.fill();
        dg.fillStyle = 'rgba(255,255,255,.28)'; dg.beginPath(); dg.arc(x, y, r * 0.8, 0, 6.3); dg.fill();
    }
    const dt = track(new THREE.CanvasTexture(dc)); dt.wrapS = dt.wrapT = THREE.MirroredRepeatWrapping; dt.repeat.set(70, 70); dt.anisotropy = 8;
    scene.add(new THREE.Mesh(geo, track(new THREE.MeshBasicMaterial({ vertexColors: true, map: dt }))));

    /* boulders */
    const rg = track(new THREE.IcosahedronGeometry(1, 1)), rm = track(new THREE.MeshStandardMaterial({ color: 0x8a867f, roughness: 1, flatShading: true }));
    for (let i = 0; i < 110; i++) {
        const a = R() * 6.283, d = 6 + R() * R() * 150, x = Math.cos(a) * d, z = Math.sin(a) * d - 8;
        if (Math.hypot(x - HP[0], z - HP[2]) < 14) continue;
        const s = 0.12 + R() * R() * 1.6, m = new THREE.Mesh(rg, rm);
        m.position.set(x, H(x, z) - 0.3 + s * 0.25, z); m.scale.set(s * (1 + R() * 0.6), s * 0.7, s * (1 + R() * 0.6)); m.rotation.set(R() * 3, R() * 3, R() * 3); scene.add(m);
    }

    /* stars */
    const sp = [], sc = [];
    for (let i = 0; i < 2600; i++) {
        const u = R() * 2 - 1, a = R() * 6.283, r = Math.sqrt(1 - u * u), b = 0.3 + R() * 0.7;
        sp.push(450 * r * Math.cos(a), Math.abs(450 * u) * 0.95 + 4, 450 * r * Math.sin(a)); sc.push(b, b, b * (0.9 + R() * 0.2));
    }
    const sg = track(new THREE.BufferGeometry()); sg.setAttribute('position', new THREE.Float32BufferAttribute(sp, 3)); sg.setAttribute('color', new THREE.Float32BufferAttribute(sc, 3));
    scene.add(new THREE.Points(sg, track(new THREE.PointsMaterial({ size: 1.7, sizeAttenuation: false, vertexColors: true, fog: false }))));

    /* Earth (real textures, same as the opening scene) */
    const earth = track(createRealEarth({ radius: 28, startLon: 40, orient: [25, 0, 0], sun: new THREE.Vector3(-0.5, -0.2, 0) }));
    earth.group.position.set(70, 85, -230); scene.add(earth.group);

    /* sun (same corona shader as the opening scene) */
    const SUN_DIST = 420, SUN_SIZE = 1.3;               // SUN_SIZE: 1 = opening-scene size, 0.5 = half, 2 = double
    const SUNU = { time: { value: 0 }, glowK: { value: 3.0 } };
    const sunMesh = new THREE.Mesh(track(new THREE.PlaneGeometry(30, 30)), track(new THREE.ShaderMaterial({
        uniforms: SUNU, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
        vertexShader: 'varying vec2 v;void main(){v=uv;gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.);}',
        fragmentShader:
            'uniform float time,glowK;varying vec2 v;' +
            'float h(vec2 p){return fract(sin(dot(p,vec2(127.1,311.7)))*43758.5453);}' +
            'float n(vec2 p){vec2 i=floor(p),f=fract(p);f=f*f*(3.-2.*f);return mix(mix(h(i),h(i+vec2(1.,0.)),f.x),mix(h(i+vec2(0.,1.)),h(i+vec2(1.,1.)),f.x),f.y);}' +
            'float fbm(vec2 p){float a=.5,s=0.;for(int i=0;i<5;i++){s+=a*n(p);p*=2.03;a*=.5;}return s;}' +
            'void main(){vec2 q=v*2.-1.;float r=length(q),R=.16;' +
            'float disc=smoothstep(R,R-.008,r);float mu=sqrt(max(0.,1.-(r/R)*(r/R)));' +
            'float g=fbm(q/R*3.5+vec2(time*.04,0.));float g2=fbm(q/R*9.-time*.03);' +
            'vec3 hot=vec3(1.,.97,.85),mid=vec3(1.,.62,.16);' +
            'vec3 sc=mix(mid,hot,pow(mu,.6)+(g-.5)*.5)*(.9+.35*g2)*(.6+.55*pow(mu,.45))*1.7;' +
            'float d=max(r-R,0.)*glowK;float ang=atan(q.y,q.x);' +
            'float ray=.65+.35*sin(ang*7.+fbm(vec2(ang*2.,time*.05))*8.);' +
            'float gl=(exp(-d*16.)*.95+exp(-d*5.)*.28)*(.75+.25*ray)+exp(-d*1.8)*.05;' +
            'vec3 cor=mix(vec3(1.,.85,.5),vec3(1.,.5,.15),clamp(d*4.,0.,1.))*gl;' +
            'vec3 c=mix(cor,sc,disc)*smoothstep(1.,.55,r);gl_FragColor=vec4(c,1.);}',
    })));
    sunMesh.position.copy(S).multiplyScalar(SUN_DIST);
    sunMesh.scale.setScalar((SUN_DIST / 70) * SUN_SIZE);  // same apparent size as the opening scene
    scene.add(sunMesh);

    /* distant habitat (HAB-01) */
    const hab = new THREE.Group(), std = (c, r, m) => track(new THREE.MeshStandardMaterial({ color: c, roughness: r, metalness: m }));
    const add = (geo_, mat, x, y, z, par) => { const o = new THREE.Mesh(track(geo_), mat); o.position.set(x, y, z); (par || hab).add(o); return o; };
    const body = add(new THREE.CylinderGeometry(3.2, 3.2, 12, 40), std(0xc9ced6, 0.5, 0.5), 0, 3.4, 0); body.rotation.z = Math.PI / 2;
    [-1, 1].forEach((s) => add(new THREE.SphereGeometry(3.2, 32, 16, 0, 6.3, 0, Math.PI / 2), std(0xc9ced6, 0.5, 0.5), s * 6, 3.4, 0).rotation.z = -s * Math.PI / 2);
    const winM = track(new THREE.MeshBasicMaterial({ color: new THREE.Color(1.6, 1.3, 0.8) }));
    for (let i = -3; i <= 3; i++) add(new THREE.BoxGeometry(0.9, 0.55, 0.12), winM, i * 1.5, 3.9, 3.15);
    add(new THREE.BoxGeometry(14, 0.4, 0.3), std(0xd98a1a, 0.6, 0.3), 0, 2.4, 3.18);
    add(new THREE.CylinderGeometry(0.12, 0.12, 6, 8), std(0x9aa3af, 0.4, 0.9), 7, 3, -1);
    const dish = add(new THREE.SphereGeometry(1.1, 24, 8, 0, 6.3, 0, 1), std(0xe8eaee, 0.4, 0.6), 7, 6.3, -1); dish.rotation.set(-0.5, 0, 0.3);
    [-1, 1].forEach((s) => { add(new THREE.BoxGeometry(7, 0.12, 3), std(0x14306a, 0.3, 0.7), 8, 0.9, 6 + (s > 0 ? 0 : -9)).rotation.x = -0.35; });
    const beaconM = track(new THREE.MeshBasicMaterial({ color: new THREE.Color(3, 1.3, 0.1), transparent: true }));
    add(new THREE.SphereGeometry(0.18, 12, 8), beaconM, -5, 7.2, 0); add(new THREE.CylinderGeometry(0.05, 0.05, 3.6, 6), std(0x9aa3af, 0.4, 0.9), -5, 5.4, 0);
    hab.position.set(HP[0], H(HP[0], HP[2]) - 0.3, HP[2]); hab.rotation.y = 0.5; scene.add(hab);

    /* lights */
    scene.add(new THREE.HemisphereLight(0xcfd8e8, 0x2a2f37, 0.7 * LS));
    const dl = new THREE.DirectionalLight(0xfff1dc, 1.6 * LS); dl.position.copy(S).multiplyScalar(30); scene.add(dl);

    return {
        hab,
        update(t, cam) {
            earth.update(t); beaconM.opacity = 0.3 + 0.7 * Math.abs(Math.sin(t * 1.6));
            SUNU.time.value = t;
            if (cam) sunMesh.quaternion.copy(cam.quaternion);   // billboard: always faces the helmet camera
        },
        sunDir: S,
    };
}

/* ============================ HUD ============================ */
let UID = 0;
function buildHud(root, uid) {
    const A = CONFIG.suit, hp = CONFIG.hab;
    root.insertAdjacentHTML('beforeend', `
  <canvas class="det"></canvas>
  <svg class="vsvg" viewBox="0 0 1 1" preserveAspectRatio="none">
    <defs><clipPath id="${uid}c" clipPathUnits="objectBoundingBox"><path class="vp"/></clipPath>
      <linearGradient id="${uid}s" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#fff" stop-opacity=".10"/><stop offset=".12" stop-color="#fff" stop-opacity="0"/><stop offset=".2" stop-color="#fff" stop-opacity=".05"/><stop offset=".26" stop-color="#fff" stop-opacity="0"/></linearGradient>
      <radialGradient id="${uid}f" cx=".5" cy="1.05" r=".55"><stop offset="0" stop-color="#dcebff" stop-opacity=".55"/><stop offset="1" stop-color="#dcebff" stop-opacity="0"/></radialGradient></defs>
    <path class="vs" fill="none"/>
    <g clip-path="url(#${uid}c)"><path class="vin"/><path class="vst"/><path class="vst2"/><rect width="1" height="1" fill="url(#${uid}s)"/><rect class="fog" width="1" height="1" fill="url(#${uid}f)" opacity="0"/></g>
    <path class="vr2" transform="translate(.5 .5) scale(.975) translate(-.5 -.5)"/><path class="vr"/>
  </svg>
  <div class="glare" style="clip-path:url(#${uid}c)"></div>
  <div class="hud">
    <div class="tape"><i></i><span class="hd">000 N</span></div><div class="tapemk"></div><div class="cross"></div>
    <div class="ret"><div class="bx"></div><div class="bx2"></div><div class="lb"><b>HAB-01</b> &middot; <span class="dist"></span><br>O2 ${hp.o2}% &middot; ${hp.psi} psi</div></div>
    <div class="pnl s-pl"><h4>SUIT ATMOSPHERE</h4>
      <div class="r"><span>O2</span><em>${A.o2} %</em></div><div class="bar"><i style="width:100%"></i></div>
      <div class="r"><span>Pressure</span><em>${A.psi.toFixed(2)} psi</em></div></div>
    <div class="pnl s-pr"><h4>CREW VITALS &middot; SIMULATED</h4>
      <div class="r"><span>Heart</span><em class="hr"></em></div><div class="r"><span>SpO2</span><em class="sp"></em></div>
      <div class="r"><span>CO2</span><em class="co2"></em></div><div class="r"><span>Tank</span><em class="tank"></em></div><div class="r"><span>EVA</span><em class="eva"></em></div></div>
    <div class="pnl s-pc"><b>EMBER &#9656;</b><div class="tx"></div></div>
  </div><div class="boot"><div>SUIT LINK &middot; EVA-02</div><div class="bt2">PRESSURE CHECK ...</div></div>`);
    const q = (s) => root.querySelector(s);
    return {
        hud: q('.hud'), tape: q('.tape i'), hd: q('.hd'), ret: q('.ret'), dist: q('.dist'), glare: q('.glare'), fog: q('.fog'), boot: q('.boot'), bt2: q('.bt2'),
        co2: q('.co2'), tank: q('.tank'), hr: q('.hr'), sp: q('.sp'), eva: q('.eva'), tx: q('.tx'),
    };
}

/* ============================ VISOR SHAPES ============================ */
// path in 0..1 screen coords + where the HUD panels sit inside it (percent)
export const SHAPES = {
    wrap: {
        d: 'M.114 .062 L.363 .059 L.403 .096 L.556 .091 L.575 .057 L.899 .070 L.972 .238 L.972 .769 L.901 .941 L.630 .930 L.575 .737 L.419 .743 L.381 .951 L.126 .947 L.027 .764 L.021 .259 Z',
        bezel: 0.3, inner: false, plates: false, warnAt: 0.48, dash: [0.435, 0.765, 0.562, 0.93], hud: { pl: [5, 25], pr: [5, 25], pf: 28, tape: 14, pc: [7, 20] },
    },
    subnautica: { d: 'M.17 .08 L.83 .08 L.94 .19 L.95 .62 L.88 .78 L.60 .83 L.5 .80 L.40 .83 L.12 .78 L.05 .62 L.06 .19 Z', struts: 'M.33 .08 L.30 .82 M.67 .08 L.70 .82', hud: { pl: [10, 27], pr: [10, 27], pf: 22, tape: 11, pc: [10, 24] } },
    ironman: { d: 'M.22 .09 L.78 .09 L.90 .20 L.92 .52 L.84 .74 L.66 .90 L.56 .90 L.5 .84 L.44 .90 L.34 .90 L.16 .74 L.08 .52 L.10 .20 Z', hud: { pl: [11, 30], pr: [11, 30], pf: 14, tape: 12, pc: [23, 20] } },
    artemis: { d: 'M.22 .10 Q.5 .05 .78 .10 Q.93 .16 .93 .42 L.91 .70 Q.88 .88 .70 .90 L.30 .90 Q.12 .88 .09 .70 L.07 .42 Q.07 .16 .22 .10 Z', hud: { pl: [12, 32], pr: [12, 32], pf: 12, tape: 12.5, pc: [15, 21] } },
    wide: { d: 'M.06 .22 Q.5 .10 .94 .22 L.94 .70 Q.5 .84 .06 .70 Z', hud: { pl: [9.5, 34], pr: [9.5, 34], pf: 24, tape: 21, pc: [10, 27] } },
};
(function () {                                  // 'real': plain bubble visor (superellipse, slightly narrower at the chin)
    const pts = [], n = 96, p = 3.2;
    for (let i = 0; i < n; i++) {
        const a = i / n * Math.PI * 2, c = Math.cos(a), sn = Math.sin(a), x = Math.sign(c) * Math.pow(Math.abs(c), 2 / p), y = Math.sign(sn) * Math.pow(Math.abs(sn), 2 / p);
        pts.push((i ? 'L' : 'M') + (0.5 + x * 0.45 * (1 - 0.07 * Math.max(0, y))).toFixed(4) + ' ' + (0.49 + y * 0.41).toFixed(4));
    }
    SHAPES.real = { d: pts.join(' ') + ' Z', hud: { pl: [8, 28], pr: [8, 28], pf: 15, tape: 12, pc: [12, 19] } };
})();
export const SHAPE_NAMES = ['real', 'wrap', 'subnautica', 'ironman', 'artemis', 'wide'];

/* ============================ canvas helpers ============================ */
function rrect(g, x, y, w, h, r) { g.beginPath(); g.moveTo(x + r, y); g.arcTo(x + w, y, x + w, y + h, r); g.arcTo(x + w, y + h, x, y + h, r); g.arcTo(x, y + h, x, y, r); g.arcTo(x, y, x + w, y, r); g.closePath(); }

/* ============================ mountSuitScene ============================
   Imperative three.js scene. Appends its own root <div class="su"> to `container`
   and returns a controller. Always call .dispose() on unmount. */
export function mountSuitScene(container, options) {
    options = options || {};
    const C = CONFIG, LS = C.lightScale;
    const reduced = options.reducedMotion != null ? !!options.reducedMotion : window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const disp = [], cleanups = [], track = (o) => (disp.push(o), o), on = (t, e, f) => { t.addEventListener(e, f); cleanups.push(() => t.removeEventListener(e, f)); };
    const uid = 'su' + (++UID);
    const helloText = options.hello || C.hello;

    const root = document.createElement('div'); root.className = 'su'; root.style.setProperty('--a', options.accent || C.accent); container.appendChild(root);
    const renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: 'high-performance' });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2)); renderer.outputColorSpace = THREE.SRGBColorSpace; renderer.toneMapping = THREE.ACESFilmicToneMapping; renderer.setClearColor(0x000000);
    root.appendChild(renderer.domElement);
    const scene = new THREE.Scene(), camera = new THREE.PerspectiveCamera(70, 1, 0.05, 1200), world = buildWorld(scene, track), E = buildHud(root, uid);

    let cur = 'real';
    const S = world.sunDir, fwd = new THREE.Vector3(), hp = new THREE.Vector3(), tp = new THREE.Vector3();
    let t = 0, last = 0, raf = 0, nx = 0, ny = 0, yaw = 0, pitch = 0, W = 1, H = 1, disposed = false, isAlert = false, hudT = 0, typeT = 0, hudOn = false, msgT = null;

    /* inside of a real hard-shell helmet: smooth light-grey shell, chrome visor frame, pivots, neck ring */
    function drawFrame() {
        const vp = root.querySelector('.vr'), cv = root.querySelector('canvas.det'); if (!vp || !cv || !vp.getAttribute('d')) return;
        const dpr = Math.min(window.devicePixelRatio || 1, 2), g = cv.getContext('2d'), sp = SHAPES[cur];
        cv.width = W * dpr; cv.height = H * dpr; g.setTransform(dpr, 0, 0, dpr, 0, 0);
        const mk = (k) => { const q = new Path2D(); q.addPath(new Path2D(sp.d), new DOMMatrix([W * k, 0, 0, H * k, W * (1 - k) / 2, H * (1 - k) / 2])); return q; };
        const sc = mk(1), cp = new Path2D(); cp.rect(0, 0, W, H); cp.addPath(new Path2D(sp.d), new DOMMatrix([W, 0, 0, H, 0, 0]));
        const rad = (x, y, r, stops) => { const q = g.createRadialGradient(x, y, 0, x, y, r); stops.forEach(([o, c]) => q.addColorStop(o, c)); return q; };
        const bolt = (x, y, r) => { g.fillStyle = 'rgba(0,0,0,.35)'; g.beginPath(); g.arc(x + 1, y + 1.5, r, 0, 6.3); g.fill(); g.fillStyle = rad(x - r * 0.3, y - r * 0.3, r * 1.3, [[0, '#ffffff'], [0.5, '#aab2ba'], [1, '#4a5058']]); g.beginPath(); g.arc(x, y, r, 0, 6.3); g.fill(); };
        const pivot = (x, y, r) => {                                           // white swivel ring with chrome dome
            g.fillStyle = 'rgba(0,0,0,.3)'; g.beginPath(); g.arc(x + 2, y + 3, r, 0, 6.3); g.fill();
            g.fillStyle = rad(x - r * 0.3, y - r * 0.4, r * 1.4, [[0, '#ffffff'], [1, '#aeb4bb']]); g.beginPath(); g.arc(x, y, r, 0, 6.3); g.fill();
            g.strokeStyle = 'rgba(0,0,0,.25)'; g.lineWidth = 2; g.beginPath(); g.arc(x, y, r * 0.72, 0, 6.3); g.stroke();
            g.fillStyle = rad(x - r * 0.2, y - r * 0.25, r * 0.7, [[0, '#ffffff'], [0.45, '#9fb0c2'], [0.55, '#2b3036'], [1, '#c9d0d6']]); g.beginPath(); g.arc(x, y, r * 0.5, 0, 6.3); g.fill(); bolt(x, y, r * 0.16);
        };
        g.save(); g.clip(cp, 'evenodd');
        const gr = g.createLinearGradient(0, 0, 0, H); gr.addColorStop(0, '#c9cfd6'); gr.addColorStop(0.5, '#9ca3ab'); gr.addColorStop(1, '#565c64'); g.fillStyle = gr; g.fillRect(0, 0, W, H);   // smooth painted shell
        g.fillStyle = rad(W * 0.2, H * 0.1, W * 0.4, [[0, 'rgba(255,255,255,.28)'], [1, 'rgba(255,255,255,0)']]); g.fillRect(0, 0, W, H);                                                  // soft top-left light
        const vg = g.createRadialGradient(W / 2, H * 0.48, Math.min(W, H) * 0.3, W / 2, H * 0.48, Math.max(W, H) * 0.75); vg.addColorStop(0, 'rgba(0,0,0,0)'); vg.addColorStop(1, 'rgba(0,0,0,.5)'); g.fillStyle = vg; g.fillRect(0, 0, W, H);   // depth
        const sm = mk(1.16); g.lineWidth = 2.5; g.strokeStyle = 'rgba(0,0,0,.35)'; g.stroke(sm); g.save(); g.translate(0, 2); g.lineWidth = 1.2; g.strokeStyle = 'rgba(255,255,255,.5)'; g.stroke(sm); g.restore();   // shell panel seam
        const cg = g.createLinearGradient(0, 0, 0, H);                                                                                                                                      // chrome visor frame
        [[0, '#f2f7fb'], [0.22, '#8fb0d0'], [0.46, '#eef1f3'], [0.52, '#222830'], [0.7, '#8d949b'], [1, '#e4eaef']].forEach(([o, c]) => cg.addColorStop(o, c));
        g.lineJoin = 'round'; g.strokeStyle = 'rgba(0,0,0,.4)'; g.lineWidth = 46; g.stroke(sc); g.strokeStyle = cg; g.lineWidth = 36; g.stroke(sc);
        g.strokeStyle = 'rgba(255,255,255,.6)'; g.lineWidth = 6; g.stroke(sc); g.strokeStyle = 'rgba(20,24,30,.7)'; g.lineWidth = 3; g.stroke(sc);
        [[0.1, 0.14], [0.132, 0.115], [0.167, 0.096]].forEach(([x, y]) => bolt(W * x, H * y, 6));                                       // three frame bolts
        pivot(W * 0.03, H * 0.5, 24); pivot(W * 0.97, H * 0.5, 24);                                                                     // side swivels
        const ring = g.createLinearGradient(0, H * 0.92, 0, H);[[0, '#f4f8fb'], [0.3, '#8e969e'], [0.55, '#1f242a'], [0.75, '#b9c1c8'], [1, '#e9eef2']].forEach(([o, c]) => ring.addColorStop(o, c));   // neck ring
        g.beginPath(); g.moveTo(0, H * 0.945); g.quadraticCurveTo(W / 2, H * 1.0, W, H * 0.945); g.lineTo(W, H); g.lineTo(0, H); g.closePath(); g.fillStyle = ring; g.fill(); g.strokeStyle = 'rgba(0,0,0,.4)'; g.lineWidth = 2; g.stroke();
        rrect(g, W / 2 - 22, H * 0.968, 44, 14, 4); g.fillStyle = '#d9dfe4'; g.fill(); g.strokeStyle = 'rgba(0,0,0,.5)'; g.lineWidth = 1.5; g.stroke(); bolt(W / 2 - 12, H * 0.968 + 7, 2.5); bolt(W / 2 + 12, H * 0.968 + 7, 2.5);
        if (isAlert) { g.fillStyle = 'rgba(255,40,30,.12)'; g.fillRect(0, 0, W, H); }
        g.restore();
    }

    function setShape(name) {
        cur = SHAPES[name] ? name : 'real'; const sp = SHAPES[cur], q = (x) => root.querySelector(x), h = sp.hud;
        q('.vp').setAttribute('d', sp.d);
        q('.vs').setAttribute('d', sp.d);
        ['.vin', '.vr', '.vr2'].forEach((k) => q(k).setAttribute('d', sp.d));
        if (sp.inner === false) q('.vr2').setAttribute('d', '');
        q('.vin').style.strokeWidth = (46 * (sp.bezel == null ? 1 : sp.bezel)) + 'px';
        q('.vst').setAttribute('d', sp.struts || ''); q('.vst2').setAttribute('d', sp.struts || '');
        q('.s-pl').style.left = h.pl[0] + '%'; q('.s-pl').style.top = h.pl[1] + '%';
        q('.s-pr').style.right = h.pr[0] + '%'; q('.s-pr').style.top = h.pr[1] + '%';
        q('.tape').style.top = h.tape + '%'; q('.tapemk').style.top = (h.tape - 1.6) + '%';
        q('.s-pc').style.left = h.pc[0] + '%'; q('.s-pc').style.bottom = h.pc[1] + '%';
        drawFrame();
    }

    function say(tx) {
        clearInterval(typeT); let i = 0; E.tx.textContent = '';
        typeT = setInterval(() => { E.tx.textContent = tx.slice(0, ++i); if (i >= tx.length) clearInterval(typeT); }, 22);
    }
    const message = () => (isAlert ? C.alertText : helloText);
    function setAlert(v, speak = true) {
        isAlert = !!v; root.classList.toggle('alert', isAlert); drawFrame();
        if (speak) say(message());
    }
    function resize() {
        W = root.clientWidth || window.innerWidth; H = root.clientHeight || window.innerHeight;
        renderer.setSize(W, H); camera.aspect = W / H; camera.updateProjectionMatrix(); drawFrame();
    }

    const ro = new ResizeObserver(() => { if (!disposed) resize(); }); ro.observe(root);
    on(window, 'pointermove', (e) => {
        const r = root.getBoundingClientRect(); if (!r.width || !r.height) return;
        nx = clamp(((e.clientX - r.left) / r.width) * 2 - 1, -1, 1); ny = clamp(((e.clientY - r.top) / r.height) * 2 - 1, -1, 1);
    });
    if (options.keyboard) on(window, 'keydown', (e) => {
        if (e.key === 'a' || e.key === 'A') setAlert(!isAlert);
        const k = SHAPE_NAMES[+e.key - 1]; if (k) setShape(k);
    });
    on(document, 'visibilitychange', () => { cancelAnimationFrame(raf); if (!document.hidden && !disposed) { last = performance.now(); raf = requestAnimationFrame(frame); } });

    function update(dt) {
        const s = 1 - Math.exp(-dt * 4), idle = reduced ? 0 : Math.sin(t * 0.15) * 0.08;
        yaw = lerp(yaw, -nx * 0.75 + idle, s); pitch = lerp(pitch, -ny * 0.28 + 0.02, s);
        const br = reduced ? 0 : Math.sin(t * 1.4);
        camera.position.set(0, 1.7 + br * 0.01, 0); camera.rotation.set(pitch + br * 0.003, yaw, 0, 'YXZ');
        world.update(t, camera); camera.updateMatrixWorld();

        E.hud.style.transform = `translate(${(-nx * 12).toFixed(1)}px,${(-ny * 7).toFixed(1)}px)`;                        // HUD floats inside the visor
        camera.getWorldDirection(fwd); const gl = Math.max(0, fwd.dot(S)); E.glare.style.opacity = Math.pow(gl, 22) * 0.85;   // sun glare on the visor
        tp.copy(S).multiplyScalar(400).add(camera.position).project(camera); E.glare.style.setProperty('--gx', ((tp.x * 0.5 + 0.5) * 100) + '%'); E.glare.style.setProperty('--gy', ((-tp.y * 0.5 + 0.5) * 100) + '%');
        E.fog.style.opacity = 0.12 + 0.1 * Math.sin(t * 1.4 - 0.6) * (reduced ? 0 : 1);                                    // breath condensation

        const hd = ((-yaw * 180 / Math.PI) % 360 + 360) % 360, card = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'][Math.round(hd / 45) % 8];
        E.tape.style.transform = `translateX(${(-hd * 2.4 % 8).toFixed(1)}px)`; E.hd.textContent = String(Math.round(hd) % 360).padStart(3, '0') + ' ' + card;

        world.hab.getWorldPosition(hp); hp.y += 3.5; const d = camera.position.distanceTo(hp); tp.copy(hp).project(camera);    // target lock on HAB-01
        if (tp.z < 1 && Math.abs(tp.x) < 0.85 && Math.abs(tp.y) < 0.8) {
            const f = H / (2 * Math.tan(camera.fov * Math.PI / 360)), w = clamp(15 / d * f * 1.2, 50, 400), h = w * 0.55;
            Object.assign(E.ret.style, { display: 'block', width: w + 'px', height: h + 'px', transform: `translate(${(tp.x * 0.5 + 0.5) * W - w / 2}px,${(-tp.y * 0.5 + 0.5) * H - h / 2}px)` });
            E.dist.textContent = Math.round(d) + ' m';
        } else E.ret.style.display = 'none';

        hudT += dt; if (hudT > 0.2) {
            hudT = 0; const hr = 74 + (isAlert ? 38 : 0) + Math.sin(t * 0.7) * 4 + Math.random() * 2;
            E.co2.textContent = (0.32 + Math.sin(t * 0.3) * 0.02).toFixed(2) + ' kPa'; E.tank.textContent = (94 - t * 0.02).toFixed(1) + ' %';
            E.hr.textContent = Math.round(hr) + ' bpm'; E.sp.textContent = (isAlert ? 96 : 98) + ' %';
            const m = Math.floor(t / 60) + 14, sc = Math.floor(t % 60); E.eva.textContent = `T+ ${String(m).padStart(2, '0')}:${String(sc).padStart(2, '0')}`;
        }
        const k = ease(t / C.T.fade); E.boot.style.opacity = 1 - k; E.bt2.textContent = t < 0.8 ? 'PRESSURE CHECK ...' : t < 1.4 ? 'VISOR CALIBRATION ...' : 'HUD ONLINE';
        if (!hudOn && t > C.T.hud) { hudOn = true; root.classList.add('on'); msgT = setTimeout(() => say(message()), 900); }
    }
    function frame(now) {
        raf = requestAnimationFrame(frame);
        const dt = Math.min((now - last) / 1000, 0.05); last = now;
        if (options.isActive && !options.isActive()) return; last = now; t += dt; update(dt); renderer.render(scene, camera);
    }

    if (document.fonts && document.fonts.ready) document.fonts.ready.then(() => { if (!disposed) drawFrame(); });
    resize(); setShape(options.shape || 'real'); setAlert(!!options.alert, false); update(0); renderer.render(scene, camera); t = 0; last = performance.now(); raf = requestAnimationFrame(frame);

    return {
        setAlert, say, setShape,
        isAlert: () => isAlert,
        getShape: () => cur,
        setAccent(c) { root.style.setProperty('--a', c || C.accent); },
        replay() { t = 0; hudOn = false; clearTimeout(msgT); root.classList.remove('on'); },
        getContext() { return { THREE, scene, camera, renderer, world, root }; },
        dispose() {
            if (disposed) return; disposed = true; cancelAnimationFrame(raf); clearInterval(typeT); clearTimeout(msgT); ro.disconnect(); cleanups.forEach((f) => f());
            scene.traverse((o) => { o.geometry && o.geometry.dispose();[].concat(o.material || []).forEach((m) => { for (const k in m) m[k] && m[k].isTexture && m[k].dispose(); m.dispose(); }); });
            disp.forEach((o) => o.dispose && o.dispose()); renderer.dispose(); renderer.forceContextLoss(); root.remove();
        },
    };
}

/* ======================================================== React component */
const SuitHelmetScene = forwardRef(function SuitHelmetScene(
    { shape = 'real', alert = false, accent, hello, reducedMotion, showDevPanel = false, className = '', style, active = true },
    ref
) {
    const hostRef = useRef(null);
    const sceneRef = useRef(null);
    const initRef = useRef({});
    initRef.current = { shape, alert, accent, hello, keyboard: showDevPanel };
    const [devAlert, setDevAlert] = useState(alert);
    const activeRef = useRef(active);
    activeRef.current = active;

    useImperativeHandle(ref, () => ({
        setAlert: (v) => sceneRef.current?.setAlert(v),
        say: (tx) => sceneRef.current?.say(tx),
        setShape: (n) => sceneRef.current?.setShape(n),
        setAccent: (c) => sceneRef.current?.setAccent(c),
        replay: () => sceneRef.current?.replay(),
        getContext: () => sceneRef.current?.getContext(),
    }), []);

    // mount / unmount the three.js scene
    useEffect(() => {
        const i = initRef.current;
        const scene = mountSuitScene(hostRef.current, { shape: i.shape, alert: i.alert, accent: i.accent, hello: i.hello, keyboard: i.keyboard, reducedMotion, isActive: () => activeRef.current });
        sceneRef.current = scene;
        return () => { scene.dispose(); sceneRef.current = null; };
    }, [reducedMotion]);

    // controlled props
    useEffect(() => { sceneRef.current?.setShape(shape); }, [shape, reducedMotion]);
    useEffect(() => {
        const s = sceneRef.current; if (!s) return;
        if (s.isAlert() !== !!alert) s.setAlert(!!alert);
        setDevAlert(!!alert);
    }, [alert, reducedMotion]);
    useEffect(() => { if (accent) sceneRef.current?.setAccent(accent); }, [accent, reducedMotion]);

    return (
        <div className={`suit-host ${className}`.trim()} style={style} ref={hostRef}>
            {showDevPanel && (
                <div className="suit-dev">
                    <button type="button" onClick={() => sceneRef.current?.replay()}>Replay</button>
                    {SHAPE_NAMES.map((n, i) => (
                        <button key={n} type="button" onClick={() => sceneRef.current?.setShape(n)}>{i + 1} {n}</button>
                    ))}
                    <button type="button" onClick={() => { const v = !devAlert; setDevAlert(v); sceneRef.current?.setAlert(v); }}>
                        Fire alert (A)
                    </button>
                </div>
            )}
        </div>
    );
});

export default SuitHelmetScene;