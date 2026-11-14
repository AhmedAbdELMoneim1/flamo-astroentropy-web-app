import React, { forwardRef, useEffect, useImperativeHandle, useRef, useState } from 'react';
import * as THREE from 'three';
import { createPortal } from 'react-dom';
import EmberHead from '../siAssistant/EmberHead.jsx'; // adjust the path if EmberHead.jsx lives elsewhere
import './SpaceCraftScene.css';
import { CATEGORIES, CATEGORY_ORDER, HOME_ACCENT } from '../coreSolution/categories';

/* =====================================================================
   SpaceCraftScene  –  "Flame in Freefall · Cabin"
   Ported from FinalScene1.html (three r128 CDN) to an ES-module React
   component that uses the npm `three` package (same as ControlCenter.jsx).

   Usage
     <div style={{ width: '100vw', height: '100vh' }}>
       <SpaceCraftScene ref={cabinRef} category="smoke" onScanDone={(id) => ...} />
     </div>

   Props
     category        string | null   one of the keys in CONFIG.categoryMap, null = home
     quality         'low' | 'high'  default: auto (low on small screens / touch)
     reducedMotion   boolean         default: prefers-reduced-motion
     onScanDone      (id) => void
     showDevPanel    boolean         shows the Home / category / Dim / Quality buttons
     className, style               applied to the host wrapper

   Imperative handle (ref)
     setCategory(id), goHome(), registerScan(id, factory), setAccent(hex),
     setDim(0..1), fadeOut(ms), getContext()
   ===================================================================== */

/* ================================================================= CONFIG */
export const CONFIG = {
    T: { fadeIn: 0.25, fly: 0.5, scanMax: 5, accent: 0.4, test: 4 },
    accents: { home: HOME_ACCENT, ...Object.fromEntries(CATEGORY_ORDER.map((id) => [id, CATEGORIES[id].accent])) },
    names: { home: 'HOME', ...Object.fromEntries(CATEGORY_ORDER.map((id) => [id, CATEGORIES[id].name.toUpperCase()])) },
    categoryMap: {
        prevention: ['panelCover', 'plugConnector', 'foamBay', 'regulator', 'bag', 'glove', 'shirt', 'foamTable'],
        flammability: ['bag', 'checklist', 'foamTable', 'supplyVent', 'ribbon', 'checklist'],
        detection: ['smoulderCloth', 'detector1', 'detector2', 'detector3', 'returnGrille'],
        suppression: ['fireSwatch', 'extinguisher', 'suppressionPort', 'maskCase'],
    },
    camera: { pos: [0, 0.2, 1.9], look: [0, 0, -2], fov: 55, maxFov: 75, fill: 0.92, yaw: 2, pitch: 1.5 },
    fitKeys: ['bench', 'panelCover', 'supplyVent', 'returnGrille', 'gaugePanel', 'detector1', 'detector3', 'extinguisher', 'maskCase', 'lockerL', 'lockerR'],
    coreKeys: ['bench', 'panelCover'],
    ITEM_SCALE: 1.25,
    openOnScan: ['ignition'],
    flamo: { ndc: [-0.5, -0.5], dist: 1.6, width: 0.35, front: 0.55, above: 0.15, headScale: 1.4 }, // headScale: size of the EmberHead box relative to `width`
    // three r155+ removed "legacy lights": light intensities are now physical, so the
    // original r128 values look ~PI times too dark. This factor compensates. Tune to taste.
    lightScale: parseInt(THREE.REVISION, 10) >= 155 ? Math.PI : 1,
    items: [ // (the demo `score` fields are not shown anywhere: no number on a label that is not from flameo) at = host (bench rack | L | R stowage locker); u/v/y = local position on its shelf
        { id: 'bag', at: 'L', u: -0.27, v: 0.2, y: -0.41, mat: 'NYLON', score: 42 },
        { id: 'shirt', at: 'L', u: -0.27, v: 0.2, y: 0.04, mat: 'COTTON', score: 78 },
        { id: 'foamTable', at: 'R', u: -0.27, v: 0.2, y: 0.04, mat: 'PU FOAM', score: 85 },
        { id: 'cableCoil', at: 'bench', u: -0.62, v: 0.02, y: 0.02, mat: 'PTFE', score: 25 },
        { id: 'pouches', at: 'L', u: 0.27, v: 0.2, y: 0.04, mat: 'FOIL LAMINATE', score: 48 },
        { id: 'plate', at: 'R', u: 0.27, v: 0.2, y: -0.41, mat: 'ALUMINUM', score: 8 },
        { id: 'glove', at: 'R', u: -0.27, v: 0.2, y: -0.41, mat: 'ARAMID', score: 30 },
        { id: 'blueBag', at: 'L', u: 0.27, v: 0.2, y: -0.41, mat: 'POLYETHYLENE', score: 55 },
        { id: 'checklist', at: 'bench', u: -0.12, v: 0.0, y: 0.02, mat: 'PAPER', score: 91 },
        { id: 'tablet', at: 'bench', u: 0.45, v: 0.12, y: 0.02, mat: 'ALUMINUM', score: 8 },
        { id: 'tool', at: 'bench', u: 0.38, v: -0.2, y: 0.02, mat: 'STEEL', score: 2 },
        { id: 'smoulderCloth', at: 'R', u: 0.27, v: 0.2, y: 0.04, mat: 'COTTON (CHARRED)', score: null }
    ],
    gauges: { O2: 21.0, PRESSURE: 101, CO2: 0.4 }
};

const SRGB = THREE.SRGBColorSpace || 'srgb';

/* ============================================================ FLAMO_MODULE
   Placeholder with the final API. Replace with the real Flamo module later,
   or pass your own via the `createFlamo` option of mountSpaceCraftScene.
   createFlamo(THREE, { camera, accent, width }) */
export function createFlamo(THREE_, o) {
    // Invisible 3D anchor. All the flying / looking logic stays here, but the visible robot
    // is the <EmberHead/> DOM canvas, which the scene pins to this anchor's screen position.
    o = o || {};
    const V = THREE_.Vector3, obj = new THREE_.Group(), cam = o.camera;
    let state = 'idle', amp = 0, tw = null, follow = false, look = null, pop = 1, popOn = false;
    const home = new V();
    return {
        object3D: obj,
        setState(n) { state = n; }, getState() { return state; }, setAmplitude(v) { amp = v; }, getAmplitude() { return amp; },
        setAccent() { },
        get pop() { return pop; },
        setHome(v, f) { home.copy(v); if (f !== undefined) follow = !!f; },
        flyTo(v, ms) {
            if (tw) { const r = tw.res; tw = null; r(); }
            follow = false;
            return new Promise((res) => {
                if (!ms) { obj.position.copy(v); pop = 0; popOn = true; res(); return; }
                tw = { a: obj.position.clone(), b: v.clone(), t: 0, ms, res };
            });
        },
        lookAt(v) { look = v ? v.clone() : null; },
        update(dt) {
            if (tw) {
                tw.t += dt * 1000; const k = Math.min(1, tw.t / tw.ms), e = k < 0.5 ? 2 * k * k : 1 - Math.pow(-2 * k + 2, 2) / 2;
                obj.position.lerpVectors(tw.a, tw.b, e);
                if (k >= 1) { const r = tw.res; tw = null; r(); }
            } else if (follow) obj.position.lerp(home, 1 - Math.exp(-10 * dt));
            if (popOn) { pop += dt / 0.15; if (pop >= 1) { pop = 1; popOn = false; } }
            if (look) obj.lookAt(look); else if (cam) obj.lookAt(cam.position);
        },
        dispose() { }
    };
}
/* ======================================================== END FLAMO_MODULE */

/* ============================================================ mountSpaceCraftScene
   Imperative three.js scene. Appends its own root <div class="cs"> to `container`
   and returns a controller. Always call .dispose() on unmount. */
