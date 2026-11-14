import * as THREE from 'three'; // written for three r186 (physically based lights)

/**
 * Ember — the flying flame robot. Framework-agnostic (plain Three.js, no React).
 *
 *   const bus = createBus();
 *   const ember = new Ember({ scene, bus, host: someElement });
 *   // every frame:  ember.tick(deltaSeconds);
 *
 * Constructor options
 *   scene  THREE.Scene   the scene Ember is added to
 *   bus    createBus()   event bus Ember listens on
 *   host   HTMLElement   element whose CSS variable --accent colors the scan beam (default <html>)
 *
 * Bus events Ember listens to
 *   'agent:state'      'connecting' | 'idle' | 'listening' | 'thinking' | 'speaking' | 'disconnected'
 *   'agent:amplitude'  0..1 mouth opening while speaking
 *   'verdict:update'   number; >= 85 turns Ember red (alert)
 *   'category:select'  re-reads --accent from host
 *
 * Methods
 *   ember.pos / ember.root      position and Group of the full robot
 *   ember.flyTo(vec3, ms)       Promise
 *   ember.lookAt(vec3|Object3D|null)
 *   ember.scan(targets, ms)     Promise, shows the scan beam
 *   ember.dock(el) / undock()   render only the head in its own canvas inside el
 *   ember.tick(dt)              call once per frame
 *   ember.S.shape (0..1)        mouth shape variation while speaking
 */

/**
 * Lighting helpers for modern three (r155+).
 * The scene was tuned for the old "legacy" light model, so intensities are
 * multiplied by PI and point lights use decay 0 (no inverse-square falloff).
 * Tweak LIGHT_SCALE to make every light brighter/darker at once.
 */
export const LIGHT_SCALE = Math.PI;
export function pointLight(color, intensity, distance) {
    return new THREE.PointLight(color, intensity * LIGHT_SCALE, distance, 0);
}
export function ambientLight(color, intensity) {
    return new THREE.AmbientLight(color, intensity * LIGHT_SCALE);
}

/** Minimal event bus used by Ember (emit / on). */
export function createBus() {
    const bus = new EventTarget();
    bus.emit = function (n, d) { this.dispatchEvent(new CustomEvent(n, { detail: d })); };
    bus.on = function (n, f) { this.addEventListener(n, (e) => f(e.detail)); };
    return bus;
}

