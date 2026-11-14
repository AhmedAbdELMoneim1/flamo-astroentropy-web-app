import React, { forwardRef, useEffect, useImperativeHandle, useRef, useState } from 'react';
import * as THREE from 'three'; // written for three r155+ (npm package, same as SpaceCraftScene / SuitHelmetScene)
import { createPortal } from 'react-dom';
import EmberHead from '../siAssistant/EmberHead.jsx'; // adjust the path to match where EmberHead.jsx lives
import './MoonHabitatScene.css';
import { createRealEarth } from '../spaceShared/realEarth.js';

/* =====================================================================
   MoonHabitatScene  –  "Flame in Freefall · Lunar habitat"
   Ported from moonHabitatScene_v2.html (three r128 CDN) to an ES-module
   React component that uses the npm `three` package.

   Usage
     <div style={{ width: '100vw', height: '100vh' }}>
       <MoonHabitatScene ref={habRef} accent="#7fb8ff" />
     </div>

   Props
     accent          CSS colour for glass tint / hologram / HUD (default CONFIG.accent)
     overlay         boolean   show the HUD panels (log + atmosphere), default true
     reducedMotion   boolean   default: prefers-reduced-motion
     showDevPanel    boolean   shows Replay / Dim buttons
     className, style         applied to the host wrapper

   Imperative handle (ref)
     replay(), setDim(0..1), setAccent(css), setOverlay(bool), getContext()
   ===================================================================== */