export function mountSpaceCraftScene(container, options) {
    const o = options || {}, TH = THREE, V3 = TH.Vector3, CF = CONFIG, LS = CF.lightScale;
    const makeFlamo = o.createFlamo || createFlamo;
    const reduced = o.reducedMotion !== undefined ? !!o.reducedMotion : window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const touch = 'ontouchstart' in window || navigator.maxTouchPoints > 0;
    const quality = o.quality || ((window.innerWidth < 900 || touch) ? 'low' : 'high'), low = quality === 'low';
    let dead = false, ready = false, raf = 0, last = 0, t = 0, seq = 0, cur = null, mode = 'home', queued = null, chip = null, flamo = null;
    const anchors = new Map(), areas = {}, texs = [], gc = {}, sway = [], anims = [], plugins = {};
    const clamp = (x, a = 0, b = 1) => Math.min(b, Math.max(a, x));
    const pretty = (n) => String(n).replace(/([A-Z])/g, ' $1').toUpperCase();

    /* ---------- DOM + renderer ---------- */
    const root = document.createElement('div'); root.className = 'cs';
    root.style.setProperty('--sp', reduced ? 2 : 1);
    root.innerHTML = '<div class="ov"><svg class="sv"></svg></div><div class="lm"></div><div class="ln"><div class="lc"></div><div class="lh">SCAN LENS</div><div class="ll"></div><i></i><i></i><i></i><i></i></div><div class="blk"></div><div class="ld"><i></i></div>';
    container.appendChild(root);
    const renderer = new TH.WebGLRenderer({ antialias: !low, powerPreference: 'high-performance' });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, low ? 1.5 : 2));
    renderer.toneMapping = TH.ACESFilmicToneMapping; renderer.toneMappingExposure = 1.15; renderer.outputColorSpace = SRGB;
    root.insertBefore(renderer.domElement, root.firstChild);
    // DOM host for the <EmberHead/> robot (React portals into it); sits under the overlay so tags/brackets stay on top
    const headEl = document.createElement('div'); headEl.className = 'cs-ember'; root.insertBefore(headEl, root.querySelector('.ov'));
    const scene = new TH.Scene(); scene.background = new TH.Color(0x020306);
    if (!low) scene.fog = new TH.FogExp2(0x0a1018, 0.03);
    const camera = new TH.PerspectiveCamera(CF.camera.fov, 1, 0.05, 60);
    camera.layers.enable(1);
    const ldBar = root.querySelector('.ld i'), blk = root.querySelector('.blk');

    /* ---------- accent ---------- */
    const accent = new TH.Color(CF.accents.home), aFrom = new TH.Color(), aTo = new TH.Color(); let aT = 1;
    const hex = () => '#' + accent.getHexString();
    function applyAccent() { root.style.setProperty('--ac', hex()); flamo && flamo.setAccent(hex()); }
    function setAccent(h) { aFrom.copy(accent); aTo.set(h); aT = 0; }

    /* ---------- helpers ---------- */
    const rnd = ((s) => () => (s = (s * 16807) % 2147483647) / 2147483647)(11);
    function tex(w, h, fn, lin) {
        const c = document.createElement('canvas'); c.width = w; c.height = h; fn(c.getContext('2d'), w, h);
        const x = new TH.CanvasTexture(c); if (!lin) x.colorSpace = SRGB; x.anisotropy = 4; texs.push(x); return x;
    }
    const rep = (x, a, b) => { x.wrapS = x.wrapT = TH.RepeatWrapping; x.repeat.set(a, b); return x; };
    const M = (c, r = 0.6, m = 0.3, x) => new TH.MeshStandardMaterial(Object.assign({ color: c, roughness: r, metalness: m }, x));
    const BM = (c, x) => new TH.MeshBasicMaterial(Object.assign({ color: c }, x));
    const geo = (k, f) => gc[k] || (gc[k] = f());
    const bg = (w, h, d) => geo('b' + w + h + d, () => new TH.BoxGeometry(w, h, d));
    const pg = (w, h) => geo('p' + w + h, () => new TH.PlaneGeometry(w, h));
    const put = (m, x, y, z, p) => { m.position.set(x || 0, y || 0, z || 0); p && p.add(m); return m; };
    const bx = (w, h, d, mat, x, y, z, p) => put(new TH.Mesh(bg(w, h, d), mat), x, y, z, p);
    const pl = (w, h, mat, x, y, z, p) => put(new TH.Mesh(pg(w, h), mat), x, y, z, p);
    const cy = (r, h, mat, x, y, z, p, ax, seg) => { const g = geo('c' + r + h + (seg || 24), () => new TH.CylinderGeometry(r, r, h, seg || 24)); const m = put(new TH.Mesh(g, mat), x, y, z, p); if (ax === 'z') m.rotation.x = Math.PI / 2; return m; };
    const sp = (r, mat, x, y, z, p) => put(new TH.Mesh(geo('s' + r, () => new TH.SphereGeometry(r, 16, 12)), mat), x, y, z, p);
    const grp = (name, x, y, z, p) => { const g = new TH.Group(); g.name = name; g.position.set(x || 0, y || 0, z || 0); (p || scene).add(g); return g; };
    const reg = (name, obj) => { anchors.set(name, obj); obj.name = obj.name || name; return obj; };
    const lab = (w, h, bgc, fg, txt, fs) => tex(w, h, (g) => {
        g.fillStyle = bgc; g.fillRect(0, 0, w, h); g.fillStyle = fg; g.font = '700 ' + (fs || 20) + 'px "Share Tech Mono",monospace'; g.textAlign = 'center'; g.textBaseline = 'middle'; g.fillText(txt, w / 2, h / 2);
    });
    const speck = (c, n, a) => tex(128, 128, (g) => {
        g.fillStyle = c; g.fillRect(0, 0, 128, 128);
        for (let i = 0; i < n; i++) { const v = rnd() * 255 | 0; g.fillStyle = 'rgba(' + v + ',' + v + ',' + v + ',' + a + ')'; g.fillRect(rnd() * 128, rnd() * 128, 2, 2); }
    });
    const tube = (pts, r, mat, seg, p) => { const m = new TH.Mesh(new TH.TubeGeometry(new TH.CatmullRomCurve3(pts.map((q) => new V3(q[0], q[1], q[2]))), seg || 16, r, 6), mat); (p || scene).add(m); return m; };

    const bolts = (p, w, h, z, bm) => { bm = bm || M(0xb5bdc9, 0.35, 0.85);[[-1, -1], [1, -1], [-1, 1], [1, 1]].forEach((q) => cy(0.012, 0.012, bm, q[0] * w / 2, q[1] * h / 2, z, p, 'z', 8)); };
    let _face; const faceTex = () => _face || (_face = tex(256, 512, (g, w, h) => {
        g.fillStyle = '#242a33'; g.fillRect(0, 0, w, h); let y = 6;
        while (y < h - 40) {
            const u = 44 + rnd() * 70 | 0, c = 60 + rnd() * 40 | 0;
            g.fillStyle = 'rgb(' + c + ',' + (c + 6) + ',' + (c + 16) + ')'; g.fillRect(6, y, w - 12, u - 5); g.strokeStyle = '#080b10'; g.lineWidth = 2; g.strokeRect(6, y, w - 12, u - 5);
            g.fillStyle = '#b5bdc9'; g.fillRect(12, y + u / 2 - 7, 6, 14); g.fillRect(w - 18, y + u / 2 - 7, 6, 14);
            if (rnd() < 0.5) { for (let i = 0; i < 6; i++) { g.fillStyle = '#0b0e13'; g.fillRect(34, y + 8 + i * 5, 110, 2); } }
            else for (let i = 0; i < 5; i++) { g.fillStyle = rnd() < 0.25 ? '#ffa020' : rnd() < 0.5 ? '#4fd6c9' : '#2a3342'; g.fillRect(34 + i * 18, y + u / 2 - 3, 8, 6); }
            y += u;
        }
    }));

    /* ---------- lights (<= 8, <= 4 in low) ---------- */
    scene.add(new TH.HemisphereLight(0xb8c8e8, 0x202530, 0.95 * LS));
    const L = (c, i, d, x, y, z) => { const l = new TH.PointLight(c, i * LS, d, 1.6); l.position.set(x, y, z); scene.add(l); return l; };
    L(0xffc98a, 1.5, 6, 0, -0.4, -2.2);                 // warm lamp above bench
    L(0xdfeaff, 1.1, 9, 0, 1.2, -0.2);                  // cool centre
    const amberL = L(0xff9a2a, 0.8, 5, -1.2, 0.2, -2.6);
    let bayL = null, bayMat = null;
    if (!low) { L(0xaac8ff, 0.7, 5, 0, -1.1, -1.4); bayL = L(0xbfd8ff, 0, 2.2, -2.9, 0.15, -1.6); }

    /* ================================================== overlay manager */
    function buildOverlayManager() {
        const ov = root.querySelector('.ov'), svg = ov.querySelector('svg'), items = new Set(), CH = '#%&@$01<>/\\=+*';
        let W = 1, H = 1; const bb = new TH.Box3(), wp = new V3(), cp = new V3();
        const mkEl = (cls, html) => { const d = document.createElement('div'); d.className = cls; if (html) d.innerHTML = html; ov.appendChild(d); return d; };
        const mkPn = () => { const d = mkEl('pn', '<div class="b"><div class="i"></div></div>'); d.q = d.querySelector('.i'); d.bb = d.querySelector('.b'); return d; };
        function rectOf(tg, cm, w, h) {
            cm = cm || camera; w = w || W; h = h || H;
            bb.setFromObject(tg); if (bb.isEmpty()) return null;
            let x0 = 1e9, y0 = 1e9, x1 = -1e9, y1 = -1e9;
            for (let i = 0; i < 8; i++) {
                wp.set(i & 1 ? bb.max.x : bb.min.x, i & 2 ? bb.max.y : bb.min.y, i & 4 ? bb.max.z : bb.min.z);
                cp.copy(wp).applyMatrix4(cm.matrixWorldInverse); if (cp.z > -0.1) return null;
                wp.project(cm); const x = (wp.x * 0.5 + 0.5) * w, y = (-wp.y * 0.5 + 0.5) * h;
                x0 = Math.min(x0, x); x1 = Math.max(x1, x); y0 = Math.min(y0, y); y1 = Math.max(y1, y);
            }
            return { l: x0, t: y0, r: x1, b: y1 };
        }
        function show(it, now) {
            if (it.vis) return; it.vis = true; it.el.style.visibility = 'visible'; if (it.line) it.line.style.visibility = 'visible';
            if (!it.shown) {
                it.shown = true; it.born = now;
                if (it.k === 'b') { it.el.classList.add('s'); } else { it.el.bb.classList.add('g'); setTimeout(() => it.el.bb && it.el.bb.classList.remove('g'), 150); }
            }
        }
        function hide(it) { if (!it.vis) return; it.vis = false; it.el.style.visibility = 'hidden'; if (it.line) it.line.style.visibility = 'hidden'; }
        function remover(it) { return () => { items.delete(it); it.el.remove(); it.line && it.line.remove(); it.lel && it.lel.remove(); }; }
        function decode(it, now) {
            if (it.text == null) return;
            const p = clamp((now - it.born) / (250 * (reduced ? 2 : 1))), n = it.text.length, k = Math.floor(p * n);
            let s = ''; for (let i = 0; i < n; i++) s += (i < k || it.text[i] === ' ' || it.text[i] === '[' || it.text[i] === ']') ? it.text[i] : CH[rnd() * CH.length | 0];
            if (it.shownText !== s) { it.shownText = s; it.el.q.textContent = s; }
        }
        const api = {
            resize(w, h) { W = w; H = h; },
            bracket(tg, op) {
                op = op || {}; const it = { k: 'b', t: tg, el: mkEl('br'), pad: op.padding == null ? 6 : op.padding };
                if (op.color) it.el.style.setProperty('--c', op.color);
                items.add(it); it.remove = remover(it); return { remove: it.remove, update() { }, el: it.el };
            },
            tag(tg, text, op) {
                op = op || {}; const it = { k: 'g', t: tg, el: mkPn(), text: text, side: op.side || 'auto' };
                if (op.color) it.el.style.setProperty('--c', op.color);
                it.line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
                it.line.setAttribute('stroke', op.color || hex()); it.line.setAttribute('stroke-width', '1.5'); it.line.style.visibility = 'hidden'; it.line.dataset.auto = op.color ? '' : '1'; svg.appendChild(it.line);
                it.shownText = null; items.add(it); it.remove = remover(it);
                return { remove: it.remove, update() { }, set(tx) { it.text = tx; it.shownText = null; } };
            },
            panel(html, op) {
                op = op || {}; const it = { k: 'p', el: mkPn(), x: op.x || 0, y: op.y || 0, anchor: op.anchor || 'tl', persist: !!op.persist, born: 0 };
                if (op.color) it.el.style.setProperty('--c', op.color);
                const setH = (h) => { if (/</.test(h)) { it.text = null; it.el.q.innerHTML = h; } else { it.text = h; it.shownText = null; } }; setH(html);
                items.add(it); it.remove = remover(it); return { remove: it.remove, update() { }, set: setH };
            },
            clear() { Array.from(items).forEach((it) => { if (!it.persist) it.remove(); }); },
            update(now) {
                const tags = [], lensR = lens.rect();
                items.forEach((it) => {
                    if (it.k === 'p') {
                        const w = it.el.offsetWidth, h = it.el.offsetHeight, a = it.anchor;
                        it.el.style.left = (a[1] === 'r' ? W - it.x - w : it.x) + 'px'; it.el.style.top = (a[0] === 'b' ? H - it.y - h : it.y) + 'px'; show(it, now); decode(it, now); return;
                    }
                    const r = rectOf(it.t);
                    if (!r || r.r < 0 || r.l > W || r.b < 0 || r.t > H) { hide(it); return; }
                    it.r = r;
                    if (it.k === 'b') {
                        const e = it.el.style; e.left = r.l - it.pad + 'px'; e.top = r.t - it.pad + 'px'; e.width = r.r - r.l + it.pad * 2 + 'px'; e.height = r.b - r.t + it.pad * 2 + 'px'; show(it, now);
                    } else { it.w = it.el.offsetWidth; it.h = it.el.offsetHeight; decode(it, now); tags.push(it); }
                });
                const placed = lensR ? [lensR] : [];
                tags.forEach((it) => {
                    const r = it.r, w = it.w, h = it.h, cx = (r.l + r.r) / 2, cyy = (r.t + r.b) / 2; let s = it.side, x, y;
                    if (s === 'auto') s = r.t - h - 28 > 8 ? 'above' : 'below';
                    if (s === 'above') { x = cx - w / 2; y = r.t - h - 28; } else if (s === 'below') { x = cx - w / 2; y = r.b + 28; }
                    else if (s === 'left') { x = r.l - w - 28; y = cyy - h / 2; } else { x = r.r + 28; y = cyy - h / 2; }
                    x = clamp(x, 8, Math.max(8, W - w - 8));
                    for (let pass = 0; pass < 4; pass++) placed.forEach((p) => {
                        if (x < p.r + 6 && x + w > p.l - 6 && y < p.b + 6 && y + h > p.t - 6) y = s === 'above' ? p.t - h - 6 : p.b + 6;
                    });
                    y = clamp(y, 8, Math.max(8, H - h - 8));
                    placed.push({ l: x, t: y, r: x + w, b: y + h });
                    it.el.style.left = Math.round(x) + 'px'; it.el.style.top = Math.round(y) + 'px';
                    const px = clamp(cx, x, x + w), py = clamp(cyy, y, y + h), qx = clamp(x + w / 2, r.l, r.r), qy = clamp(y + h / 2, r.t, r.b);
                    it.line.setAttribute('x1', px); it.line.setAttribute('y1', py); it.line.setAttribute('x2', qx); it.line.setAttribute('y2', qy);
                    if (it.line.dataset.auto) it.line.setAttribute('stroke', hex());
                    show(it, now);
                });
            },
            lensUpdate(cam, w, h, host, on) {
                items.forEach((it) => {
                    if (it.k === 'p') return;
                    if (!on) { it.lel && (it.lel.style.visibility = 'hidden'); return; }
                    if (!it.lel) {
                        const e = document.createElement('div');
                        if (it.k === 'b') { e.className = 'br s'; }
                        else { e.className = 'pn'; e.innerHTML = '<div class="b g"><div class="i"></div></div>'; e.q = e.querySelector('.i'); }
                        const col = it.el.style.getPropertyValue('--c'); if (col) e.style.setProperty('--c', col);
                        host.appendChild(e); it.lel = e;
                    }
                    const e = it.lel, r = rectOf(it.t, cam, w, h);
                    if (!r || r.r < 0 || r.l > w || r.b < 0 || r.t > h) { e.style.visibility = 'hidden'; return; }
                    e.style.visibility = 'visible';
                    if (it.k === 'b') {
                        const p = 3;
                        e.style.left = r.l - p + 'px'; e.style.top = r.t - p + 'px';
                        e.style.width = r.r - r.l + p * 2 + 'px'; e.style.height = r.b - r.t + p * 2 + 'px';
                    } else {
                        const tx = it.shownText != null ? it.shownText : (it.text || '');
                        if (e.q.textContent !== tx) e.q.textContent = tx;
                        const bw = e.offsetWidth, bh = e.offsetHeight, cx = (r.l + r.r) / 2;
                        const x = clamp(cx - bw / 2, 4, Math.max(4, w - bw - 4));
                        let y = r.t - bh - 6 > 22 ? r.t - bh - 6 : r.b + 6;
                        y = clamp(y, 20, Math.max(20, h - bh - 20));
                        e.style.left = Math.round(x) + 'px'; e.style.top = Math.round(y) + 'px';
                    }
                });
            },
            dispose() { Array.from(items).forEach((it) => it.remove()); }
        };
        return api;
    }

    /* ================================================== lens */
    function buildLens() {
        const el = root.querySelector('.ln'), mk = root.querySelector('.lm'), lb = el.querySelector('.ll');
        const lc = new TH.PerspectiveCamera(30, 260 / 160, 0.02, 40), bb = new TH.Box3(), c = new V3();
        let tg = null, want = 0, a = 0, op = {}, ext = null;
        const getExt = () => { const t = o.lensTarget && o.lensTarget(); return t && t.canvas && t.canvas.isConnected ? t : null; };
        function aim(aspect) {
            bb.setFromObject(tg); bb.getCenter(c);
            const sz = bb.getSize(new V3()), fo = flamo && flamo.object3D;
            lc.position.copy(fo ? fo.position : camera.position);   // camera sits where the robot is
            const dist = Math.max(lc.position.distanceTo(c), 0.05);
            const fov = op.fov || clamp(2 * Math.atan(Math.max(sz.x, sz.y) * 0.8 / dist) * 180 / Math.PI, 25, 80);
            lc.aspect = aspect; lc.fov = fov; lc.lookAt(c); lc.updateProjectionMatrix(); lc.updateMatrixWorld(true);
            return fo;
        }
        return {
            show(n, opts) { if (low || reduced) return; tg = resolve(n); if (!tg) return; op = opts || {}; lb.textContent = op.label || pretty(tg.name || ''); want = 1; },
            hide() { want = 0; },
            rect() { if (ext || a <= 0.01) return null; const W = root.clientWidth; return { l: W - 280, t: 20, r: W - 20, b: 180 }; },

            /* external target (dashboard voice panel). Runs BEFORE the main render. */
            pre(dt) {
                if (low || reduced) return;
                ext = getExt(); if (!ext) return;
                el.style.opacity = 0; mk.style.opacity = 0;                 // hide the top-right lens
                a = clamp(a + (want ? 1 : -1) * dt / 0.2);
                const cv = ext.canvas, cw = cv.clientWidth, ch = cv.clientHeight;
                cv.style.opacity = a;
                if (ext.label) { ext.label.style.opacity = a; if (tg) ext.label.textContent = op.label || pretty(tg.name || ''); }
                if (!tg || a <= 0.01 || !cw || !ch) { overlay.lensUpdate(lc, cw || 1, ch || 1, ext.host, false); return; }
                const W = root.clientWidth, H = root.clientHeight, pr = renderer.getPixelRatio();
                const k = Math.min(1, W / cw, H / ch), lw = Math.max(1, Math.round(cw * k)), lh = Math.max(1, Math.round(ch * k));
                const bw = Math.round(lw * pr), bh = Math.round(lh * pr);
                if (cv.width !== bw || cv.height !== bh) { cv.width = bw; cv.height = bh; }
                const fo = aim(cw / ch);
                if (fo) fo.visible = false;
                renderer.setViewport(0, 0, lw, lh); renderer.setScissor(0, 0, lw, lh); renderer.setScissorTest(true);
                renderer.render(scene, lc);
                renderer.setScissorTest(false); renderer.setViewport(0, 0, W, H);
                if (fo) fo.visible = true;
                // copy the bottom-left region into the dashboard canvas; the main render then overwrites it
                cv.getContext('2d').drawImage(renderer.domElement, 0, renderer.domElement.height - bh, bw, bh, 0, 0, bw, bh);
                overlay.lensUpdate(lc, cw, ch, ext.host, true);             // brackets + tags inside the lens
            },

            /* fallback: on-screen lens in the top-right corner (runs AFTER the main render) */
            render(dt) {
                if (low || reduced || ext) return;
                const host = el.querySelector('.lc');
                a = clamp(a + (want ? 1 : -1) * dt / 0.2); el.style.opacity = a; mk.style.opacity = a > 0 ? 1 - a : 0;
                if (!tg || a <= 0.01) { overlay.lensUpdate(lc, 260, 160, host, false); return; }
                const fo = aim(260 / 160), W = root.clientWidth, H = root.clientHeight, x = W - 280, y = H - 180;
                if (fo) fo.visible = false;
                renderer.setViewport(x, y, 260, 160); renderer.setScissor(x, y, 260, 160); renderer.setScissorTest(true);
                renderer.render(scene, lc);
                renderer.setScissorTest(false); renderer.setViewport(0, 0, W, H);
                if (fo) fo.visible = true;
                overlay.lensUpdate(lc, 260, 160, host, true);
            },
            dispose() { el.style.opacity = 0; mk.style.opacity = 0; }
        };
    }
    const overlay = buildOverlayManager(), lens = buildLens();
    function resolve(n) { return typeof n === 'string' ? anchors.get(n) : n; }
    const tmpB = new TH.Box3();
    const centerOf = (n) => tmpB.setFromObject(resolve(n)).getCenter(new V3());
    const hoverPos = (n) => { const c = centerOf(n); return c.add(camera.position.clone().sub(c).normalize().multiplyScalar(CF.flamo.front)).add(new V3(0, CF.flamo.above, 0)); };
    const homePos = () => { camera.updateMatrixWorld(); return new V3(CF.flamo.ndc[0], CF.flamo.ndc[1], 0.5).unproject(camera).sub(camera.position).normalize().multiplyScalar(CF.flamo.dist).add(camera.position); };

    /* ================================================== shell */
    function buildShell() {
        const panel = tex(1024, 1024, (g, w, h) => {
            g.fillStyle = '#868e9a'; g.fillRect(0, 0, w, h);
            for (let i = 0; i < 700; i++) { const v = 120 + rnd() * 40 | 0; g.fillStyle = 'rgba(' + v + ',' + v + ',' + (v + 6) + ',.12)'; g.fillRect(rnd() * w, rnd() * h, 6, 6); }
            [0, 512].forEach((p) => { g.fillStyle = 'rgba(20,26,36,.35)'; g.fillRect(p, 0, 3, h); g.fillRect(0, p, w, 3); g.fillStyle = 'rgba(255,255,255,.08)'; g.fillRect(p + 3, 0, 2, h); g.fillRect(0, p + 3, w, 2); });
        }, 0);
        rep(panel, 1, 1);
        const rough = tex(256, 256, (g) => { for (let i = 0; i < 5000; i++) { const v = 90 + rnd() * 165 | 0; g.fillStyle = 'rgb(' + v + ',' + v + ',' + v + ')'; g.fillRect(rnd() * 256, rnd() * 256, 6, 6); } }, 1); rep(rough, 1, 1);
        const wm = M(0xffffff, 1, 0.4, { map: panel, roughnessMap: rough, side: TH.DoubleSide }), wm2 = wm.clone(); wm2.color.set(0x9097a2);
        // box room: back, left (with bay opening), right, floor, ceiling
        const wall = (w, h, mat, x, y, z, rx, ry, hole) => {
            const sh = new TH.Shape(); sh.moveTo(-w / 2, -h / 2); sh.lineTo(w / 2, -h / 2); sh.lineTo(w / 2, h / 2); sh.lineTo(-w / 2, h / 2); sh.closePath();
            if (hole) { const p = new TH.Path(); p.moveTo(hole[0], hole[1]); p.lineTo(hole[2], hole[1]); p.lineTo(hole[2], hole[3]); p.lineTo(hole[0], hole[3]); p.closePath(); sh.holes.push(p); }
            const g = new TH.ShapeGeometry(sh), u = g.attributes.uv; for (let i = 0; i < u.count; i++) u.setXY(i, u.getX(i) / 1.5, u.getY(i) / 1.5);
            const m = new TH.Mesh(g, mat); m.position.set(x, y, z); m.rotation.set(rx, ry, 0); scene.add(m);
        };
        wall(5.6, 3.6, wm2, 0, 0, -3, 0, 0);
        wall(5.4, 3.6, wm, -2.8, 0, -0.3, 0, Math.PI / 2, [0.7, -0.3, 1.9, 0.6]);
        wall(5.4, 3.6, wm, 2.8, 0, -0.3, 0, -Math.PI / 2);
        wall(5.6, 5.4, wm2, 0, -1.8, -0.3, -Math.PI / 2, 0);
        wall(5.6, 5.4, wm2, 0, 1.8, -0.3, Math.PI / 2, 0);
        // cool white strip lights along the edges + ring ribs
        const strip = BM(new TH.Color(1.5, 1.8, 2.3));
        [[-1.2, 1.1], [1.5, -0.9], [-0.3, -2.3], [1.4, 1.3]].forEach((p) => { bx(0.5, 0.04, 0.24, M(0x1a1e25, 0.6, 0.5), p[0], 1.78, p[1], scene); bx(0.42, 0.01, 0.17, strip, p[0], 1.755, p[1], scene); });
        [1.6, -0.3, -2.4].forEach((z) => { const rm = M(0x353d4a, 0.5, 0.5); bx(5.6, 0.1, 0.14, rm, 0, 1.75, z, scene); bx(5.6, 0.1, 0.14, rm, 0, -1.75, z, scene);[-1, 1].forEach((sd) => bx(0.1, 3.6, 0.14, rm, sd * 2.75, 0, z, scene)); });
        // handrails, foot loops, conduits, cable runs
        const steel = M(0x9aa3af, 0.35, 0.8), blk_ = M(0x15181d, 0.6, 0.2), org = M(0x3d4450, 0.7, 0.2);
        [-1, 1].forEach((s) => {
            cy(0.02, 5, steel, s * 2.66, -1.0, -0.4, scene, 'z');
            [1.4, 0.2, -1.0, -2.2].forEach((z) => bx(0.14, 0.03, 0.03, steel, s * 2.73, -1.0, z, scene));
            tube([[s * 2.76, 0.9, 2.3], [s * 2.76, 0.88, 0], [s * 2.76, 0.9, -2.9]], 0.03, blk_, 20); tube([[s * 2.76, 0.78, 2.3], [s * 2.76, 0.8, -2.9]], 0.02, org, 8);
            cy(0.04, 5.2, M(0x3a424f, 0.5, 0.6), s * 2.0, -1.72, -0.3, scene, 'z');[1.6, 0.2, -1.2, -2.4].forEach((z) => bx(0.12, 0.05, 0.06, steel, s * 2.0, -1.77, z, scene));
            const clamp_ = M(0x2a303a, 0.5, 0.6), strap = M(0xe8e8e8, 0.8, 0);
            for (let z = 2.0; z > -2.8; z -= 0.55) {
                bx(0.05, 0.1, 0.06, clamp_, s * 2.76, 0.84, z, scene);          // conduit clamp
                bx(0.02, 0.07, 0.04, strap, s * 2.74, 0.9, z + 0.2, scene);     // cable strap
                bx(0.05, 0.05, 0.05, clamp_, s * 2.66, -1.0, z, scene);         // handrail bracket
            }
        });
        for (let i = 0; i < 6; i++) { const m = put(new TH.Mesh(geo('ft', () => new TH.TorusGeometry(0.05, 0.01, 6, 16)), steel), (i % 2 ? 1 : -1) * 1.4, -1.76, 1.2 - (i >> 1) * 1.6, scene); m.rotation.x = Math.PI / 2; bx(0.16, 0.02, 0.05, steel, m.position.x, -1.775, m.position.z, scene); }
        [[-1.4, 1.7, blk_], [-1.28, 1.72, org], [-1.16, 1.7, M(0x555b66, 0.6, 0.2)]].forEach((c) => tube([[c[0], c[1], 2.3], [c[0] + 0.03, c[1] - 0.02, 0.5], [c[0] - 0.02, c[1], -1.2], [c[0], c[1], -2.9]], 0.025, c[2], 24));
        [1.4, 0, -1.4, -2.6].forEach((z) => bx(0.4, 0.14, 0.04, steel, -1.28, 1.74, z, scene));
        const faceM = M(0xffffff, 0.7, 0.35, { map: faceTex() }), rkM = M(0x2e3540, 0.6, 0.5);
        [-1, 1].forEach((sd, k) => {
            const z = 0.4, w = 1.0, rh = 1.15, y = 0.4 - k * 0.1;
            bx(0.36, rh, w, rkM, sd * 2.62, y, z, scene);
            const f = pl(w - 0.08, rh - 0.08, faceM, sd * 2.43, y, z, scene); f.rotation.y = -sd * Math.PI / 2;
            [-1, 1].forEach((e) => bx(0.04, rh + 0.06, 0.04, steel, sd * 2.43, y, z + e * w / 2, scene));
            tube([[sd * 2.4, y + rh / 2, z + 0.3], [sd * 2.3, 1.2, z + 0.3], [sd * 2.2, 1.7, z + 0.3]], 0.015, blk_, 10); bx(0.08, 0.06, 0.05, steel, sd * 2.2, 1.72, z + 0.3, scene);
            [1.5, 0.3, -2.1].forEach((cz) => bx(0.06, 0.05, 0.04, steel, sd * 2.75, 0.85, cz, scene));
        });
        // hatch outline in a rear corner (right wall)
        const hatch = pl(1.0, 1.2, BM(0xffffff, { map: tex(256, 300, (g) => { g.fillStyle = '#1c222b'; g.fillRect(0, 0, 256, 300); g.strokeStyle = '#7d8798'; g.lineWidth = 8; g.strokeRect(12, 12, 232, 276); g.lineWidth = 3; g.strokeRect(34, 34, 188, 232); g.beginPath(); g.arc(128, 150, 34, 0, 7); g.stroke(); g.fillStyle = '#ffa020'; g.fillRect(34, 268, 188, 8); g.font = '16px monospace'; g.fillStyle = '#9fb0c8'; g.fillText('HATCH 3 · EVA', 70, 60); }) }), 1.6, -1.79, -0.3, scene);
        hatch.rotation.x = -Math.PI / 2;
        // amber indicator lights (pulse)
        const am = BM(new TH.Color(3, 1.3, 0.1));[[-1.5, 0.3], [1.5, 0.3], [-1.0, 1.55], [1.0, 1.55]].forEach((p, i) => { const s = sp(0.03, am.clone(), p[0], p[1], -2.96, scene); anims.push((tt) => { s.material.opacity = 1; s.scale.setScalar(0.8 + 0.5 * Math.abs(Math.sin(tt * 1.6 * (reduced ? 0.5 : 1) + i))); }); });
        // dust
        const N = 150, dp = new Float32Array(N * 3), base = new Float32Array(N * 3);
        for (let i = 0; i < N; i++) { base[i * 3] = (rnd() - 0.5) * 5; base[i * 3 + 1] = (rnd() - 0.5) * 3.2; base[i * 3 + 2] = -2.8 + rnd() * 5; }
        const dg = new TH.BufferGeometry(); dg.setAttribute('position', new TH.BufferAttribute(dp, 3));
        scene.add(new TH.Points(dg, new TH.PointsMaterial({ color: 0xcfe0ff, size: 0.012, transparent: true, opacity: 0.4, depthWrite: false })));
        anims.push((tt) => { for (let i = 0; i < N; i++) { dp[i * 3] = base[i * 3] + Math.sin(tt * 0.1 + i) * 0.15; dp[i * 3 + 1] = base[i * 3 + 1] + Math.cos(tt * 0.08 + i * 2) * 0.1; dp[i * 3 + 2] = base[i * 3 + 2]; } dg.attributes.position.needsUpdate = true; });
    }

    /* ================================================== workbench */
    function buildWorkbench() {
        const g = grp('bench', 0, -1.0, -2.58); areas.bench = g; reg('bench', g);
        const brushed = tex(256, 128, (c) => { c.fillStyle = '#a9b0ba'; c.fillRect(0, 0, 256, 128); for (let i = 0; i < 400; i++) { const v = 150 + rnd() * 90 | 0; c.fillStyle = 'rgba(' + v + ',' + v + ',' + (v + 6) + ',.35)'; c.fillRect(rnd() * 256, rnd() * 128, 30 + rnd() * 100, 1); } });
        const al = M(0xffffff, 0.4, 0.8, { map: brushed }), strut = M(0x5a626e, 0.4, 0.7), rim = M(0x7d8590, 0.4, 0.8), dk = M(0x2e3540, 0.6, 0.5), vel = M(0xf2f2f2, 1, 0), cord = M(0x15181d, 0.8, 0.1);
        // free-standing equipment rack with a built-in work shelf: faceplate, control panel, handrail, bungee cords
        bx(1.6, 0.8, 0.8, dk, 0, -0.4, 0, g); bx(1.7, 0.86, 0.02, rim, 0, -0.4, -0.41, g); bolts(g, 1.62, 0.78, -0.4); bx(1.7, 0.03, 0.9, rim, 0, -0.785, 0, g);[[-1, -1], [1, -1], [-1, 1], [1, 1]].forEach((q) => cy(0.015, 0.02, strut, q[0] * 0.8, -0.765, q[1] * 0.42, g)); pl(1.52, 0.7, M(0xffffff, 0.7, 0.35, { map: faceTex() }), 0, -0.4, 0.401, g);
        bx(1.6, 0.03, 0.8, al, 0, 0, 0, g);[-0.8, 0.8].forEach((x) => bx(0.04, 0.05, 0.8, rim, x, 0.035, 0, g)); bx(1.6, 0.05, 0.04, rim, 0, 0.035, -0.4, g);
        for (let i = 0; i < 6; i++) bx(0.07, 0.004, 0.6, vel, -0.65 + i * 0.26, 0.017, 0, g);
        const hr = cy(0.015, 1.6, strut, 0, 0.12, 0.43, g); hr.rotation.z = Math.PI / 2;[-0.78, 0.78].forEach((x) => bx(0.03, 0.12, 0.05, strut, x, 0.06, 0.42, g));
        [0.07, 0.2].forEach((y, k) => tube([[-0.78, y, 0.42], [-0.3, y - 0.03 - k * 0.01, 0.43], [0.3, y - 0.03 - k * 0.01, 0.43], [0.78, y, 0.42]], 0.004, cord, 16, g));
        bx(0.9, 0.3, 0.05, dk, 0, 0.17, -0.37, g);
        pl(0.8, 0.22, BM(0xffffff, { map: tex(160, 44, (c) => { c.fillStyle = '#06101a'; c.fillRect(0, 0, 160, 44); for (let i = 0; i < 7; i++) { c.fillStyle = i % 3 ? '#4fd6c9' : '#ffa020'; c.fillRect(8, 6 + i * 5, 20 + rnd() * 90, 3); } c.fillStyle = '#7fb8ff'; c.fillRect(120, 8, 30, 26); }) }), 0, 0.17, -0.34, g);
        bx(0.04, 0.16, 0.04, strut, 0, 0.4, -0.37, g); bx(1.0, 0.03, 0.08, BM(new TH.Color(2.2, 1.7, 1.0)), 0, 0.49, -0.3, g);
        // wall-mounted stowage lockers on the back wall: shelves, velcro, restraint net
        const ST = grp('storage', 0, 0, 0); areas.storage = ST; const lockers = {};
        [['L', -2.0, 'STOW A-07'], ['R', 2.0, 'STOW B-02']].forEach((q) => {
            const lk = grp('locker' + q[0], q[1], -0.85, -2.97, ST); reg('locker' + q[0], lk); lockers[q[0]] = lk;
            bx(1.24, 1.0, 0.01, rim, 0, 0, 0.005, lk); bolts(lk, 1.18, 0.94, 0.012);
            bx(1.1, 0.95, 0.03, dk, 0, 0, 0.025, lk);[-0.55, 0.55].forEach((x) => bx(0.03, 0.95, 0.45, dk, x, 0, 0.235, lk));
            bx(1.16, 0.03, 0.45, dk, 0, 0.475, 0.235, lk); bx(1.1, 0.03, 0.45, dk, 0, -0.475, 0.235, lk);
            pl(0.4, 0.05, BM(0xffffff, { map: lab(128, 32, '#e9ebef', '#15181d', q[2], 16) }), 0, 0.475, 0.461, lk);
            [-0.42, 0.03].forEach((y) => { bx(1.08, 0.02, 0.43, al, 0, y, 0.235, lk);[-0.3, 0, 0.3].forEach((x) => bx(0.12, 0.004, 0.3, vel, x, y + 0.012, 0.2, lk)); });
            [-0.2, 0.25].forEach((y) => tube([[-0.55, y, 0.47], [0, y - 0.03, 0.48], [0.55, y, 0.47]], 0.004, cord, 12, lk));
            [-0.18, 0.18].forEach((x) => tube([[x, -0.47, 0.47], [x + 0.01, 0, 0.48], [x, 0.47, 0.47]], 0.004, cord, 12, lk));
        });
        const hosts = { bench: g, L: lockers.L, R: lockers.R };
        const IS = CF.ITEM_SCALE;
        const IB = {
            bag(p) { bx(0.30, 0.20, 0.15, M(0xe9ecf0, 0.85, 0, { map: speck('#e4e7ec', 500, 0.08) }), 0, 0.1, 0, p);[-0.07, 0.07].forEach((x) => bx(0.025, 0.205, 0.155, M(0xc4cad3, 0.9, 0), x, 0.1, 0, p)); bx(0.06, 0.012, 0.05, M(0x2b2f36, 0.9, 0), 0, 0.206, 0, p); pl(0.1, 0.05, BM(0xffffff, { map: lab(128, 64, '#fff', '#222', 'CARGO 07', 20) }), 0.1, 0.12, 0.076, p); },
            shirt(p) { const t_ = speck('#9fb0c4', 1500, 0.12); bx(0.28, 0.05, 0.22, M(0xffffff, 1, 0, { map: t_, bumpMap: t_, bumpScale: 1.5 }), 0, 0.025, 0, p); bx(0.28, 0.052, 0.07, M(0x8fa0b6, 1, 0), 0, 0.026, 0.07, p); },
            foamTable(p) { const t_ = tex(128, 128, (c) => { c.fillStyle = '#2b2c2f'; c.fillRect(0, 0, 128, 128); for (let i = 0; i < 260; i++) { c.fillStyle = 'rgba(0,0,0,.55)'; c.beginPath(); c.arc(rnd() * 128, rnd() * 128, 1 + rnd() * 3, 0, 7); c.fill(); } }); bx(0.24, 0.10, 0.20, M(0xffffff, 1, 0, { map: t_, bumpMap: t_, bumpScale: 2 }), 0, 0.05, 0, p); },
            cableCoil(p) { const c = tex(8, 64, (q) => { q.fillStyle = '#121214'; q.fillRect(0, 0, 8, 64); q.fillStyle = '#ff8a1a'; q.fillRect(0, 28, 8, 8); }); const m = put(new TH.Mesh(geo('coil', () => new TH.TorusGeometry(0.08, 0.016, 8, 32)), M(0xffffff, 0.6, 0.1, { map: c })), 0, 0.02, 0, p); m.rotation.x = Math.PI / 2; const m2 = m.clone(); m2.position.y = 0.045; m2.scale.setScalar(0.8); p.add(m2); },
            pouches(p) { [[0, 0xd23a3a], [1, 0x3aa85a], [2, 0x3a6ad2]].forEach((a) => { const m = bx(0.14, 0.012, 0.2, M(0xc5ccd6, 0.3, 0.8), (a[0] - 1) * 0.05, 0.008 + a[0] * 0.012, (a[0] - 1) * 0.02, p); m.rotation.y = (a[0] - 1) * 0.3; bx(0.1, 0.002, 0.08, BM(a[1]), 0, 0.007, 0.02, m); }); },
            plate(p) { bx(0.30, 0.015, 0.20, M(0xb4bbc5, 0.3, 0.9), 0, 0.0075, 0, p);[[-1, -1], [1, -1], [-1, 1], [1, 1]].forEach((s) => cy(0.01, 0.006, M(0x555b66, 0.3, 0.9), s[0] * 0.13, 0.018, s[1] * 0.08, p)); },
            glove(p) { const m = M(0x30343b, 0.8, 0.1); bx(0.1, 0.03, 0.11, m, 0, 0.02, 0, p); bx(0.1, 0.006, 0.02, M(0xff7a1a, 0.7, 0), 0, 0.036, 0.04, p); for (let i = 0; i < 5; i++) { const f = cy(0.014, 0.08, m, -0.04 + i * 0.02, 0.02, -0.09, p, 'z'); f.rotation.z = (i - 2) * 0.12; sp(0.014, m, -0.04 + i * 0.02, 0.02, -0.13, p); } },
            blueBag(p) { bx(0.26, 0.18, 0.14, M(0x2a62c9, 0.8, 0), 0, 0.09, 0, p); bx(0.26, 0.004, 0.003, M(0x111111, 1, 0), 0, 0.12, 0.071, p); put(new TH.Mesh(geo('hd', () => new TH.TorusGeometry(0.04, 0.007, 6, 12, Math.PI)), M(0x15181d, 0.8, 0)), 0, 0.18, 0, p); },
            checklist(p, R) {
                const t_ = tex(256, 180, (c) => { c.fillStyle = '#d8d4c4'; c.fillRect(0, 0, 256, 180); c.fillStyle = '#7a1f1f'; c.fillRect(0, 0, 256, 24); c.fillStyle = '#fff'; c.font = '14px monospace'; c.fillText('FIRE RESPONSE CHECKLIST', 10, 17); c.fillStyle = '#333'; for (let i = 0; i < 8; i++) { c.strokeRect(12, 38 + i * 17, 9, 9); c.fillRect(30, 41 + i * 17, 60 + rnd() * 130, 3); } }, 1);
                const mat = new TH.ShaderMaterial({ side: 2, uniforms: { uTex: { value: t_ }, uFront: { value: 0 } }, vertexShader: 'varying vec2 v;void main(){v=uv;gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.);}', fragmentShader: 'uniform sampler2D uTex;uniform float uFront;varying vec2 v;void main(){vec3 c=texture2D(uTex,v).rgb;float s=(v.x+1.-v.y)*.5,f=uFront*1.3-.1;if(s<f-.12)discard;c=mix(c,vec3(.04,.03,.02),1.-smoothstep(f-.08,f,s));c+=vec3(2.,.7,.1)*exp(-abs(s-f)*30.)*step(.001,uFront);gl_FragColor=vec4(c,1.);}' });
                const m = pl(0.5, 0.35, mat, 0, 0.002, 0, p); m.rotation.x = -Math.PI / 2; R.mat = mat;
                [[-.24, -.16], [.24, -.16], [-.24, .16], [.24, .16]].forEach((q) => bx(0.05, 0.002, 0.02, BM(0xe8e4c8, { transparent: true, opacity: 0.6 }), q[0], 0.004, q[1], p));
            },
            tablet(p) { bx(0.24, 0.012, 0.16, M(0x15181d, 0.4, 0.7), 0, 0.006, 0, p); const s = pl(0.22, 0.14, BM(0xffffff, { map: tex(128, 80, (c) => { c.fillStyle = '#0a1a2c'; c.fillRect(0, 0, 128, 80); c.fillStyle = '#4fd6c9'; for (let i = 0; i < 6; i++) c.fillRect(8, 10 + i * 11, 30 + rnd() * 70, 4); }) }), 0, 0.0125, 0, p); s.rotation.x = -Math.PI / 2; },
            tool(p) { const h = cy(0.014, 0.09, M(0xd2561a, 0.6, 0.1), 0.06, 0.014, 0, p); h.rotation.z = Math.PI / 2; const s = cy(0.004, 0.11, M(0xb4bbc5, 0.3, 0.9), -0.04, 0.014, 0, p); s.rotation.z = Math.PI / 2; },
            smoulderCloth(p, R) {
                bx(0.15, 0.01, 0.10, M(0x6b727d, 0.4, 0.8), 0, 0.005, 0, p); bx(0.12, 0.03, 0.08, M(0x14100e, 1, 0, { map: speck('#1a1411', 400, 0.1) }), 0, 0.025, 0, p);
                const em = BM(new TH.Color(3, 0.8, 0.2), { transparent: true, opacity: 0.25 });
                for (let i = 0; i < 9; i++) sp(0.006, em, -0.05 + rnd() * 0.1, 0.042, -0.03 + rnd() * 0.06, p);
                R.embers = em; anims.push((tt) => { em.opacity = R.emberLevel != null ? R.emberLevel : 0.22 + 0.06 * Math.sin(tt * 3); });
            }
        };
        const rig = {};
        CF.items.forEach((it, i) => {
            const it_g = new TH.Group(); it_g.name = it.id; it_g.scale.setScalar(IS); const R = {};
            IB[it.id](it_g, R);
            const fl = it.id === 'checklist' ? 0.012 : (it.id === 'smoulderCloth' || it.id === 'tool' || it.id === 'plate') ? 0 : 0.02 + (i % 3) * 0.006;
            it_g.position.set(it.u, it.y + fl, it.v); hosts[it.at].add(it_g); reg(it.id, it_g);
            if (R.mat) rig.checklist = { setFront(v) { R.mat.uniforms.uFront.value = v; } };
            if (R.embers) it_g.userData.setGlow = (v) => { R.emberLevel = v; };
            if (fl > 0 && it.id !== 'checklist') sway.push({ g: it_g, y: it.y + fl, ph: i * 1.7, a: 0.002 + (i % 4) * 0.0008 });
            if (fl > 0 && it.id !== 'checklist') {
                const tm = M(0x15181d, 0.8, 0.1), host = hosts[it.at], rx = it.u + (it.u > 0 ? -0.14 : 0.14), rz = it.v + 0.1;
                const ring = put(new TH.Mesh(geo('tr', () => new TH.TorusGeometry(0.015, 0.003, 6, 12)), tm), rx, it.y + 0.006, rz, host); ring.rotation.x = Math.PI / 2;
                tube([[rx, it.y + 0.01, rz], [(rx + it.u) / 2, it.y + fl + 0.03, (rz + it.v) / 2], [it.u, it.y + fl + 0.04, it.v]], 0.0025, tm, 6, host);
            }
        });
        return rig;
    }

    /* ================================================== electrical panel */
    function buildElectricalPanel() {
        const g = grp('electrical', -2.8, 0.15, -1.6); areas.electrical = g; g.rotation.y = Math.PI / 2; const rig = {};
        const steel = M(0xb5bdc9, 0.3, 0.9), blk_ = M(0x15181d, 0.6, 0.3), mid = M(0x4a5260, 0.5, 0.6), rub = M(0x0c0d10, 0.95, 0);
        const led = (col, x, y, z, p, ph, rate) => { const s = sp(0.008, BM(col), x, y, z, p); anims.push((tt) => { s.visible = reduced ? true : ((tt * rate + ph) % 2) < 1.4; }); return s; };
        const GRN = new TH.Color(0.2, 2.5, 0.6), AMB = new TH.Color(3, 1.3, 0.1);

        // bay + textured back plate
        const bayM = M(0x0b0e13, 0.9, 0.2, { side: TH.BackSide }); bx(1.2, 0.9, 0.3, bayM, 0, 0, -0.15, g).geometry = new TH.BoxGeometry(1.2, 0.9, 0.3);
        const plate = tex(256, 256, (c, w, h) => {
            c.fillStyle = '#1d232d'; c.fillRect(0, 0, w, h);
            for (let i = 0; i < 1200; i++) { const v = 40 + rnd() * 45 | 0; c.fillStyle = 'rgba(' + v + ',' + v + ',' + (v + 8) + ',.5)'; c.fillRect(rnd() * w, rnd() * h, 2, 2); }
            c.strokeStyle = 'rgba(120,135,160,.22)'; c.lineWidth = 2; for (let x = 0; x <= w; x += 64) { c.beginPath(); c.moveTo(x, 0); c.lineTo(x, h); c.stroke(); c.beginPath(); c.moveTo(0, x); c.lineTo(w, x); c.stroke(); }
            c.fillStyle = 'rgba(180,190,205,.5)'; for (let x = 32; x < w; x += 64) for (let y = 32; y < h; y += 64) { c.beginPath(); c.arc(x, y, 3, 0, 7); c.fill(); }
        }); rep(plate, 2, 1.5);
        pl(1.18, 0.88, M(0xffffff, 0.7, 0.5, { map: plate }), 0, 0, -0.293, g);

        // frame, bolts, glow strips
        bayMat = BM(0x000000); { const fm = M(0x4a5260, 0.5, 0.6); bx(1.3, 0.05, 0.04, fm, 0, 0.475, 0.01, g); bx(1.3, 0.05, 0.04, fm, 0, -0.475, 0.01, g); bx(0.05, 0.9, 0.04, fm, -0.625, 0, 0.01, g); bx(0.05, 0.9, 0.04, fm, 0.625, 0, 0.01, g); bolts(g, 1.26, 0.96, 0.035); } [-0.4, 0.4].forEach((x) => bx(0.3, 0.02, 0.02, bayMat, x, 0.42, -0.04, g));

        // cable duct (top) + label
        bx(1.0, 0.05, 0.04, M(0x2a303a, 0.7, 0.3), 0.0, 0.36, -0.27, g);
        for (let i = 0; i < 22; i++) bx(0.02, 0.03, 0.002, blk_, -0.46 + i * 0.043, 0.36, -0.249, g);
        pl(0.22, 0.04, BM(0xffffff, { map: lab(128, 24, '#e0c020', '#15181d', '24V DC BUS', 15) }), 0.4, 0.31, -0.286, g);

        // DIN rail with terminal blocks
        bx(0.7, 0.03, 0.012, steel, -0.2, -0.08, -0.285, g);
        const tc = [0x2a62c9, 0xc22a2a, 0xe0c020, 0x3aa85a, 0x6b727d];
        for (let i = 0; i < 14; i++) {
            const x = -0.53 + i * 0.045;
            bx(0.038, 0.07, 0.035, M(tc[i % 5], 0.6, 0.1), x, -0.08, -0.265, g); bx(0.03, 0.01, 0.004, blk_, x, -0.055, -0.246, g); bx(0.012, 0.012, 0.004, steel, x, -0.085, -0.246, g);
            if (i % 3 === 0) led(GRN, x, -0.125, -0.25, g, i * 0.37, 1.1);
        }

        // relay modules (left of the board)
        [0.2, 0.05].forEach((y, k) => {
            bx(0.1, 0.09, 0.05, M(0x30363f, 0.5, 0.4), -0.52, y, -0.27, g); bx(0.08, 0.05, 0.004, M(0x2a62c9, 0.4, 0.3), -0.52, y + 0.005, -0.243, g);
            pl(0.07, 0.02, BM(0xffffff, { map: lab(64, 20, '#e9ebef', '#15181d', 'K' + (k + 1), 14) }), -0.52, y - 0.03, -0.241, g);
            led(k ? AMB : GRN, -0.48, y + 0.035, -0.243, g, k * 0.7, 0.9);
        });

        // wire harness, ties, clamps
        const cols = [0x15181d, 0x6b727d, 0xc22a2a, 0x2a62c9, 0xe0c020, 0x15181d]; const ties = M(0xe8e8e8, 0.8, 0);
        for (let i = 0; i < 12; i++) { const y = -0.38 + i * 0.012, z = -0.2 - (i % 3) * 0.015; tube([[-0.58, y + 0.1, z], [-0.35, y - 0.04, z - 0.02], [-0.1, y + 0.02, z], [0.12, y - 0.12, z + 0.01]], 0.011, M(cols[i % 6], 0.7, 0.1), 14, g); }
        [-0.4, -0.2].forEach((x) => bx(0.02, 0.2, 0.03, ties, x, -0.36, -0.21, g)); bx(0.05, 0.3, 0.03, M(0x8a8f99, 0.5, 0.5), -0.58, -0.3, -0.285, g);
        bx(0.1, 0.07, 0.04, mid, -0.3, -0.34, -0.28, g);
        reg('splice', bx(0.1, 0.07, 0.06, M(0x8a8f99, 0.5, 0.5), -0.3, -0.34, -0.23, g));

        // circuit board: traces, chips with pins, capacitors, header, LED
        const pcb = tex(256, 192, (c) => {
            c.fillStyle = '#0f5a34'; c.fillRect(0, 0, 256, 192); c.strokeStyle = '#c9a227'; c.lineWidth = 2;
            for (let i = 0; i < 50; i++) { const x = rnd() * 256, y = rnd() * 192; c.beginPath(); c.moveTo(x, y); c.lineTo(x + (rnd() - 0.5) * 90, y); c.lineTo(x + (rnd() - 0.5) * 90, y + (rnd() - 0.5) * 60); c.stroke(); }
            c.fillStyle = '#d9dde3'; for (let i = 0; i < 40; i++) c.fillRect(rnd() * 250, rnd() * 186, 3, 3);
            c.fillStyle = '#e9ebef'; c.font = '700 12px monospace'; c.fillText('PWR-07 REV C', 10, 184);
        });
        [[-1, -1], [1, -1], [-1, 1], [1, 1]].forEach((q) => cy(0.006, 0.03, steel, -0.25 + q[0] * 0.12, 0.2 + q[1] * 0.08, -0.285, g, 'z', 8));
        const bd = grp('board', -0.25, 0.2, -0.27, g); bx(0.28, 0.2, 0.01, M(0xffffff, 0.6, 0.1, { map: pcb }), 0, 0, 0, bd);
        const chipM = M(0x15181d, 0.5, 0.3), pinM = M(0xaab2bd, 0.3, 0.9);
        [[-0.08, 0.05, 0.05, 0.04], [-0.07, -0.05, 0.04, 0.03], [0.02, 0.06, 0.035, 0.035]].forEach((p) => {
            bx(p[2], p[3], 0.012, chipM, p[0], p[1], 0.011, bd);
            for (let k = 0; k < 5; k++) { bx(0.003, 0.008, 0.003, pinM, p[0] - p[2] / 2 + 0.005 + k * (p[2] - 0.01) / 4, p[1] + p[3] / 2 + 0.004, 0.011, bd); bx(0.003, 0.008, 0.003, pinM, p[0] - p[2] / 2 + 0.005 + k * (p[2] - 0.01) / 4, p[1] - p[3] / 2 - 0.004, 0.011, bd); }
        });
        const cap = reg('capacitor', cy(0.012, 0.03, M(0x2a62c9, 0.4, 0.4), 0.09, 0.06, 0.02, bd)); cap.rotation.x = Math.PI / 2;
        [[0.11, 0.03], [0.11, 0.075]].forEach((p) => { const c2 = cy(0.008, 0.022, M(0x1c3f9e, 0.4, 0.4), p[0], p[1], 0.016, bd); c2.rotation.x = Math.PI / 2; });
        bx(0.07, 0.014, 0.014, blk_, -0.02, -0.085, 0.012, bd); for (let k = 0; k < 6; k++) bx(0.004, 0.012, 0.004, M(0xd6b25a, 0.3, 0.9), -0.045 + k * 0.011, -0.085, 0.02, bd);
        led(GRN, -0.11, -0.08, 0.012, bd, 0.2, 1.6);
        const reg_ = grp('regulator', 0.08, -0.05, 0.015, bd); reg('regulator', reg_); bx(0.04, 0.03, 0.012, chipM, 0, 0, 0, reg_);
        for (let i = 0; i < 8; i++) bx(0.055, 0.002, 0.035, M(0xaab2bd, 0.3, 0.9), 0, 0.016, 0.012 + i * 0.005, reg_); bx(0.055, 0.002, 0.04, M(0xaab2bd, 0.3, 0.9), 0, 0.012, 0.025, reg_);

        // outlet module, plug (housing + strain relief), charger brick (label, LED, vents), foam
        bx(0.3, 0.2, 0.04, M(0x30363f, 0.6, 0.4), 0.3, 0.12, -0.28, g);[-0.09, 0, 0.09].forEach((x) => bx(0.05, 0.05, 0.01, M(0x07080a, 1, 0), 0.3 + x, 0.12, -0.255, g));
        const plug = grp('plugConnector', 0.3, 0.12, -0.23, g); reg('plugConnector', plug); bx(0.05, 0.05, 0.04, M(0x23272e, 0.5, 0.4), 0, 0, 0, plug);[-0.01, 0.01].forEach((x) => bx(0.006, 0.02, 0.02, M(0xd6b25a, 0.3, 0.9), x, 0, -0.025, plug));
        bx(0.056, 0.056, 0.012, M(0x3a424f, 0.4, 0.6), 0, 0, 0.022, plug); cy(0.014, 0.04, rub, 0, 0, 0.045, plug, 'z', 12);
        tube([[0.3, 0.12, -0.19], [0.33, -0.05, -0.17], [0.42, -0.2, -0.2]], 0.008, blk_, 12, g);
        bx(0.07, 0.05, 0.06, mid, 0.45, -0.25, -0.27, g); bx(0.1, 0.015, 0.05, M(0xe8e8e8, 0.8, 0), 0.45, -0.25, -0.195, g);
        reg('chargerBrick', bx(0.08, 0.05, 0.04, M(0x1c2026, 0.5, 0.3), 0.45, -0.25, -0.22, g));
        pl(0.06, 0.02, BM(0xffffff, { map: lab(96, 32, '#e9ebef', '#15181d', '12V 4A', 16) }), 0.45, -0.25, -0.199, g);
        led(GRN, 0.47, -0.235, -0.199, g, 0.4, 0.8); for (let i = 0; i < 4; i++) bx(0.05, 0.002, 0.002, rub, 0.45, -0.265 + i * 0.006, -0.199, g);
        const foamT = tex(128, 128, (c) => { c.fillStyle = '#26272b'; c.fillRect(0, 0, 128, 128); for (let i = 0; i < 300; i++) { c.fillStyle = 'rgba(0,0,0,.6)'; c.beginPath(); c.arc(rnd() * 128, rnd() * 128, 1 + rnd() * 3, 0, 7); c.fill(); } });
        bx(0.14, 0.12, 0.04, M(0xf2f2f2, 1, 0), 0.415, 0.12, -0.28, g);
        reg('foamBay', bx(0.12, 0.10, 0.08, M(0xffffff, 1, 0, { map: foamT, bumpMap: foamT, bumpScale: 2 }), 0.3 + 0.025 + 0.03 + 0.06, 0.12, -0.23, g)).userData.gapToConnector = 0.03;

        // cover
        const piv = grp('panelCover', 0.6, 0, 0.03, g); reg('panelCover', piv);
        bx(1.2, 0.9, 0.04, M(0x4a5260, 0.5, 0.6), -0.6, 0, 0, piv);
        pl(1.16, 0.86, BM(0xffffff, { map: tex(512, 384, (c) => { c.fillStyle = '#39404c'; c.fillRect(0, 0, 512, 384); c.strokeStyle = '#1a1e25'; c.lineWidth = 4; c.strokeRect(10, 10, 492, 364); c.fillStyle = '#e9ebef'; c.fillRect(150, 30, 210, 44); c.fillStyle = '#15181d'; c.font = '700 22px monospace'; c.textAlign = 'center'; c.fillText('ACCESS PNL 07', 255, 60); c.fillStyle = '#e0c020'; c.beginPath(); c.moveTo(400, 250); c.lineTo(470, 370); c.lineTo(330, 370); c.closePath(); c.fill(); c.fillStyle = '#111'; c.font = '700 54px monospace'; c.fillText('!', 400, 350); c.font = '12px monospace'; c.fillText('HV · QUALIFIED ONLY', 120, 360); }) }), -0.6, 0, 0.022, piv);
        [[-0.12, 0.38], [-1.08, 0.38], [-0.12, -0.38], [-1.08, -0.38]].forEach((p) => { cy(0.03, 0.02, M(0xb5bdc9, 0.3, 0.9), p[0], p[1], 0.03, piv, 'z'); bx(0.04, 0.008, 0.004, M(0x111111, 1, 0), p[0], p[1], 0.042, piv); });
        bx(0.04, 0.2, 0.05, M(0x15181d, 0.5, 0.4), -1.12, 0, 0.04, piv);
        piv.userData.setOpen = (v) => {
            v = clamp(v); piv.rotation.y = v * 105 * Math.PI / 180; bayMat.color.setRGB(v * 1.2, v * 1.5, v * 2.2); if (bayL) bayL.intensity = 1.1 * v * LS;
        };
        rig.setOpen = (v) => piv.userData.setOpen(v);
        return rig;
    }

    /* ================================================== air system */
    function buildAirSystem() {
        const A = grp('air', 0, 0, 0); areas.air = A;
        const dk = M(0x15181d, 0.7, 0.3), mt = M(0x4a5260, 0.5, 0.6);
        function vent(name, x, y, w, h, o_) {
            const g = grp(name, x, y, -2.97, A); reg(name, g);
            const wh = M(0xd9dde3, 0.55, 0.25), alu = M(0xb5bdc9, 0.3, 0.9), cord = M(0x15181d, 0.8, 0.1);
            // perforated plate: holes are real alpha cut-outs so the fan shows through
            const perf = tex(512, Math.round(512 * h / w), (c, cw, ch) => {
                c.fillStyle = '#c9ced6'; c.fillRect(0, 0, cw, ch);
                c.globalCompositeOperation = 'destination-out';
                const cols = o_.cols, rows = Math.round(cols * h / w * 1.15), dx = cw / cols, dy = ch / rows, r = Math.min(dx, dy) * 0.3, m = cw * 0.05;
                for (let j = 0; j < rows; j++) for (let i = 0; i < cols; i++) {
                    const px = (i + 0.5 + (j % 2 ? 0.5 : 0)) * dx, py = (j + 0.5) * dy;
                    if (px < m + r || px > cw - m - r || py < m + r || py > ch - m - r) continue;
                    c.beginPath(); c.arc(px, py, r, 0, 7); c.fill();
                }
                c.globalCompositeOperation = 'source-over'; c.strokeStyle = 'rgba(40,46,56,.6)'; c.lineWidth = 3; c.strokeRect(2, 2, cw - 4, ch - 4);
            });
            // housing: flange, dark cavity, fan, optional debris screen, perforated plate, frame
            bx(w + 0.1, h + 0.1, 0.02, alu, 0, 0, 0.01, g);
            bx(w, h, 0.01, M(0x07090c, 0.9, 0.2), 0, 0, 0.026, g);
            const fan = new TH.Group(); fan.position.z = 0.045; g.add(fan);
            const fr = Math.min(w, h) * 0.42, bm = M(0x2a2f38, 0.6, 0.3);
            cy(fr * 0.22, 0.03, M(0x15181d, 0.5, 0.5), 0, 0, 0, fan, 'z');
            for (let i = 0; i < 7; i++) {
                const pv = new TH.Group(); pv.rotation.z = i * Math.PI * 2 / 7; fan.add(pv);
                const b = bx(fr * 0.62, 0.05, 0.004, bm, fr * 0.55, 0, 0, pv); b.rotation.x = 0.6;
            }
            anims.push((tt, dt) => { fan.rotation.z += dt * o_.spin * (reduced ? 0.5 : 1); });
            if (o_.screen) {
                const mesh = tex(64, 64, (c) => { c.strokeStyle = 'rgba(200,208,220,.9)'; c.lineWidth = 3; c.beginPath(); c.moveTo(0, 0); c.lineTo(0, 64); c.moveTo(0, 0); c.lineTo(64, 0); c.stroke(); }); rep(mesh, w * 45, h * 45);
                pl(w - 0.02, h - 0.02, new TH.MeshBasicMaterial({ map: mesh, transparent: true, alphaTest: 0.2, side: 2, color: 0x8892a0 }), 0, 0, 0.062, g);
            }
            pl(w - 0.02, h - 0.02, new TH.MeshStandardMaterial({ map: perf, transparent: true, alphaTest: 0.5, roughness: 0.5, metalness: 0.5, side: 2 }), 0, 0, 0.078, g);
            const t_ = 0.035;
            bx(w + 0.04, t_, 0.03, wh, 0, h / 2, 0.08, g); bx(w + 0.04, t_, 0.03, wh, 0, -h / 2, 0.08, g);
            bx(t_, h, 0.03, wh, -w / 2, 0, 0.08, g); bx(t_, h, 0.03, wh, w / 2, 0, 0.08, g);
            // captive quarter-turn fasteners + tethers
            [[-1, -1], [1, -1], [-1, 1], [1, 1]].forEach((q) => {
                const fx = q[0] * (w / 2 + 0.015), fy = q[1] * (h / 2 + 0.015);
                cy(0.022, 0.02, alu, fx, fy, 0.1, g, 'z'); bx(0.032, 0.006, 0.004, M(0x111111, 1, 0), fx, fy, 0.112, g);
                tube([[fx, fy, 0.1], [fx + q[0] * 0.03, fy + q[1] * 0.02, 0.07], [fx + q[0] * 0.05, fy + q[1] * 0.05, 0.03]], 0.0025, cord, 8, g);
            });
            // label + status LED
            pl(o_.lw, 0.04, BM(0xffffff, { map: lab(192, 32, '#e9ebef', '#15181d', o_.label, 16) }), 0, -h / 2 - 0.075, 0.03, g);
            const led = sp(0.01, BM(new TH.Color(0.2, 2.5, 0.6)), w / 2 - 0.04, -h / 2 - 0.075, 0.035, g);
            anims.push((tt) => { led.visible = reduced ? true : ((tt * 0.9) % 2) < 1.5; });
            if (o_.tab) { bx(0.1, 0.05, 0.012, M(0xe0742a, 0.6, 0.1), 0, h / 2 + 0.005, 0.105, g); bx(0.1, 0.012, 0.03, M(0xe0742a, 0.6, 0.1), 0, h / 2 + 0.03, 0.115, g); }
            // flexible accordion duct up to the ceiling (outside the anchor group so the camera fit is unchanged)
            if (o_.duct) {
                const d = grp(name + 'Duct', x, y, -2.97, A), top = 1.75 - y, y0 = h / 2 + 0.1, dr = 0.085;
                bx(0.17, 0.09, 0.13, M(0x4a5260, 0.5, 0.6), 0, h / 2 + 0.06, 0.06, d);
                cy(dr * 0.94, top - y0, M(0xcfd3da, 0.85, 0.05), 0, (top + y0) / 2, 0.06, d);
                const rg = geo('rib', () => new TH.TorusGeometry(dr, 0.011, 6, 20)), rm = M(0xe7e9ee, 0.8, 0.05);
                for (let yy = y0 + 0.02; yy < top - 0.02; yy += 0.034) { const m = put(new TH.Mesh(rg, rm), 0, yy, 0.06, d); m.rotation.x = Math.PI / 2; }
                [y0, top - 0.03].forEach((yy) => cy(dr * 1.08, 0.025, alu, 0, yy, 0.06, d));
            }
            return g;
        }
        vent('supplyVent', -1.55, 1.2, 0.5, 0.36, { cols: 18, spin: 1.2, label: 'SUPPLY DIFFUSER', lw: 0.3, duct: true });
        vent('returnGrille', 1.55, 1.2, 0.7, 0.5, { cols: 26, spin: 2.4, label: 'CABIN FAN INLET', lw: 0.34, screen: true, tab: true });
        // ribbon on a short stand
        const rb = grp('ribbon', -1.55, 0.85, -2.65, A); reg('ribbon', rb);
        bx(0.02, 0.02, 0.32, mt, 0, 0, -0.16, rb); bx(0.08, 0.08, 0.01, mt, 0, 0, -0.315, rb); bolts(rb, 0.06, 0.06, -0.31);
        const rg = new TH.PlaneGeometry(0.45, 0.05, 12, 1); rg.translate(0.225, 0, 0); rg.rotateY(-Math.PI / 2);
        const rp = rg.attributes.position, rz = Array.from({ length: rp.count }, (_, i) => rp.getZ(i));
        rb.add(new TH.Mesh(rg, M(0xff7a1a, 0.6, 0, { side: 2, emissive: 0x552000 })));
        anims.push((tt) => { for (let i = 0; i < rp.count; i++) rp.setX(i, Math.sin(tt * 2.2 - rz[i] * 9) * 0.035 * (rz[i] / 0.45)); rp.needsUpdate = true; });
        // life-support gauge panel
        const gp = grp('gaugePanel', 0, 0.1, -2.97, A); reg('gaugePanel', gp); gp.scale.setScalar(1.6);
        bx(1.6, 0.5, 0.04, M(0x2a303a, 0.5, 0.6), 0, 0, 0.02, gp); bolts(gp, 1.5, 0.4, 0.045);
        const G = [['O2', CF.gauges.O2, '%', 0.7, -0.5], ['PRESSURE', CF.gauges.PRESSURE, 'kPa', 0.67, 0], ['CO2', CF.gauges.CO2, '%', 0.2, 0.5]];
        G.forEach((q, i) => {
            const dial = tex(256, 256, (c) => {
                c.fillStyle = '#05080c'; c.fillRect(0, 0, 256, 256); c.strokeStyle = '#8fa6c6'; c.lineWidth = 3; c.beginPath(); c.arc(128, 128, 112, 0, 7); c.stroke();
                for (let k = 0; k <= 20; k++) { const a = Math.PI * 0.75 + k / 20 * Math.PI * 1.5, r2 = k % 5 ? 98 : 88; c.beginPath(); c.moveTo(128 + Math.cos(a) * r2, 128 + Math.sin(a) * r2); c.lineTo(128 + Math.cos(a) * 108, 128 + Math.sin(a) * 108); c.stroke(); }
                c.fillStyle = '#cfe0f5'; c.font = '700 26px monospace'; c.textAlign = 'center'; c.fillText(q[0], 128, 190); c.fillStyle = '#4fd6c9'; c.font = '22px monospace'; c.fillText(q[1] + ' ' + q[2], 128, 224);
            });
            pl(0.36, 0.36, BM(0xffffff, { map: dial }), q[4], 0.02, 0.043, gp);
            const nd = grp('needle' + i, q[4], 0.02, 0.05, gp); bx(0.008, 0.15, 0.004, BM(0xff7a2a), 0, 0.07, 0, nd);
            const th = -(Math.PI * 0.75 + q[3] * Math.PI * 1.5) - Math.PI / 2;
            anims.push((tt) => { nd.rotation.z = th + Math.sin(tt * 23 + i) * 0.012 + Math.sin(tt * 7 + i * 2) * 0.01; });
            sp(0.012, BM(new TH.Color(0.3, 2.5, 0.8)), q[4] + 0.15, -0.2, 0.05, gp); bx(0.03, 0.012, 0.02, M(0xaab4c4, 0.4, 0.8), q[4] - 0.15, -0.2, 0.05, gp);
        });
        // smoke detectors with blinking LEDs
        [-0.7, 0, 0.7].forEach((x, i) => {
            const d = grp('detector' + (i + 1), x, 1.5, -2.97, A); reg('detector' + (i + 1), d);
            cy(0.095, 0.012, M(0x4a5260, 0.5, 0.6), 0, 0, 0.01, d, 'z'); cy(0.08, 0.03, M(0xe3e6ea, 0.5, 0.2), 0, 0, 0.02, d, 'z'); cy(0.03, 0.01, M(0x15181d, 0.3, 0.6), 0, 0, 0.04, d, 'z');
            const led = sp(0.008, BM(new TH.Color(0.2, 2.5, 0.6)), 0.05, 0.04, 0.04, d); anims.push((tt) => { led.visible = (tt * 0.8 + i * 0.3) % 2 < 1.6; });
        });
    }

    /* ================================================== safety wall */
    function buildSafetyWall() {
        const S = grp('safety', -0.17, 0, -3.4); areas.safety = S; S.rotation.y = -Math.PI / 2; const mt = M(0x4a5260, 0.5, 0.6), dk = M(0x15181d, 0.7, 0.3);
        const sp_ = grp('suppressionPort', 1.75, 0.55, -2.97, S); reg('suppressionPort', sp_);
        bx(0.6, 0.45, 0.04, M(0x2e3540, 0.5, 0.6), 0, 0, 0.02, sp_); bolts(sp_, 0.54, 0.39, 0.045); cy(0.025, 0.1, mt, 0.22, 0.12, -0.03, sp_, 'z');
        [['nozzleMist', 'MIST', 0.09], ['nozzleN2', 'N2', -0.09]].forEach((n) => {
            const ng = grp(n[0], -0.05, n[2], 0.04, sp_); reg(n[0], ng); bx(0.34, 0.12, 0.02, dk, 0, 0, 0, ng);
            pl(0.3, 0.1, BM(0xffffff, { map: tex(160, 56, (c) => { c.fillStyle = '#0a0c10'; c.fillRect(0, 0, 160, 56); c.strokeStyle = '#46505e'; c.lineWidth = 2; for (let i = 0; i < 8; i++) { c.beginPath(); c.moveTo(60, 8 + i * 6); c.lineTo(152, 8 + i * 6); c.stroke(); } c.fillStyle = '#9fe8ff'; c.font = '700 20px monospace'; c.fillText(n[1], 8, 36); }) }), 0, 0, 0.012, ng);
            sp(0.01, BM(new TH.Color(0.3, 2.5, 0.8)), 0.2, n[2] + 0.04, 0.045, sp_);
        });
        // extinguisher
        const ex = grp('extinguisher', 2.35, 0.1, -2.9, S); reg('extinguisher', ex); ex.rotation.z = 10 * Math.PI / 180;
        cy(0.07, 0.5, M(0xc42a22, 0.35, 0.4), 0, 0, 0, ex); sp(0.07, M(0xc42a22, 0.35, 0.4), 0, 0.25, 0, ex); bx(0.12, 0.03, 0.03, dk, 0, 0.33, 0, ex);
        tube([[0.03, 0.31, 0.02], [0.14, 0.26, 0.06], [0.12, 0.1, 0.1]], 0.008, dk, 10, ex); const horn = put(new TH.Mesh(geo('horn', () => new TH.ConeGeometry(0.03, 0.09, 12)), M(0xf1f1ee, 0.5, 0.1)), 0.12, 0.04, 0.1, ex); horn.rotation.x = Math.PI;
        cy(0.025, 0.012, M(0xdddddd, 0.3, 0.8), 0, 0.2, 0.07, ex, 'z'); pl(0.1, 0.08, BM(0xffffff, { map: lab(64, 48, '#f2f2f2', '#222', 'CO2', 24) }), 0, 0.02, 0.071, ex);
        [-0.1, 0.12].forEach((y) => { cy(0.077, 0.035, mt, 0, y, 0, ex); bx(0.07, 0.04, 0.06, mt, 0, y, -0.05, ex); bx(0.03, 0.04, 0.02, M(0x2a2f38, 0.9, 0), 0, y, 0.08, ex);[-0.03, 0.03].forEach((x) => cy(0.01, 0.012, M(0xb5bdc9, 0.35, 0.85), x, y, -0.08, ex, 'z', 8)); });
        // mask case with a clear lid
        const mc = grp('maskCase', 2.0, -0.55, -2.95, S); reg('maskCase', mc);
        bx(0.6, 0.25, 0.1, M(0x2e3540, 0.5, 0.5), 0, 0, 0, mc); bx(0.62, 0.27, 0.01, new TH.MeshStandardMaterial({ color: 0xcfe8ff, transparent: true, opacity: 0.22, roughness: 0.1 }), 0, 0, 0.06, mc); bolts(mc, 0.58, 0.23, 0.066);
        [-0.14, 0.14].forEach((x) => { const m = sp(0.07, M(0xd8dde4, 0.7, 0.1), x, 0, 0.02, mc); m.scale.set(1, 1.1, 0.5); sp(0.03, dk, x, -0.03, 0.045, mc); });
        // fire rig: arm + charred swatch (flame-ready anchor)
        const fr = grp('fireRig', 1.85, -0.2, -2.95, S); reg('fireRig', fr); bx(0.03, 0.03, 0.6, mt, 0, 0, 0.3, fr); bx(0.1, 0.1, 0.015, mt, 0, 0, 0.008, fr); bolts(fr, 0.08, 0.08, 0.02);
        const fs = grp('fireSwatch', 0, 0, 0.6, fr); reg('fireSwatch', fs); bx(0.1, 0.1, 0.01, M(0x14100e, 1, 0, { map: speck('#1a1411', 300, 0.1) }), 0, 0, 0, fs);
        const em = BM(new TH.Color(3, 0.9, 0.2), { transparent: true, opacity: 0.35 }); bx(0.1, 0.008, 0.012, em, 0, 0.05, 0.003, fs);
        const fa = new TH.Object3D(); fa.name = 'flameAnchor'; fa.position.set(0, 0.05, 0.01); fs.add(fa); fs.userData.flameAnchor = fa;
        anims.push((tt) => { em.opacity = 0.3 + 0.1 * Math.sin(tt * 4); });
    }

    /* ================================================== camera */
    const baseQ = new TH.Quaternion(), tq = new TH.Quaternion(), eu = new TH.Euler(0, 0, 0, 'YXZ'); let nx = 0, ny = 0, yaw = 0, pitch = 0;
    function fitCamera() {
        const W = root.clientWidth || window.innerWidth, H = root.clientHeight || window.innerHeight; camera.aspect = W / H;
        const cp = new V3(...CF.camera.pos), lk = new V3(...CF.camera.look), dir = lk.clone().sub(cp).normalize();
        scene.updateMatrixWorld(true);
        const bx_ = (ks) => ks.map((k) => new TH.Box3().setFromObject(anchors.get(k))), full = bx_(CF.fitKeys), core = bx_(CF.coreKeys), v = new V3();
        const fits = (bs) => { camera.updateMatrixWorld(true); return bs.every((b) => { for (let i = 0; i < 8; i++) { v.set(i & 1 ? b.max.x : b.min.x, i & 2 ? b.max.y : b.min.y, i & 4 ? b.max.z : b.min.z).project(camera); if (v.z > 1 || Math.abs(v.x) > CF.camera.fill || Math.abs(v.y) > CF.camera.fill) return false; } return true; }); };
        const tryFit = (bs, fovs, maxS) => { for (const f of fovs) { camera.fov = f; for (let s = 0; s <= maxS; s += 0.05) { camera.position.copy(cp).addScaledVector(dir, -s); camera.lookAt(lk); camera.updateProjectionMatrix(); if (fits(bs)) return true; } } return false; };
        if (!tryFit(full, [55, 60, 65, 70, 75], 0.5) && !tryFit(full, [75], 4)) tryFit(core, [75], 9);
        camera.updateMatrixWorld(true); baseQ.copy(camera.quaternion);
    }
    function resize() { const W = root.clientWidth || window.innerWidth, H = root.clientHeight || window.innerHeight; renderer.setSize(W, H); overlay.resize(W, H); if (ready) fitCamera(); }

    /* ================================================== scan runner */
    let po = 0, pt = 0; // panel open amount (current / target)
    const rigObj = {};
    const ctx = {
        THREE: TH, scene, camera, renderer, anchors, areas, items: CF.items, categoryMap: CF.categoryMap, overlay, lens, rig: rigObj, category: null,
        reducedMotion: reduced, quality, openPanel(v) { pt = v; }, centerOf, hoverPos, get accent() { return hex(); }, get accentColor() { return accent; }, get flamo() { return flamo; }
    };
    function defaultScan(c) {
        const list = c.categoryMap[c.category] || [], k = Math.min(4, list.length), tg = [];
        for (let i = 0; i < k; i++) { const n = list[k === 1 ? 0 : Math.round(i * (list.length - 1) / (k - 1))]; if (tg[tg.length - 1] !== n) tg.push(n); }
        const dur = CF.T.test, slot = dur / tg.length, hs = []; let idx = -1, shown = -1;
        const bg_ = new TH.BufferGeometry(); bg_.setAttribute('position', new TH.BufferAttribute(new Float32Array(6), 3));
        const beam = new TH.Line(bg_, new TH.LineBasicMaterial({ color: c.accent })); beam.frustumCulled = false;
        const dot = new TH.Mesh(new TH.SphereGeometry(0.02, 8, 8), new TH.MeshBasicMaterial({ color: c.accent })); dot.visible = false;
        beam.layers.set(1); dot.layers.set(1);
        return {
            duration: dur,
            start() { c.scene.add(beam, dot); },
            update(tm) {
                const i = Math.min(tg.length - 1, tm / slot | 0), lt = tm - i * slot, ob = c.anchors.get(tg[i]), cen = c.centerOf(ob);
                if (i !== idx) {
                    if (i > 0 && tg[i - 1] === 'panelCover' && c.category === 'ignition') c.openPanel(1);
                    idx = i; c.flamo.lookAt(cen); c.flamo.flyTo(c.hoverPos(ob), c.reducedMotion ? 0 : slot * 450);
                }
                const a = c.flamo.object3D.position, e = a.clone().lerp(cen, clamp(lt / (slot * 0.5)));
                beam.geometry.attributes.position.setXYZ(0, a.x, a.y, a.z); beam.geometry.attributes.position.setXYZ(1, e.x, e.y, e.z); beam.geometry.attributes.position.needsUpdate = true;
                beam.material.color.set(c.accent); dot.material.color.set(c.accent); dot.position.copy(e); dot.visible = true;
                if (lt >= slot * 0.5 && shown !== i) {
                    shown = i; hs.forEach((h) => h.remove()); hs.length = 0;
                    const row = c.items.find((x) => x.id === tg[i]);
                    hs.push(c.overlay.bracket(ob, { padding: 6 }), c.overlay.tag(ob, row ? row.mat : pretty(tg[i]), { side: 'auto' }));
                    c.lens.show(ob, { label: pretty(tg[i]) });
                }
            },
            dispose() { c.scene.remove(beam, dot); bg_.dispose(); beam.material.dispose(); dot.geometry.dispose(); dot.material.dispose(); }
        };
    }
    function cancel() {
        pt = 0;
        seq++; if (cur) { try { cur.p.dispose(); } catch (e) { } cur = null; }
        lens.hide(); overlay.clear(); flamo && flamo.lookAt(null);
    }
    function startScan(id, my) {
        if (my !== seq || dead) return;
        const p = (plugins[id] || defaultScan)(ctx); mode = 'scan';
        cur = { id, p, t: 0, dur: Math.min(p.duration || CF.T.test, CF.T.scanMax), my };
        p.start && p.start();
    }
    function finish() {
        const c = cur; cur = null; try { c.p.dispose(); } catch (e) { }
        lens.hide(); mode = 'idle'; chip && chip.set(CF.names[c.id] + ' // DONE');
        o.onScanDone && o.onScanDone(c.id); container.dispatchEvent(new CustomEvent('scan:done', { detail: { id: c.id } }));
    }
    function setCategory(id) {
        if (!ready) { queued = () => setCategory(id); return; }
        if (!CF.categoryMap[id]) { goHome(); return; }
        cancel(); const my = seq; mode = 'fly'; ctx.category = id; setAccent(CF.accents[id]);
        chip && chip.remove(); chip = overlay.panel(CF.names[id] + ' // SCANNING', { x: 20, y: 20, anchor: 'tl', persist: true });
        const first = anchors.get(CF.categoryMap[id][0]); flamo.lookAt(centerOf(first));
        flamo.flyTo(hoverPos(first), reduced ? 0 : CF.T.fly * 1000).then(() => { if (my === seq) startScan(id, my); });
    }
    function goHome() {
        if (!ready) { queued = goHome; return; }
        cancel(); const my = seq; chip && chip.remove(); chip = null; ctx.category = null; setAccent(CF.accents.home); mode = 'return';
        flamo.flyTo(homePos(), reduced ? 0 : 900).then(() => { if (my === seq) { mode = 'home'; flamo.setHome(homePos(), true); } });
    }
    function registerScan(id, factory) { plugins[id] = factory; }

    /* ================================================== build + loop */
    const onResize = () => resize();
    const onMove = (e) => { nx = e.clientX / window.innerWidth * 2 - 1; ny = e.clientY / window.innerHeight * 2 - 1; };
    let started = false;
    function frame(now) {
        raf = requestAnimationFrame(frame);
        const dt = Math.min((now - last) / 1000, 0.05); last = now;
        if (o.isActive && !o.isActive()) return; last = now; t += dt;
        if (aT < 1) { aT = Math.min(1, aT + dt / CF.T.accent); accent.lerpColors(aFrom, aTo, aT); applyAccent(); }
        if (!reduced) {
            yaw += (-nx * CF.camera.yaw - yaw) * (1 - Math.exp(-6 * dt)); pitch += (-ny * CF.camera.pitch - pitch) * (1 - Math.exp(-6 * dt));
            eu.set(pitch * Math.PI / 180, yaw * Math.PI / 180, 0); camera.quaternion.copy(baseQ).multiply(tq.setFromEuler(eu));
        }
        camera.updateMatrixWorld();
        if (mode === 'home') flamo.setHome(homePos(), true);
        anims.forEach((f) => f(t, dt)); amberL.intensity = (0.5 + 0.5 * Math.abs(Math.sin(t * 1.6))) * LS;
        if (po !== pt) {
            po = reduced ? pt : po + (pt - po) * (1 - Math.exp(-4 * dt));
            if (Math.abs(pt - po) < 0.002) po = pt;
            rigObj.panel && rigObj.panel.setOpen(po);
        }
        if (!low && !reduced) sway.forEach((s) => { s.g.position.y = s.y + Math.sin(t * 0.7 + s.ph) * s.a; s.g.rotation.z = Math.sin(t * 0.5 + s.ph * 2) * 0.012; });
        flamo.update(dt, t);
        if (cur) { cur.t += dt; cur.p.update(cur.t, dt); if (cur.t >= cur.dur) finish(); }
        lens.pre(dt);
        renderer.render(scene, camera); lens.render(dt); overlay.update(performance.now()); updateHead();
    }
    function updateHead() {
        if (!flamo) return;
        const W = root.clientWidth, H = root.clientHeight; if (!W || !H) return;
        const p = flamo.object3D.position.clone(), c = p.clone().applyMatrix4(camera.matrixWorldInverse);
        if (c.z > -0.1) { headEl.style.visibility = 'hidden'; return; }
        const f = H / (2 * Math.tan(camera.fov * Math.PI / 360)), px = CF.flamo.width * CF.flamo.headScale * f / -c.z * (flamo.pop == null ? 1 : flamo.pop);
        if (px < 2) { headEl.style.visibility = 'hidden'; return; }
        p.project(camera);
        const x = (p.x * 0.5 + 0.5) * W - px / 2, y = (-p.y * 0.5 + 0.5) * H - px / 2;
        headEl.style.width = headEl.style.height = px.toFixed(1) + 'px';
        headEl.style.transform = 'translate3d(' + x.toFixed(1) + 'px,' + y.toFixed(1) + 'px,0)';
        headEl.style.visibility = 'visible';
    }
    async function build() {
        const steps = [buildShell, () => Object.assign(rigObj, buildWorkbench()), () => { rigObj.panel = buildElectricalPanel(); }, buildAirSystem, buildSafetyWall];
        for (let i = 0; i < steps.length; i++) { if (dead) return; steps[i](); ldBar.style.width = (i + 1) / steps.length * 100 + '%'; await new Promise(requestAnimationFrame); }
        if (dead) return;
        resize(); fitCamera();
        flamo = makeFlamo(TH, { camera, accent: hex() });
        {
            const ss = flamo.setState.bind(flamo), sa = flamo.setAmplitude.bind(flamo);
            flamo.setState = (n) => { ss(n); o.onFlamoState && o.onFlamoState(n); };
            flamo.setAmplitude = (v) => { sa(v); o.onFlamoAmplitude && o.onFlamoAmplitude(v); };
        }
        flamo.setState('idle'); scene.add(flamo.object3D);
        flamo.object3D.position.copy(homePos()); flamo.setHome(homePos(), true);
        root.querySelector('.ld').style.display = 'none'; ready = true; started = true;
        blk.style.transition = 'opacity ' + CF.T.fadeIn + 's ease'; blk.style.opacity = 0;
        last = performance.now(); raf = requestAnimationFrame(frame);
        if (queued) { const q = queued; queued = null; q(); }
    }
    window.addEventListener('resize', onResize); window.addEventListener('pointermove', onMove);
    const onVis = () => { if (!started || dead) return; cancelAnimationFrame(raf); if (!document.hidden) { last = performance.now(); raf = requestAnimationFrame(frame); } };
    document.addEventListener('visibilitychange', onVis);
    resize(); build();

    return {
        setCategory, goHome, registerScan, setAccent,
        getHeadHost() { return headEl; },
        setDim(v) { renderer.domElement.style.filter = v ? 'brightness(' + (1 - 0.6 * v) + ') blur(' + 2 * v + 'px)' : 'none'; },
        fadeOut(ms) { blk.style.transition = 'opacity ' + ms + 'ms ease'; blk.style.opacity = 1; },
        getContext() { return ctx; },
        dispose() {
            if (dead) return; dead = true; cancelAnimationFrame(raf);
            window.removeEventListener('resize', onResize); window.removeEventListener('pointermove', onMove); document.removeEventListener('visibilitychange', onVis);
            cancel(); overlay.dispose(); lens.dispose(); flamo && flamo.dispose();
            scene.traverse((ob) => { ob.geometry && ob.geometry.dispose();[].concat(ob.material || []).forEach((m) => { for (const k in m) { const x = m[k]; x && x.isTexture && x.dispose(); } m.dispose(); }); });
            Object.keys(gc).forEach((k) => gc[k].dispose()); texs.forEach((x) => x.dispose());
            renderer.dispose(); renderer.forceContextLoss(); root.remove();
        }
    };
}