const Ember = (function () {
    const ORG = 0xff6a2a, TMP = new THREE.Object3D(), V = new THREE.Vector3();
    let GT = null;
    function gt() { if (GT) return GT; const c = document.createElement('canvas'); c.width = c.height = 64; const g = c.getContext('2d'), r = g.createRadialGradient(32, 32, 0, 32, 32, 32); r.addColorStop(0, 'rgba(255,255,255,1)'); r.addColorStop(0.3, 'rgba(255,255,255,.4)'); r.addColorStop(1, 'rgba(255,255,255,0)'); g.fillStyle = r; g.fillRect(0, 0, 64, 64); return (GT = new THREE.CanvasTexture(c)); }
    function spr(col, sz, op) { const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: gt(), color: col, blending: 2, transparent: true, depthWrite: false, opacity: op || 1 })); s.scale.set(sz, sz, 1); return s; }
    function rr(w, h, r) { const s = new THREE.Shape(), x = -w / 2, y = -h / 2; s.moveTo(x + r, y); s.lineTo(x + w - r, y); s.quadraticCurveTo(x + w, y, x + w, y + r); s.lineTo(x + w, y + h - r); s.quadraticCurveTo(x + w, y + h, x + w - r, y + h); s.lineTo(x + r, y + h); s.quadraticCurveTo(x, y + h, x, y + h - r); s.lineTo(x, y + r); s.quadraticCurveTo(x, y, x + r, y); return new THREE.ShapeGeometry(s); }
    function makeEnv(r) {
        const s = new THREE.Scene(); s.add(new THREE.Mesh(new THREE.SphereGeometry(10, 16, 16), new THREE.MeshBasicMaterial({ side: 1, color: 0x0a0e16 })));
        function pl(c, x, y, z, w, h) { const m = new THREE.Mesh(new THREE.PlaneGeometry(w, h), new THREE.MeshBasicMaterial({ color: c, side: 2 })); m.position.set(x, y, z); m.lookAt(0, 0, 0); s.add(m); }
        pl(new THREE.Color(6, 6, 6.5), 3, 5, 4, 6, 2); pl(new THREE.Color(5, 2, 0.6), -6, 1, 2, 3, 4); pl(new THREE.Color(0.6, 1.2, 3), 4, -1, -6, 4, 4); pl(new THREE.Color(2, 2, 2), 0, -5, 3, 8, 2);
        return new THREE.PMREMGenerator(r).fromScene(s, 0.04).texture;
    }
    function fshape() { const s = new THREE.Shape(); s.moveTo(0, -0.52); s.bezierCurveTo(0.3, -0.52, 0.5, -0.36, 0.5, -0.14); s.bezierCurveTo(0.5, 0, 0.42, 0.1, 0.55, 0.3); s.bezierCurveTo(0.46, 0.27, 0.4, 0.24, 0.33, 0.2); s.bezierCurveTo(0.34, 0.4, 0.2, 0.5, 0.06, 0.66); s.bezierCurveTo(0, 0.5, -0.1, 0.45, -0.2, 0.3); s.bezierCurveTo(-0.3, 0.4, -0.4, 0.42, -0.5, 0.42); s.bezierCurveTo(-0.42, 0.28, -0.52, 0.1, -0.5, -0.12); s.bezierCurveTo(-0.5, -0.36, -0.3, -0.52, 0, -0.52); return s; }
    function lay(sc, dy, z, col) { const g = new THREE.ExtrudeGeometry(fshape(), { depth: 0.05, bevelEnabled: true, bevelThickness: 0.03, bevelSize: 0.025, bevelSegments: 4, curveSegments: 28 }); g.scale(sc, sc, 1); g.translate(0, dy, z); return new THREE.Mesh(g, new THREE.MeshStandardMaterial({ color: col, roughness: 0.35, metalness: 0.05, emissive: col, emissiveIntensity: 0.28 })); }
    function rsh(w, h, r) { const s = new THREE.Shape(), x = -w / 2, y = -h / 2; s.moveTo(x + r, y); s.lineTo(x + w - r, y); s.quadraticCurveTo(x + w, y, x + w, y + r); s.lineTo(x + w, y + h - r); s.quadraticCurveTo(x + w, y + h, x + w - r, y + h); s.lineTo(x + r, y + h); s.quadraticCurveTo(x, y + h, x, y + h - r); s.lineTo(x, y + r); s.quadraticCurveTo(x, y, x + r, y); return s; }

    /* Ember: a friendly flying flame buddy (cartoon fire character with a glossy screen face) */
    function build(o) {
        const g = new THREE.Group(), P = { g, glow: [], sp: [] }, body = new THREE.Group(), face = new THREE.Group();
        let i;
        P.aura = spr(0xff6a2a, 1.8, 0.35); P.aura.position.z = -0.25; g.add(body); g.add(P.aura);
        P.L = [lay(1, 0, 0, 0xff1800), lay(0.82, -0.03, 0.045, 0xff6600), lay(0.6, -0.1, 0.09, 0xffb800)];
        P.L.forEach((m) => body.add(m)); body.position.z = -0.09; P.cols = P.L.map((m) => m.material);
        face.add(new THREE.Mesh(new THREE.ExtrudeGeometry(rsh(0.56, 0.4, 0.07), { depth: 0.025, bevelEnabled: true, bevelThickness: 0.012, bevelSize: 0.012, bevelSegments: 3, curveSegments: 16 }), new THREE.MeshStandardMaterial({ color: 0x160a10, roughness: 0.12, metalness: 0.4 })));
        const gl = new THREE.Mesh(rr(0.54, 0.38, 0.06), new THREE.MeshBasicMaterial({ color: 0x07030a })); gl.position.z = 0.0375; face.add(gl);
        const sh = new THREE.Mesh(new THREE.PlaneGeometry(0.05, 0.42), new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.07, depthWrite: false })); sh.position.set(-0.16, 0, 0.04); sh.rotation.z = 0.35; face.add(sh);
        face.position.set(0, -0.03, 0.075); g.add(face);
        P.eyeM = new THREE.MeshBasicMaterial({ color: new THREE.Color(1.9, 1.15, 0.5) }); P.eyes = new THREE.Group();
        [-1, 1].forEach((s) => { const e = new THREE.Mesh(rr(0.07, 0.085, 0.03), P.eyeM); e.position.set(s * 0.1, 0.05, 0.042); P.eyes.add(e); }); face.add(P.eyes);
        P.chk = new THREE.Group();
        P.cheeks = [-1, 1].map((sd) => { const c = new THREE.Mesh(new THREE.CircleGeometry(0.05, 32), new THREE.MeshBasicMaterial({ color: 0x07030a })); c.scale.x = 1.25; c.position.set(sd * 0.1, -0.1, 0.0435); P.chk.add(c); return c; });
        P.chk.visible = false; face.add(P.chk);
        P.dots = [-1, 0, 1].map((k) => { const d = new THREE.Mesh(new THREE.CircleGeometry(0.03, 24), P.eyeM); d.position.set(k * 0.1, 0, 0.042); d.visible = false; face.add(d); return d; });
        P.mN = 24; const mg = new THREE.BufferGeometry(), mi = [];
        P.mPos = new Float32Array((P.mN + 1) * 2 * 3);
        for (i = 0; i < P.mN; i++) { const a0 = i * 2; mi.push(a0, a0 + 1, a0 + 2, a0 + 1, a0 + 3, a0 + 2); }
        mg.setAttribute('position', new THREE.BufferAttribute(P.mPos, 3)); mg.setIndex(mi);
        P.mouth = new THREE.Mesh(mg, P.eyeM); P.mouth.position.set(0, -0.08, 0.046); P.mouth.frustumCulled = false; P.mouth.visible = false; face.add(P.mouth); P.mo = 0;
        P.tip = pointLight(0xff8a2a, 0.8, 3); P.tip.position.set(0, 0.2, 0.7); g.add(P.tip);
        if (!o.headOnly) {
            P.jet = new THREE.Group();
            const j1 = new THREE.Mesh(new THREE.ConeGeometry(0.1, 0.32, 24, 1, true), new THREE.MeshBasicMaterial({ color: new THREE.Color(2.6, 1, 0.3), transparent: true, opacity: 0.75, blending: 2, depthWrite: false, side: 2 })),
                j2 = new THREE.Mesh(new THREE.ConeGeometry(0.05, 0.2, 16, 1, true), new THREE.MeshBasicMaterial({ color: new THREE.Color(3, 2.4, 1.4), transparent: true, opacity: 0.9, blending: 2, depthWrite: false, side: 2 }));
            j1.rotation.x = j2.rotation.x = 3.1416; j1.position.y = -0.16; j2.position.y = -0.1; P.jet.add(j1, j2); P.jet.position.set(0, -0.62, -0.04); g.add(P.jet);
            P.jl = pointLight(0xff6a2a, 1.1, 3); P.jl.position.set(0, -0.8, 0.2); g.add(P.jl);
            for (i = 0; i < 6; i++) { const q = spr(0xffa030, 0.08, 1); P.sp.push(q); g.add(q); }
            P.beam = new THREE.Group(); P.beam.position.set(0, -0.03, 0.22);
            const bg = new THREE.CylinderGeometry(0.09, 0.003, 1, 24, 1, true); bg.translate(0, 0.5, 0); bg.rotateX(1.5708);
            P.bm = new THREE.MeshBasicMaterial({ color: 0x7fb8ff, transparent: true, opacity: 0.3, blending: 2, depthWrite: false, side: 2 });
            P.bmesh = new THREE.Mesh(bg, P.bm); P.hit = spr(0xffffff, 0.3, 0.9); P.hit.material.color = P.bm.color;
            P.beam.add(P.bmesh, P.hit); P.beam.visible = false; g.add(P.beam);
        }
        g.scale.setScalar(0.5); P.al = null; P.fl = 1; P.th = 0; P.ph = 0; P.tt = 0; P.dr = -1; P.sh = 0; P.hp = 0; P.mw = 0.09; P.mx = 0; P.mt = 0;
        const AC = [[0xe00800, 0xa00008], [0xff1800, 0xf00000], [0xff6600, 0xff2000]];
        P.update = function (S, dt) {
            const t = S.t, s = S.state, al = S.alert, thk = s === 'thinking';
            let ex = 1, ey = 1, ox = 0, oy = 0;
            P.tt = thk ? P.tt + dt : 0; P.dr += ((thk && Math.floor(P.tt / 3) % 2 ? 1 : -1) - P.dr) * 0.06;
            if (s === 'listening') { ex = 1.45; ey = 1.7; }
            else if (thk) { ox = P.dr * (0.035 + 0.035 * Math.sin(t * 0.9)); oy = 0.045 + 0.008 * Math.sin(t * 0.6); ey = 0.95; }
            else if (s === 'disconnected') { ex = 1.2; ey = 0.2; oy = -0.015; }
            if (t % 4.2 > 4.1 && s !== 'disconnected') ey *= 0.1;
            P.eyes.children.forEach((e) => { e.scale.x += (ex - e.scale.x) * 0.2; e.scale.y += (ey - e.scale.y) * 0.35; });
            P.eyes.position.x += (ox - P.eyes.position.x) * 0.25; P.eyes.position.y += (oy - P.eyes.position.y) * 0.12;
            P.sh += ((S.shape || 0) - P.sh) * 0.3;
            const spk = s === 'speaking';
            P.mouth.visible = spk || thk;
            if (P.mouth.visible) {
                P.mo += ((spk ? S.amp : 0) - P.mo) * 0.6;
                P.mw += ((thk ? 0.045 : 0.09 * (1 - 0.4 * P.sh)) - P.mw) * 0.2;
                P.mx += ((thk ? P.dr * 0.03 : 0) - P.mx) * 0.1;
                P.mt += ((thk ? P.dr : 0) - P.mt) * 0.1;
                const mOpen = 0.01 + P.mo * 0.09, mp = P.mPos;
                for (let mj = 0; mj <= P.mN; mj++) {
                    const u = (mj / P.mN) * 2 - 1,
                        env = Math.pow(Math.max(0, 1 - u * u), 0.7),
                        sm = 0.012 * u * u * (1 - P.th) - P.th * 0.018 * P.mt * u,
                        x = u * P.mw + P.mx,
                        top = sm + 0.003 + mOpen * 0.45 * env,
                        bot = sm - 0.003 - mOpen * 0.55 * env;
                    mp[mj * 6] = x; mp[mj * 6 + 1] = top; mp[mj * 6 + 2] = 0;
                    mp[mj * 6 + 3] = x; mp[mj * 6 + 4] = bot; mp[mj * 6 + 5] = 0;
                }
                P.mouth.geometry.attributes.position.needsUpdate = true;
            }
            const cn = s === 'connecting';
            P.fl += ((cn ? 0 : 1) - P.fl) * 0.1; P.eyes.visible = !cn;
            P.dots.forEach((d, i) => { const k = 0.5 + 0.5 * Math.sin(t * 6 - i * 1.2); d.visible = cn; d.scale.setScalar(0.55 + 0.6 * k); d.position.y = 0.015 * (k - 0.5); });
            P.th += ((thk ? 1 : 0) - P.th) * 0.08; if (!thk && P.th < 0.003) P.th = 0;
            P.ph += dt * (1 + P.th * 3);
            const pp = P.ph, fa = 1 + P.th * 2.5;
            P.L.forEach((l, i) => { l.scale.set(1 + 0.004 * fa * Math.sin(pp * 5 + i), 1 + (0.01 * Math.sin(pp * (4 + i) + i) + 0.005 * Math.sin(pp * 9 + i)) * fa, 1); l.rotation.z = Math.sin(pp * (2.5 + i * 0.5) + i) * 0.008 * fa; });
            P.aura.material.opacity = 0.3 + (0.02 + 0.05 * P.th) * Math.sin(pp * 3); P.tip.intensity = (0.8 + (0.05 + 0.2 * P.th) * Math.sin(pp * 12)) * LIGHT_SCALE;
            if (P.jet) {
                const q = 0.9 + 0.25 * Math.sin(t * 37) + 0.1 * Math.sin(t * 61);
                P.jet.scale.set(0.95 + 0.08 * Math.sin(t * 45), q * P.fl, 0.95); P.jl.intensity = 1.1 * q * P.fl * LIGHT_SCALE;
                P.sp.forEach((p, i) => { const k = (t * 0.9 + i / 6) % 1, z = 0.09 * (1 - k) + 0.015; p.position.set(Math.sin(i * 2.7 + t * 2) * 0.1 * (1 + k), -0.78 - k * 0.6, -0.05); p.scale.set(z, z, 1); p.material.opacity = (1 - k) * P.fl; });
                P.beam.visible = s === 'scanning';
                if (P.beam.visible) { P.bmesh.scale.z = S.beamLen; P.hit.position.z = S.beamLen; P.bm.color.copy(S.accent); P.bm.opacity = 0.26 + 0.1 * Math.sin(t * 20); P.beam.rotation.y = Math.sin(t * 6) * 0.1; }
            }
            if (P.al !== al) {
                P.al = al; const c = al ? 0xff2a2a : ORG;
                P.cols.forEach((m, i) => { const c2 = AC[i][al ? 1 : 0]; m.color.setHex(c2); m.emissive.setHex(c2); });
                P.eyeM.color.set(al ? 0xff3030 : 0xffb060).multiplyScalar(al ? 3 : 1.6); P.tip.color.setHex(c); if (P.jl) P.jl.color.setHex(c);
            }
        };
        return P;
    }

    function Ember(o) {
        const me = this;
        me.scene = o.scene; me.bus = o.bus; me.host = o.host || document.documentElement;
        me.S = { state: 'idle', amp: 0, accent: new THREE.Color(0x7fb8ff), t: 0, beamLen: 2, alert: false };
        me.root = new THREE.Group(); me.inst = build({}); me.root.add(me.inst.g); me.scene.add(me.root);
        me.pos = me.root.position; me.vel = new THREE.Vector3(); me.tw = null; me.target = null; me.docked = null;
        me.bus.on('agent:state', (s) => { me.S.state = s; });
        me.bus.on('agent:amplitude', (a) => { me.S.amp = a; });
        me.bus.on('verdict:update', (v) => { me.S.alert = v >= 85; });
        me.bus.on('category:select', () => { requestAnimationFrame(() => me.accent()); });
        me.accent();
    }
    Ember.prototype.accent = function () { this.S.accent.set(getComputedStyle(this.host).getPropertyValue('--accent').trim() || '#7fb8ff'); };
    Ember.prototype.flyTo = function (p, ms) { const me = this; return new Promise((res) => { me.tw = { a: me.pos.clone(), b: p.clone(), t: 0, ms: ms || 1500, res }; }); };
    Ember.prototype.lookAt = function (t) { this.target = t || null; };
    Ember.prototype.scan = function (ts, ms) {
        const me = this, prev = me.S.state === 'scanning' ? 'idle' : me.S.state, per = ms / ts.length; let i = 0;
        me.bus.emit('scan:start', { count: ts.length }); me.S.state = 'scanning';
        return new Promise((res) => { (function nx() { if (i >= ts.length) { me.S.state = prev; me.target = null; me.bus.emit('scan:done'); res(); return; } me.target = ts[i++]; setTimeout(nx, per); })(); });
    };
    Ember.prototype.dock = function (el) {
        const me = this; if (me.docked) return;
        const w = el.clientWidth, h = el.clientHeight, r = new THREE.WebGLRenderer({ antialias: true, alpha: true });
        r.setPixelRatio(Math.min(devicePixelRatio, 2)); r.setSize(w, h); r.toneMapping = THREE.ACESFilmicToneMapping; el.appendChild(r.domElement);
        const s = new THREE.Scene(); s.environment = makeEnv(r);
        const c = new THREE.PerspectiveCamera(32, w / h, 0.05, 10); c.position.set(0, 0.02, 1.05);
        const hd = build({ headOnly: true }); s.add(hd.g);
        const L = pointLight(0xff6a2a, 2, 5); L.position.set(0, -0.3, 0.6); s.add(L, ambientLight(0x223344, 0.6));
        me.docked = { r, s, c, h: hd }; me.root.visible = false; me.bus.emit('ember:dock', true);
    };
    Ember.prototype.undock = function () { const d = this.docked; if (!d) return; d.r.domElement.remove(); d.r.dispose(); this.docked = null; this.root.visible = true; this.bus.emit('ember:dock', false); };
    Ember.prototype.tick = function (dt) {
        const me = this, S = me.S; S.t += dt;
        if (me.docked) { const d = me.docked; d.h.g.rotation.y = Math.sin(S.t * 0.45) * 0.55; d.h.g.position.y = Math.sin(S.t * 1.7) * 0.012; d.h.update(S, dt); d.r.render(d.s, d.c); return; }
        if (me.tw) {
            const w = me.tw; w.t += dt * 1000; const k = Math.min(1, w.t / w.ms), e = k < 0.5 ? 2 * k * k : 1 - Math.pow(-2 * k + 2, 2) / 2;
            V.lerpVectors(w.a, w.b, e); me.vel.copy(V).sub(me.pos).divideScalar(Math.max(dt, 1e-3)); me.pos.copy(V); if (k >= 1) { me.tw = null; w.res(); }
        } else { if (me.lp) V.copy(me.pos).sub(me.lp).divideScalar(Math.max(dt, 1e-3)); else V.set(0, 0, 0); me.vel.lerp(V, 0.12); }
        if (!me.lp) me.lp = new THREE.Vector3(); me.lp.copy(me.pos);
        const tp = me.target ? (me.target.isObject3D ? me.target.getWorldPosition(new THREE.Vector3()) : me.target) : null;
        let dir = null;
        if (tp) { dir = tp.clone().sub(me.pos); S.beamLen = Math.max(0.3, dir.length()); } else if (me.vel.length() > 0.08) dir = me.vel.clone();
        if (dir && dir.lengthSq() > 1e-6) { TMP.position.copy(me.pos); TMP.lookAt(me.pos.clone().add(dir)); me.root.quaternion.slerp(TMP.quaternion, 1 - Math.exp(-6 * dt)); }
        const nk = (S.t % 2.4) / 1.2, nod = S.state === 'listening' && nk < 1 ? Math.sin(nk * 12.566) * 0.3 : 0;
        me.inst.g.rotation.x += (Math.min(me.vel.length(), 6) * 0.05 + nod - me.inst.g.rotation.x) * 0.25;
        me.inst.g.rotation.z += (Math.max(-0.45, Math.min(0.45, -me.vel.x * 0.12)) + -me.inst.dr * me.inst.th * 0.17 - me.inst.g.rotation.z) * 0.08;
        me.inst.g.position.y = Math.sin(S.t * 1.7) * 0.03 * me.inst.fl; me.inst.update(S, dt);
    };
    Ember.makeEnv = makeEnv;
    return Ember;
})();

export const makeEnv = Ember.makeEnv;
export { Ember };
export default Ember;