/* ============================ CONFIG ============================ */
export const CONFIG = {
    accent: '#7fb8ff',
    T: { fadeIn: 1.4, online: 2.2 },
    // habitat atmosphere from the challenge brief: >=30% O2 at <=10.2 psi
    atmosphere: { o2: 30, psi: 10.2 },        // scenario definition (challenge brief); no gravity / exterior temperature: not flameo data
    sun: [0.55, 0.26, -0.5],            // direction TOWARD the sun (through the window)
    cam: { pos: [0, 1.55, 4.2], look: [0, 1.75, -5], fov: 55 },
    window: { w: 4, y0: 0.9, y1: 2.7 },
    // three r155+ removed "legacy lights": intensities are now physical, so the original
    // r128 values look ~PI times too dark. This factor compensates. Tune to taste.
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
// point light with no inverse-square falloff (matches the look the scene was tuned for)
const pointLight = (c, i, d) => new THREE.PointLight(c, i * CONFIG.lightScale, d, 0);
// "raw" colour: keeps the numeric rgb as-is for hand-written shaders (r128 behaviour)
const rawColor = (css) => new THREE.Color().setStyle(css, THREE.LinearSRGBColorSpace);

/* ============================ REGOLITH TEXTURES (procedural, high-res) ============================ */
function buildRegolithTextures(craters, track) {
    const R = seeded(23), WORLD = 520;
    const pn = (x, y, P) => {                       // tileable value noise
        const m = (n) => ((n % P) + P) % P, i = Math.floor(x), j = Math.floor(y), fx = x - i, fy = y - j, u = fx * fx * (3 - 2 * fx), v = fy * fy * (3 - 2 * fy);
        return lerp(lerp(hash(m(i), m(j)), hash(m(i + 1), m(j)), u), lerp(hash(m(i), m(j + 1)), hash(m(i + 1), m(j + 1)), u), v);
    };
    /* --- 1024px seamless detail map: grain, pebbles, craterlets (tiled several times over the terrain) --- */
    const DN = 1024, dc = cvs(DN, DN), dg = dc.getContext('2d'), di = dg.createImageData(DN, DN), dp = di.data;
    for (let y = 0; y < DN; y++) for (let x = 0; x < DN; x++) {
        const u = x / DN, v = y / DN; let s = 0, a = 0.5, f = 4;
        for (let o = 0; o < 6; o++) { s += a * pn(u * f, v * f, f); f *= 2; a *= 0.55; }
        const val = clamp((s - 0.54) * 1.7 + 0.5 + (hash(x * 1.7, y * 1.3) - 0.5) * 0.14), k = (y * DN + x) * 4, g8 = val * 255;
        dp[k] = g8; dp[k + 1] = g8; dp[k + 2] = g8; dp[k + 3] = 255;
    }
    dg.putImageData(di, 0, 0);
    for (let i = 0; i < 1100; i++) {                // pebbles with tiny shadows
        const x = 6 + R() * (DN - 12), y = 6 + R() * (DN - 12), r = 0.8 + R() * R() * 3.2;
        dg.fillStyle = 'rgba(0,0,0,.38)'; dg.beginPath(); dg.ellipse(x + r * 0.7, y + r * 0.8, r, r * 0.8, 0, 0, 6.3); dg.fill();
        dg.fillStyle = 'rgba(255,255,255,.3)'; dg.beginPath(); dg.ellipse(x - r * 0.1, y - r * 0.15, r * 0.8, r * 0.65, 0, 0, 6.3); dg.fill();
    }
    for (let i = 0; i < 70; i++) {                  // craterlets
        const x = 50 + R() * (DN - 100), y = 50 + R() * (DN - 100), r = 8 + R() * R() * 38, gr = dg.createRadialGradient(x + r * 0.15, y + r * 0.15, r * 0.1, x, y, r * 1.15);
        gr.addColorStop(0, 'rgba(0,0,0,.30)'); gr.addColorStop(0.7, 'rgba(0,0,0,.18)'); gr.addColorStop(0.86, 'rgba(255,255,255,.28)'); gr.addColorStop(1, 'rgba(255,255,255,0)');
        dg.fillStyle = gr; dg.beginPath(); dg.arc(x, y, r * 1.15, 0, 6.3); dg.fill();
    }
    const detail = track(new THREE.CanvasTexture(dc)); detail.wrapS = detail.wrapT = THREE.RepeatWrapping; detail.anisotropy = 8;

    /* --- 2048px albedo map covering the whole terrain: large patches, crater rims, ejecta halos, rock specks --- */
    const MN = 2048, mc = cvs(MN, MN), mg = mc.getContext('2d'), sm = cvs(512, 512), sx = sm.getContext('2d'), si = sx.createImageData(512, 512), sp = si.data;
    for (let y = 0; y < 512; y++) for (let x = 0; x < 512; x++) {
        const n = vnoise(x / 512 * 10, y / 512 * 10) * 0.5 + vnoise(x / 512 * 28, y / 512 * 28) * 0.3 + vnoise(x / 512 * 70, y / 512 * 70) * 0.2, val = (0.76 + n * 0.32) * 255, k = (y * 512 + x) * 4;
        sp[k] = val; sp[k + 1] = val * 0.985; sp[k + 2] = val * 0.96; sp[k + 3] = 255;
    }
    sx.putImageData(si, 0, 0); mg.imageSmoothingEnabled = true; mg.imageSmoothingQuality = 'high'; mg.drawImage(sm, 0, 0, MN, MN);
    craters.forEach((c) => {
        const cx = (c.x + WORLD / 2) / WORLD * MN, cy = (c.z + WORLD / 2) / WORLD * MN, r = c.r / WORLD * MN;
        const gr = mg.createRadialGradient(cx, cy, r * 0.9, cx, cy, r * 2.4);
        gr.addColorStop(0, 'rgba(255,250,240,.22)'); gr.addColorStop(1, 'rgba(255,250,240,0)');
        mg.fillStyle = gr; mg.beginPath(); mg.arc(cx, cy, r * 2.4, 0, 6.3); mg.fill();                         // ejecta halo
        mg.fillStyle = 'rgba(40,38,36,.16)'; mg.beginPath(); mg.arc(cx, cy, r * 0.95, 0, 6.3); mg.fill();       // darker floor
        mg.strokeStyle = 'rgba(255,252,245,.28)'; mg.lineWidth = Math.max(2, r * 0.06); mg.beginPath(); mg.arc(cx, cy, r, 0, 6.3); mg.stroke();   // bright rim
    });
    for (let i = 0; i < 16000; i++) {               // rocks / grain specks
        const x = R() * MN, y = R() * MN, s = 1 + R() * 2.2;
        mg.fillStyle = R() < 0.5 ? 'rgba(20,18,16,.28)' : 'rgba(255,255,250,.22)'; mg.fillRect(x, y, s, s);
    }
    const macro = track(new THREE.CanvasTexture(mc)); macro.anisotropy = 8;
    return { macro, detail };
}

/* ============================ EXTERIOR: regolith, rocks, stars, Earth ============================ */
function buildExterior(scene, track) {
    const R = seeded(11), S = new THREE.Vector3(...CONFIG.sun).normalize();
    // craters (kept away from the window)
    const craters = [];
    while (craters.length < 46) {
        const x = (R() - 0.5) * 460, z = (R() - 0.5) * 460, r = 5 + R() * R() * 45;
        if (Math.hypot(x, z + 5) > 22 + r * 0.5) craters.push({ x, z, r, d: 0.25 + R() * 0.35 });
    }
    const H = (x, z) => {
        const m = ease((Math.hypot(x, z + 8) - 10) / 40);
        let h = (vnoise(x * 0.018, z * 0.018) * 9 + vnoise(x * 0.09, z * 0.09) * 1.4 + vnoise(x * 0.4, z * 0.4) * 0.12 + vnoise(x * 1.3, z * 1.3) * 0.04) * m;
        for (const c of craters) {
            const d = Math.hypot(x - c.x, z - c.z) / c.r;
            if (d < 1.6) h += (d < 1 ? -c.r * c.d * 0.35 * (1 - d * d) : 0) + c.r * 0.05 * Math.exp(-Math.pow((d - 1) / 0.18, 2));
        }
        return h;
    };
    const geo = track(new THREE.PlaneGeometry(520, 520, 360, 360)); geo.rotateX(-Math.PI / 2);
    const p = geo.attributes.position;
    for (let i = 0; i < p.count; i++) p.setY(i, H(p.getX(i), p.getZ(i)) - 0.3);
    geo.computeVertexNormals();
    const n = geo.attributes.normal, col = new Float32Array(p.count * 3);
    for (let i = 0; i < p.count; i++) {
        const l = Math.max(0, n.getX(i) * S.x + n.getY(i) * S.y + n.getZ(i) * S.z);
        const g = (0.1 + 1.0 * l) * (0.9 + 0.2 * hash(p.getX(i) * 3.1, p.getZ(i) * 3.1));
        col.set([0.66 * g, 0.63 * g, 0.6 * g], i * 3);
    }
    geo.setAttribute('color', new THREE.BufferAttribute(col, 3));
    const RT = buildRegolithTextures(craters, track);
    const terrainM = track(new THREE.MeshBasicMaterial({ vertexColors: true, map: RT.macro }));
    terrainM.onBeforeCompile = (sh) => {              // three detail layers at different scales = no visible tiling, sharp up close
        sh.uniforms.detailMap = { value: RT.detail };
        // NOTE: modern three names the map uv varying `vMapUv` (r128 used `vUv`)
        sh.fragmentShader = 'uniform sampler2D detailMap;\n' + sh.fragmentShader.replace('#include <map_fragment>',
            '#include <map_fragment>\n float d1=texture2D(detailMap,vMapUv*130.).r; float d2=texture2D(detailMap,vMapUv*19.).r; float d3=texture2D(detailMap,vMapUv*3.).r; diffuseColor.rgb*=.45+1.1*(d1*.45+d2*.35+d3*.2);');
    };
    scene.add(new THREE.Mesh(geo, terrainM));

    // boulders
    const rg = track(new THREE.IcosahedronGeometry(1, 1)), rm = track(new THREE.MeshStandardMaterial({ color: 0x8a867f, roughness: 1, flatShading: true }));
    for (let i = 0; i < 40; i++) {
        const x = (R() - 0.5) * 90, z = -9 - R() * 70, s = 0.15 + R() * R() * 1.6, m = new THREE.Mesh(rg, rm);
        m.position.set(x, H(x, z) - 0.3 + s * 0.25, z); m.scale.set(s * (1 + R() * 0.6), s * 0.7, s * (1 + R() * 0.6)); m.rotation.set(R() * 3, R() * 3, R() * 3); scene.add(m);
    }
    for (let i = 0; i < 30; i++) {                 // boulders close to the habitat so the glass walls show the ground
        const side = R() < 0.5 ? -1 : 1, x = side * (5 + R() * 35), z = -8 + R() * 20, s = 0.1 + R() * R() * 1.0, m = new THREE.Mesh(rg, rm);
        m.position.set(x, H(x, z) - 0.3 + s * 0.25, z); m.scale.set(s * (1 + R() * 0.6), s * 0.7, s * (1 + R() * 0.6)); m.rotation.set(R() * 3, R() * 3, R() * 3); scene.add(m);
    }
    // stars
    const sp = [], sc = [];
    for (let i = 0; i < 2600; i++) {
        const u = R() * 2 - 1, a = R() * 6.283, r = Math.sqrt(1 - u * u), b = 0.3 + R() * 0.7;
        sp.push(400 * r * Math.cos(a), Math.abs(400 * u) * 0.9 + 5, 400 * r * Math.sin(a)); sc.push(b, b, b * (0.9 + R() * 0.2));
    }
    const sg = track(new THREE.BufferGeometry());
    sg.setAttribute('position', new THREE.Float32BufferAttribute(sp, 3)); sg.setAttribute('color', new THREE.Float32BufferAttribute(sc, 3));
    scene.add(new THREE.Points(sg, track(new THREE.PointsMaterial({ size: 1.6, sizeAttenuation: false, vertexColors: true, fog: false }))));

    // real Earth (same textures and shader as the opening scene)
    const earth = track(createRealEarth({ radius: 3.2, sun: new THREE.Vector3(0.7, 0.1, 0.6) }));
    earth.group.position.set(-10, 14, -150);
    earth.group.scale.setScalar(3);
    scene.add(earth.group);
    return { update(t) { earth.update(t); } };
}

/* ============================ HABITAT INTERIOR ============================ */
function buildHabitat(scene, track, A) {
    // A.accent = current accent (CSS string). Read every frame so setAccent() takes effect live.
    const LS = CONFIG.lightScale;
    const std = (c, r, m, o) => track(new THREE.MeshStandardMaterial(Object.assign({ color: c, roughness: r, metalness: m }, o)));
    const bas = (c, o) => track(new THREE.MeshBasicMaterial(Object.assign({ color: c }, o)));
    const R = seeded(7);
    const tints = [], accentMats = [];
    const mkT = (w, h, fn, rep) => {
        const c = cvs(w, h); fn(c.getContext('2d'), w, h);
        const t = track(new THREE.CanvasTexture(c)); t.wrapS = t.wrapT = THREE.RepeatWrapping; t.colorSpace = THREE.SRGBColorSpace; t.anisotropy = 4;
        if (rep) t.repeat.set(rep[0], rep[1]); return t;
    };
    const add = (geo, mat, x = 0, y = 0, z = 0, parent = scene) => { const o = new THREE.Mesh(track(geo), mat); o.position.set(x, y, z); parent.add(o); return o; };
    const CY = 1.4, RAD = 3, ZE = -5;

    // shell: structural glass envelope (no opaque wall panels)
    const glassMat = (grid) => {
        const tint = { value: rawColor(A.accent) }; tints.push(tint);
        return track(new THREE.ShaderMaterial({
            transparent: true, depthWrite: false, side: THREE.BackSide,
            uniforms: { tint, grid: { value: new THREE.Vector2(grid[0], grid[1]) } },
            vertexShader: 'varying vec3 vN,vV;varying vec2 vU;void main(){vU=uv;vec4 mv=modelViewMatrix*vec4(position,1.);vN=normalize(normalMatrix*normal);vV=-mv.xyz;gl_Position=projectionMatrix*mv;}',
            fragmentShader: 'uniform vec3 tint;uniform vec2 grid;varying vec3 vN,vV;varying vec2 vU;void main(){' +
                'float f=pow(1.-abs(dot(normalize(vN),normalize(vV))),3.);' +
                'vec2 g=abs(fract(vU*grid-.5)-.5);float seam=1.-smoothstep(0.,.03,min(g.x,g.y));' +
                'vec3 c=mix(vec3(.55,.75,1.),tint,.35)*(.25+f*1.1+seam*.7);' +
                'gl_FragColor=vec4(c,.035+f*.36+seam*.16);}',
        }));
    };
    const tube = add(new THREE.CylinderGeometry(RAD, RAD, 13, 96, 1, true), glassMat([36, 16]), 0, CY, 1.5); tube.rotation.x = Math.PI / 2; tube.renderOrder = 2;
    const ribM = std(0x8f97a3, 0.35, 0.8), fm = std(0x2b3038, 0.4, 0.8);
    for (let i = 0; i <= 8; i++) add(new THREE.TorusGeometry(RAD - 0.03, i === 0 ? 0.1 : 0.07, 10, 64), ribM, 0, CY, ZE + i * 1.625);   // frames
    for (let k = 0; k < 24; k++) {                  // longitudinal mullions holding the panes
        const an = k / 24 * Math.PI * 2, y = CY + Math.sin(an) * RAD; if (y < 0.15 || k === 6) continue;
        const m = add(new THREE.CylinderGeometry(0.035, 0.035, 13, 8), ribM, Math.cos(an) * (RAD - 0.03), y, 1.5); m.rotation.x = Math.PI / 2;
    }
    [-1, 1].forEach((s) => add(new THREE.BoxGeometry(0.3, 0.22, 13), fm, s * 2.66, 0.1, 1.5));   // floor-level sills

    // end wall: glass disc inside a metal ring, window portal frame kept as structure
    const endGlass = add(new THREE.CircleGeometry(RAD - 0.03, 64), glassMat([10, 10]), 0, CY, ZE - 0.01); endGlass.renderOrder = 2; endGlass.material.side = THREE.DoubleSide;
    const W = CONFIG.window, hw = W.w / 2, fh = W.y1 - W.y0, fc = (W.y0 + W.y1) / 2;
    add(new THREE.BoxGeometry(W.w + 0.4, 0.2, 0.35), fm, 0, W.y1 + 0.1, ZE);
    add(new THREE.BoxGeometry(W.w + 0.4, 0.2, 0.35), fm, 0, W.y0 - 0.1, ZE);
    [-1, 1].forEach((s) => add(new THREE.BoxGeometry(0.2, fh, 0.35), fm, s * (hw + 0.1), fc, ZE));
    add(new THREE.BoxGeometry(0.08, fh, 0.12), fm, 0, fc, ZE - 0.02);                     // mullion
    const winA = new THREE.Object3D(); winA.position.set(0, fc, ZE); scene.add(winA);
    const sill = bas(A.accent); accentMats.push(sill);
    add(new THREE.BoxGeometry(W.w, 0.05, 0.06), sill, 0, W.y0 + 0.02, ZE + 0.18);         // sill light

    // floor + light strips
    const floorT = mkT(512, 512, (g, w, h) => {
        g.fillStyle = '#3a3f47'; g.fillRect(0, 0, w, h);
        g.strokeStyle = '#5b626d'; g.lineWidth = 3; for (let i = 0; i <= w; i += 64) { g.beginPath(); g.moveTo(i, 0); g.lineTo(i, h); g.moveTo(0, i); g.lineTo(w, i); g.stroke(); }
        g.fillStyle = '#20242a'; for (let x = 8; x < w; x += 16) for (let y = 8; y < h; y += 16) if ((x + y) % 64 < 40) g.fillRect(x, y, 5, 5);
    }, [3, 6]);
    const floor = add(new THREE.PlaneGeometry(5.3, 12), std(0xffffff, 0.5, 0.6, { map: floorT }), 0, 0, 1); floor.rotation.x = -Math.PI / 2;
    const stripM = bas(A.accent); accentMats.push(stripM);
    [-1.7, 1.7].forEach((x) => add(new THREE.BoxGeometry(0.06, 0.02, 11), stripM, x, 0.015, 1));
    add(new THREE.BoxGeometry(0.5, 0.02, 11), bas(0xe8f2ff, { transparent: true, opacity: 0.0 }), 0, 4.3, 1);
    add(new THREE.BoxGeometry(0.35, 0.04, 11), bas(new THREE.Color(1.8, 1.9, 2.1)), 0, CY + RAD - 0.08, 1);

    // central workstation with hologram
    const desk = add(new THREE.BoxGeometry(2.4, 0.08, 0.95), std(0xdfe3e8, 0.3, 0.3), 0, 0.82, -1.6);
    [-1, 1].forEach((s) => add(new THREE.BoxGeometry(0.1, 0.8, 0.8), std(0x5a606b, 0.5, 0.7), s * 1.05, 0.4, -1.6));
    add(new THREE.BoxGeometry(2.2, 0.5, 0.06), std(0x2a2f37, 0.5, 0.6), 0, 0.45, -1.95);
    [[-0.7, 0.1], [-0.4, -0.1], [0.5, 0.1]].forEach(([x, z], i) => add(new THREE.BoxGeometry(0.3, 0.16, 0.22), std(i === 1 ? 0xd98a1a : 0xc5c9cf, 0.5, 0.4), x, 0.94, -1.6 + z));
    const holoC = cvs(256, 256), hg = holoC.getContext('2d'), holoT = track(new THREE.CanvasTexture(holoC));
    const holo = add(new THREE.PlaneGeometry(0.9, 0.9), bas(0xffffff, { map: holoT, transparent: true, opacity: 0.85, blending: THREE.AdditiveBlending, depthWrite: false, side: THREE.DoubleSide }), 0, 1.4, -1.6);
    const drawHolo = (t) => {
        hg.clearRect(0, 0, 256, 256); hg.strokeStyle = A.accent; hg.lineWidth = 2; hg.shadowColor = A.accent; hg.shadowBlur = 8;
        for (let k = 1; k <= 3; k++) { hg.beginPath(); hg.arc(128, 128, k * 36, 0, 6.3); hg.globalAlpha = 0.9 - k * 0.2; hg.stroke(); }
        hg.globalAlpha = 1; const a = t * 1.2; hg.beginPath(); hg.moveTo(128, 128); hg.lineTo(128 + Math.cos(a) * 112, 128 + Math.sin(a) * 112); hg.stroke();
        hg.fillStyle = '#fff'; hg.font = '14px "Chakra Petch",monospace'; hg.fillText('HAB-01 / O2 30%', 80, 244); holoT.needsUpdate = true;
    };

    // wall rack with live screens (left)
    const rack = new THREE.Group(); rack.position.set(-2.38, 0, -0.2); scene.add(rack);
    add(new THREE.BoxGeometry(0.5, 2.0, 3.6), std(0x4a505a, 0.5, 0.6), 0, 1, 0, rack);
    const screens = [];
    for (let i = 0; i < 3; i++) {
        const c = cvs(256, 192), t = track(new THREE.CanvasTexture(c));
        const m = add(new THREE.PlaneGeometry(0.95, 0.7), bas(0xffffff, { map: t }), 0.26, 1.25, -1.1 + i * 1.1, rack); m.rotation.y = Math.PI / 2;
        screens.push({ g: c.getContext('2d'), t, i });
    }
    // tanks (right)
    const tanks = [-3.4, -2.4].map((z) => {
        const tg = new THREE.Group(); tg.position.set(2.3, 0, z); scene.add(tg);
        add(new THREE.CylinderGeometry(0.32, 0.32, 1.7, 32), std(0xc9ccd1, 0.35, 0.7), 0, 0.85, 0, tg);
        add(new THREE.CylinderGeometry(0.325, 0.325, 0.18, 32), std(0x2a62c9, 0.5, 0.3), 0, 1.1, 0, tg);
        add(new THREE.SphereGeometry(0.32, 32, 12, 0, 6.3, 0, Math.PI / 2), std(0xc9ccd1, 0.35, 0.7), 0, 1.7, 0, tg);
        return tg;
    });
    // airlock hatch (right wall)
    const hatch = new THREE.Group(); hatch.position.set(2.55, 1.1, 1.6); hatch.rotation.y = -Math.PI / 2; scene.add(hatch);
    add(new THREE.TorusGeometry(0.62, 0.08, 12, 48), std(0x9aa3af, 0.3, 0.9), 0, 0, 0, hatch);
    add(new THREE.CircleGeometry(0.6, 48), std(0x3a3f47, 0.5, 0.7), 0, 0, -0.02, hatch);
    add(new THREE.CircleGeometry(0.12, 24), std(0x9aa3af, 0.3, 0.9), 0, 0, 0.01, hatch);
    const hatchLed = bas(0x1fe08a); add(new THREE.SphereGeometry(0.05, 12, 8), hatchLed, 0.75, 0.5, 0, hatch);
    // handrails + amber blinkers
    [-1, 1].forEach((s) => { const r = add(new THREE.CylinderGeometry(0.03, 0.03, 10, 12), std(0x9aa3af, 0.3, 0.9), s * 2.3, 1.5, 1); r.rotation.x = Math.PI / 2; });
    const ambM = [[-2.2, 2.7, -4.9], [2.2, 2.7, -4.9], [0, 3.8, -4.9]].map((p) => { const m = bas(new THREE.Color(3, 1.3, 0.1), { transparent: true }); add(new THREE.SphereGeometry(0.06, 12, 8), m, ...p); return m; });

    // lights
    scene.add(new THREE.HemisphereLight(0xcfd8e8, 0x2a2f37, 0.9 * LS));
    const key = pointLight(0xfff2dd, 1.4, 16); key.position.set(0, 3.9, 0.5);
    const fill = pointLight(0xbfd8ff, 1.1, 14); fill.position.set(0, 3.6, -3.5);
    const sun = new THREE.DirectionalLight(0xfff1dc, 0.9 * LS); sun.position.set(...CONFIG.sun).multiplyScalar(30);
    const amL = pointLight(0xff9a2a, 1, 6); amL.position.set(0, 2.6, -4.2);
    scene.add(key, fill, sun, amL);

    // floating dust
    const N = 200, dp = new Float32Array(N * 3), base = new Float32Array(N * 3);
    for (let i = 0; i < N; i++) { base[i * 3] = (R() - 0.5) * 5; base[i * 3 + 1] = 0.3 + R() * 3.6; base[i * 3 + 2] = -4.5 + R() * 9; }
    const dg = track(new THREE.BufferGeometry()); dg.setAttribute('position', new THREE.BufferAttribute(dp, 3));
    scene.add(new THREE.Points(dg, track(new THREE.PointsMaterial({ color: 0xf4f6fa, size: 0.02, transparent: true, opacity: 0.45, depthWrite: false, blending: THREE.AdditiveBlending }))));

    let fr = 0;
    return {
        anchors: { hologram: holo, workstation: desk, rack, hatch, tankA: tanks[0], tankB: tanks[1], window: winA },
        setAccent(css) {
            A.accent = css;
            tints.forEach((t) => t.value.copy(rawColor(css)));
            accentMats.forEach((m) => m.color.set(css));
        },
        update(t, dt) {
            fr++;
            if (fr % 3 === 1) drawHolo(t);
            holo.rotation.y = Math.sin(t * 0.4) * 0.35;
            holo.position.y = 1.4 + Math.sin(t * 1.3) * 0.02;
            if (fr % 8 === 1) screens.forEach((s) => {
                const g = s.g; g.fillStyle = '#05080c'; g.fillRect(0, 0, 256, 192);
                g.fillStyle = A.accent; for (let k = 0; k < 9; k++) g.fillRect(12, 14 + k * 19, 20 + (Math.sin(t * (0.8 + s.i * 0.3) + k * 1.7) * 0.5 + 0.5) * 210, 8);
                s.t.needsUpdate = true;
            });
            ambM.forEach((m, i) => { m.opacity = 0.35 + 0.65 * Math.abs(Math.sin(t * 1.6 + i)); });
            amL.intensity = (0.3 + 1 * Math.abs(Math.sin(t * 1.6))) * LS;
            hatchLed.color.setRGB(0.1, 0.88 * (0.6 + 0.4 * Math.sin(t * 3)), 0.54);
            key.intensity = (1.4 + Math.sin(t * 50) * 0.01) * LS;
            for (let i = 0; i < N; i++) {
                base[i * 3 + 1] += dt * 0.03; if (base[i * 3 + 1] > 4.2) base[i * 3 + 1] = 0.3;
                dp[i * 3] = base[i * 3] + Math.sin(t * 0.3 + i) * 0.15; dp[i * 3 + 1] = base[i * 3 + 1]; dp[i * 3 + 2] = base[i * 3 + 2] + Math.cos(t * 0.25 + i) * 0.15;
            }
            dg.attributes.position.needsUpdate = true;
        },
    };
}

/* ============================ OVERLAY ============================ */
function buildOverlay(root, accent) {
    const ov = document.createElement('div'); ov.className = 'mh-ov'; ov.style.setProperty('--a', accent); root.appendChild(ov);
    const A = CONFIG.atmosphere;
    ov.innerHTML = `<div class="mh-pnl mh-log"><span>S3 &middot; LUNAR HABITAT &middot; </span><span class="lv">PRESSURIZING</span></div>
<div class="mh-pnl mh-atm"><div class="r"><span>Oxygen</span><em class="o2"></em></div><div class="r"><span>Pressure</span><em class="ps"></em></div>
</div>`;
    const lv = ov.querySelector('.lv'), o2 = ov.querySelector('.o2'), ps = ov.querySelector('.ps');
    return {
        setAccent(c) { ov.style.setProperty('--a', c); },
        setVisible(v) { ov.style.display = v ? '' : 'none'; },
        update(t) {
            lv.textContent = t < CONFIG.T.online ? 'PRESSURIZING' : 'HABITAT ONLINE';
            const k = ease(t / CONFIG.T.online), j = Math.sin(t * 2) * 0.03;
            o2.textContent = `${(lerp(21, A.o2, k) + j).toFixed(1)} %`; ps.textContent = `${(lerp(14.7, A.psi, k) + j * 0.1).toFixed(2)} psi`;
        },
        dispose() { ov.remove(); },
    };
}

/* ============================ mountMoonHabitatScene ============================
   Imperative three.js scene. Appends its own root <div class="mh-root"> to `container`
   and returns a controller. Always call .dispose() on unmount. */
export function mountMoonHabitatScene(container, options) {
    options = options || {};
    const C = CONFIG, A = { accent: options.accent || C.accent };
    const reduced = options.reducedMotion != null ? !!options.reducedMotion : window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const disp = [], cleanups = [], track = (o) => (disp.push(o), o);
    const on = (t, e, f) => { t.addEventListener(e, f); cleanups.push(() => t.removeEventListener(e, f)); };

    const root = document.createElement('div'); root.className = 'mh-root'; container.appendChild(root);
    const renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: 'high-performance' });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2)); renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.ACESFilmicToneMapping; renderer.toneMappingExposure = 1.0; renderer.setClearColor(0x000000);
    root.appendChild(renderer.domElement);
    const scene = new THREE.Scene(), camera = new THREE.PerspectiveCamera(C.cam.fov, 1, 0.05, 900);
    const ext = buildExterior(scene, track), hab = buildHabitat(scene, track, A), overlay = buildOverlay(root, A.accent);
    overlay.setVisible(options.overlay !== false);
    const fade = document.createElement('div'); fade.className = 'mh-fade'; root.appendChild(fade);

    /* ---------------- Ember: scanner robot ---------------- */
    const V3 = THREE.Vector3, lookRef = options.lookRef;
    const headEl = document.createElement('div'); headEl.className = 'mh-ember'; root.appendChild(headEl);
    const tagEl = document.createElement('div'); tagEl.className = 'mh-tag'; tagEl.style.setProperty('--a', A.accent); root.appendChild(tagEl);
    const LABELS = { hologram: 'HOLOGRAM // O2 30%', workstation: 'WORKSTATION', rack: 'AVIONICS RACK', hatch: 'AIRLOCK HATCH', tankA: 'O2 TANK A', tankB: 'O2 TANK B', window: 'VIEWPORT' };
    const ep = new V3(), elook = new V3(), _b = new THREE.Box3();
    let inited = false, hasLook = false, tw = null, sc = null;
    const bgeo = new THREE.BufferGeometry(); bgeo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(6), 3));
    const beam = new THREE.Line(bgeo, new THREE.LineBasicMaterial({ color: A.accent, transparent: true, opacity: 0.85 })); beam.frustumCulled = false; beam.visible = false; scene.add(beam);
    const dot = new THREE.Mesh(new THREE.SphereGeometry(0.04, 12, 8), new THREE.MeshBasicMaterial({ color: A.accent })); dot.visible = false; scene.add(dot);

    const centerOf = (o) => { _b.setFromObject(o); return _b.isEmpty() ? o.getWorldPosition(new V3()) : _b.getCenter(new V3()); };
    const homePos = () => { camera.updateMatrixWorld(); return new V3(-0.62, -0.5, 0.5).unproject(camera).sub(camera.position).normalize().multiplyScalar(2).add(camera.position); };
    const hoverPos = (c) => c.clone().add(camera.position.clone().sub(c).normalize().multiplyScalar(1.1)).add(new V3(0, 0.3, 0));
    const flyTo = (v, s) => { tw = s > 0 ? { a: ep.clone(), b: v.clone(), t: 0, s } : (ep.copy(v), null); };

    function scan(ids, slot) {
        slot = slot || 2.6;
        if (sc) sc.res();
        const list = (ids && ids.length ? ids : Object.keys(hab.anchors)).filter((k) => hab.anchors[k]);
        return new Promise((res) => { sc = { list, slot, t: 0, idx: -1, res }; });
    }

    function emberUpdate(dt) {
        camera.updateMatrixWorld();
        camera.matrixWorldInverse.copy(camera.matrixWorld).invert(); // keep project() in sync with this frame's camera
        if (!inited) { ep.copy(homePos()); inited = true; }
        if (tw) {
            tw.t += dt; const k = Math.min(1, tw.t / tw.s), e = k < 0.5 ? 2 * k * k : 1 - Math.pow(-2 * k + 2, 2) / 2;
            ep.lerpVectors(tw.a, tw.b, e); if (k >= 1) tw = null;
        } else if (!sc) ep.lerp(homePos(), 1 - Math.exp(-6 * dt));

        const Wd = root.clientWidth, Hd = root.clientHeight;
        if (sc) {
            sc.t += dt; const i = Math.floor(sc.t / sc.slot);
            if (i >= sc.list.length) {
                const r = sc.res; sc = null; hasLook = false;
                beam.visible = dot.visible = false; tagEl.style.opacity = 0;
                flyTo(homePos(), reduced ? 0 : 0.9); r();
            } else {
                const key = sc.list[i], c = centerOf(hab.anchors[key]), lt = sc.t - i * sc.slot;
                if (i !== sc.idx) { sc.idx = i; tagEl.style.opacity = 0; flyTo(hoverPos(c), reduced ? 0 : sc.slot * 0.4); }
                elook.copy(c); hasLook = true;
                const e = ep.clone().lerp(c, clamp((lt - sc.slot * 0.2) / (sc.slot * 0.3)));
                const pa = bgeo.attributes.position; pa.setXYZ(0, ep.x, ep.y, ep.z); pa.setXYZ(1, e.x, e.y, e.z); pa.needsUpdate = true;
                dot.position.copy(e); beam.visible = dot.visible = lt > sc.slot * 0.2;
                if (lt >= sc.slot * 0.45 && Wd) {
                    const q = c.clone().project(camera);
                    tagEl.textContent = LABELS[key] || key.toUpperCase();
                    tagEl.style.left = (q.x * 0.5 + 0.5) * Wd + 'px'; tagEl.style.top = (-q.y * 0.5 + 0.5) * Hd + 'px'; tagEl.style.opacity = 1;
                }
            }
        }

        // pin the EmberHead canvas to the anchor
        const c2 = ep.clone().applyMatrix4(camera.matrixWorldInverse);
        if (!Wd || c2.z > -0.1) { headEl.style.visibility = 'hidden'; return; }
        const f = Hd / (2 * Math.tan(camera.fov * Math.PI / 360)), px = 0.55 * f / -c2.z;
        const p = ep.clone().project(camera);
        headEl.style.width = headEl.style.height = Math.round(px) + 'px';
        headEl.style.transform = 'translate3d(' + ((p.x * 0.5 + 0.5) * Wd - px / 2).toFixed(1) + 'px,' + ((-p.y * 0.5 + 0.5) * Hd - px / 2).toFixed(1) + 'px,0)';
        headEl.style.visibility = 'visible';
        if (lookRef) {
            if (hasLook) { const q = elook.clone().project(camera); lookRef.current = { x: clamp((q.x - p.x) * 2.5, -1, 1), y: clamp((q.y - p.y) * 2.5, -1, 1) }; }
            else lookRef.current = null;
        }
    }

    let t = 0, last = 0, raf = 0, nx = 0, ny = 0, yaw = 0, pitch = 0, disposed = false, W = 1, H = 1;
    const pos = new THREE.Vector3(...C.cam.pos), look = new THREE.Vector3(...C.cam.look), eu = new THREE.Euler(0, 0, 0, 'YXZ'), qq = new THREE.Quaternion();
    function resize() {
        W = root.clientWidth || window.innerWidth; H = root.clientHeight || window.innerHeight;
        renderer.setSize(W, H); camera.aspect = W / H; camera.updateProjectionMatrix();
    }
    const ro = new ResizeObserver(() => { if (!disposed) resize(); }); ro.observe(root);
    on(window, 'pointermove', (e) => {
        const r = root.getBoundingClientRect(); if (!r.width || !r.height) return;
        nx = clamp(((e.clientX - r.left) / r.width) * 2 - 1, -1, 1); ny = clamp(((e.clientY - r.top) / r.height) * 2 - 1, -1, 1);
    });
    on(document, 'visibilitychange', () => { cancelAnimationFrame(raf); if (!document.hidden && !disposed) { last = performance.now(); raf = requestAnimationFrame(frame); } });

    function update(dt) {
        const push = reduced ? 0 : ease(t / 14);
        camera.position.set(pos.x + (reduced ? 0 : Math.sin(t * 0.2) * 0.03), pos.y + (reduced ? 0 : Math.cos(t * 0.27) * 0.02), pos.z - push * 0.9);
        camera.lookAt(look);
        if (!reduced) {
            const s = 1 - Math.exp(-dt * 5); yaw = lerp(yaw, -nx * 4, s); pitch = lerp(pitch, -ny * 2.5, s);
            eu.set(THREE.MathUtils.degToRad(pitch), THREE.MathUtils.degToRad(yaw), 0); camera.quaternion.multiply(qq.setFromEuler(eu));
        }
        ext.update(t); hab.update(t, dt); overlay.update(t); emberUpdate(dt);
        fade.style.opacity = 1 - ease(t / C.T.fadeIn);
    }
    function frame(now) {
        raf = requestAnimationFrame(frame);
        const dt = Math.min((now - last) / 1000, 0.05); last = now;
        if (options.isActive && !options.isActive()) return;
        t += dt; update(dt); renderer.render(scene, camera);
    }
    resize(); update(0); renderer.render(scene, camera); t = 0; last = performance.now(); raf = requestAnimationFrame(frame);

    return {
        replay() { t = 0; },
        setDim(v) { renderer.domElement.style.filter = v ? `brightness(${1 - 0.6 * v}) blur(${2 * v}px)` : 'none'; },
        setAccent(c) { if (!c) return; hab.setAccent(c); overlay.setAccent(c); beam.material.color.set(c); dot.material.color.set(c); tagEl.style.setProperty('--a', c); },
        scan,
        getHeadHost() { return headEl; },
        setOverlay(v) { overlay.setVisible(!!v); },
        getContext() { return { THREE, scene, camera, renderer, root }; },
        dispose() {
            if (disposed) return; disposed = true; cancelAnimationFrame(raf); ro.disconnect(); cleanups.forEach((f) => f()); sc && sc.res();
            scene.traverse((o) => {
                o.geometry && o.geometry.dispose();
                o.material && [].concat(o.material).forEach((m) => { for (const k in m) m[k] && m[k].isTexture && m[k].dispose(); m.dispose(); });
            });
            disp.forEach((o) => o.dispose && o.dispose()); overlay.dispose(); renderer.dispose(); renderer.forceContextLoss(); root.remove();
        },
    };
}