/* ======================================================== React component */
const SpaceCraftScene = forwardRef(function SpaceCraftScene(
    { category = null, quality, reducedMotion, onScanDone, lensTarget, createFlamo: customFlamo, showDevPanel = false, emberState, emberAmplitude, emberAlert = false, className = '', style, active = true },
    ref
) {
    const hostRef = useRef(null);
    const sceneRef = useRef(null);
    const cbRef = useRef({});
    cbRef.current = { onScanDone, lensTarget };
    const activeRef = useRef(active);
    activeRef.current = active;

    // quality can be overridden at runtime by the dev panel (remounts the scene)
    const [devQuality, setDevQuality] = useState(null);
    const [dimmed, setDimmed] = useState(false);
    const [headHost, setHeadHost] = useState(null);
    const [flState, setFlState] = useState('idle');   // driven by flamo.setState(...)
    const [flAmp, setFlAmp] = useState(0);            // driven by flamo.setAmplitude(...)
    const q = devQuality || quality;

    useImperativeHandle(ref, () => ({
        setCategory: (id) => sceneRef.current?.setCategory(id),
        goHome: () => sceneRef.current?.goHome(),
        registerScan: (id, f) => sceneRef.current?.registerScan(id, f),
        setAccent: (h) => sceneRef.current?.setAccent(h),
        setDim: (v) => sceneRef.current?.setDim(v),
        fadeOut: (ms) => sceneRef.current?.fadeOut(ms),
        getContext: () => sceneRef.current?.getContext(),
    }), []);

    // mount / unmount the three.js scene
    useEffect(() => {
        const scene = mountSpaceCraftScene(hostRef.current, {
            quality: q,
            reducedMotion,
            isActive: () => activeRef.current,
            createFlamo: customFlamo,
            onScanDone: (id) => cbRef.current.onScanDone?.(id),
            lensTarget: () => cbRef.current.lensTarget?.(),
            onFlamoState: (s) => setFlState(s),
            onFlamoAmplitude: (a) => setFlAmp(a),
        });
        sceneRef.current = scene;
        setHeadHost(scene.getHeadHost());
        return () => {
            setHeadHost(null);
            scene.dispose();
            sceneRef.current = null;
        };
    }, [q, reducedMotion, customFlamo]);

    // controlled category (null = home). Calls made before the scene is ready are queued internally.
    useEffect(() => {
        const s = sceneRef.current;
        if (!s) return;
        if (category) s.setCategory(category);
        else s.goHome();
    }, [category, q, reducedMotion, customFlamo]);

    const EMBER_STATE = { idle: 'idle', listening: 'listening', thinking: 'thinking', talking: 'speaking', speaking: 'speaking', connecting: 'connecting', disconnected: 'disconnected' };
    const headState = emberState ?? EMBER_STATE[flState] ?? 'idle';

    return (
        <div className={`cabin-host ${className}`} style={style} ref={hostRef}>
            {headHost && createPortal(
                <EmberHead state={headState} amplitude={emberAmplitude ?? flAmp} alert={emberAlert} size="100%" />,
                headHost
            )}
            {showDevPanel && (
                <div className="cabin-dev">
                    <button type="button" onClick={() => sceneRef.current?.goHome()}>Home</button>
                    {Object.keys(CONFIG.categoryMap).map((id) => (
                        <button key={id} type="button" onClick={() => sceneRef.current?.setCategory(id)}>{id}</button>
                    ))}
                    <button
                        type="button"
                        onClick={() => { const v = !dimmed; setDimmed(v); sceneRef.current?.setDim(v ? 0.4 : 0); }}
                    >
                        Dim 40%
                    </button>
                    <button type="button" onClick={() => setDevQuality(q === 'high' ? 'low' : 'high')}>
                        Quality: {q || 'auto'}
                    </button>
                </div>
            )}
        </div>
    );
});

export default SpaceCraftScene;