/* ======================================================== React component */
const MoonHabitatScene = forwardRef(function MoonHabitatScene(
    { accent, overlay = true, reducedMotion, showDevPanel = false, onScanDone, emberState, emberAmplitude = 0, emberAlert = false, className = '', style, active = true },
    ref
) {
    const hostRef = useRef(null);
    const sceneRef = useRef(null);
    const initRef = useRef({});
    initRef.current = { accent, overlay };
    const [dimmed, setDimmed] = useState(false);
    const [headHost, setHeadHost] = useState(null);
    const [scanning, setScanning] = useState(false);
    const lookRef = useRef(null);
    const doneRef = useRef(null);
    doneRef.current = onScanDone;
    const activeRef = useRef(active);
    activeRef.current = active;

    const runScan = async (ids) => {
        const s = sceneRef.current; if (!s) return;
        setScanning(true);
        await s.scan(ids);
        setScanning(false);
        doneRef.current?.(ids);
    };

    useImperativeHandle(ref, () => ({
        scan: runScan,
        replay: () => sceneRef.current?.replay(),
        setDim: (v) => sceneRef.current?.setDim(v),
        setAccent: (c) => sceneRef.current?.setAccent(c),
        setOverlay: (v) => sceneRef.current?.setOverlay(v),
        getContext: () => sceneRef.current?.getContext(),
    }), []);

    // mount / unmount the three.js scene
    useEffect(() => {
        const i = initRef.current;
        const scene = mountMoonHabitatScene(hostRef.current, { accent: i.accent, overlay: i.overlay, reducedMotion, lookRef, isActive: () => activeRef.current });
        sceneRef.current = scene;
        setHeadHost(scene.getHeadHost());
        return () => { setHeadHost(null); scene.dispose(); sceneRef.current = null; };
    }, [reducedMotion]);

    // controlled props (no remount)
    useEffect(() => { if (accent) sceneRef.current?.setAccent(accent); }, [accent, reducedMotion]);
    useEffect(() => { sceneRef.current?.setOverlay(overlay); }, [overlay, reducedMotion]);

    return (
        <div className={`moon-host ${className}`.trim()} style={style} ref={hostRef}>
            {headHost && createPortal(
                <EmberHead state={emberState ?? (scanning ? 'thinking' : 'idle')} amplitude={emberAmplitude} alert={emberAlert} accent={accent || CONFIG.accent} size="100%" lookRef={lookRef} />,
                headHost
            )}
        </div>
    );
});

export default MoonHabitatScene;