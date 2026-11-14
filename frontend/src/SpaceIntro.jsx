import React, { useEffect, useRef, useState } from 'react';
import * as THREE from 'three';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import './SpaceIntro.css';

import earthDayUrl from './assets/earth_day.webp';
import earthNightUrl from './assets/earth_night.webp';
import moonUrl from './assets/moon.webp';
import marsUrl from './assets/mars.webp';
import orionUrl from './assets/orion.glb';
import artemisUrl from './assets/artemis_ii_web.glb';

import { DRACOLoader } from 'three/examples/jsm/loaders/DRACOLoader.js';
import { MeshoptDecoder } from 'three/examples/jsm/libs/meshopt_decoder.module.js';

/* ===== ENTRANCE TIMING (seconds, counted from mount) ===== */
export const TIMING = {
    starsFade: 0.0,
    planetsStart: 0,       // delay before the first planet starts sliding in
    planetsStagger: 0.15,  // extra delay between one planet and the next (Earth, Moon, Mars)
    planetsDuration: 0.0,  // how long each planet takes to arrive
    shipStart: 0.0,       // delay before the spacecraft starts flying in
    shipDuration: 1.5,     // how long the spacecraft takes to arrive
    readyText: 2.9,        // when the top-left label changes to "READY"
};

// CDN fallbacks (used if the local asset fails to load)
const CD = 'https://cdn.jsdelivr.net/gh/openbrian/artemis-viewer@main/public/';
const TX = 'https://cdn.jsdelivr.net/gh/jeromeetienne/threex.planets@master/images/';

const SRGB = THREE.SRGBColorSpace;
const V = THREE.Vector3;
const ease = (k) => 1 - Math.pow(1 - k, 3);
const cl = (k) => Math.max(0, Math.min(1, k));

/* ---------- shared asset cache for instant readiness on call ---------- */
export const spaceAssetCache = {
    textures: new Map(),
    gltfs: new Map(),
    loadingPromises: new Map(),
};

export function preloadSpaceAssets() {
    const TL = new THREE.TextureLoader();
    const GL = new GLTFLoader()
        .setDRACOLoader(new DRACOLoader().setDecoderPath('/draco/'))
        .setMeshoptDecoder(MeshoptDecoder);

    const loadTex = (url, isSRGB = false) => {
        if (!url || spaceAssetCache.textures.has(url) || spaceAssetCache.loadingPromises.has(url)) return;
        const p = new Promise((resolve) => {
            TL.load(
                url,
                (t) => {
                    t.anisotropy = 8;
                    t.wrapS = THREE.RepeatWrapping;
                    if (isSRGB) t.colorSpace = SRGB;
                    spaceAssetCache.textures.set(url, t);
                    resolve(t);
                },
                undefined,
                () => resolve(null)
            );
        });
        spaceAssetCache.loadingPromises.set(url, p);
    };

    const loadGltf = (url) => {
        if (!url || spaceAssetCache.gltfs.has(url) || spaceAssetCache.loadingPromises.has(url)) return;
        const p = new Promise((resolve) => {
            GL.load(
                url,
                (g) => { spaceAssetCache.gltfs.set(url, g); resolve(g); },
                undefined,
                (e) => {
                    console.warn('[preload] gltf failed', url, e);
                    spaceAssetCache.loadingPromises.delete(url);   // let the real loader retry
                    resolve(null);
                }
            );
        });
        spaceAssetCache.loadingPromises.set(url, p);
    };

    loadTex(earthDayUrl, false);
    loadTex(earthNightUrl, false);
    loadTex(moonUrl, true);
    loadTex(marsUrl, true);
    // orion.glb is only the fallback ship: OpenningScene fetches it if the Artemis model fails
    loadGltf(artemisUrl);
}

// Start preloading immediately on import so SpaceIntro is ready when called
preloadSpaceAssets();

/* ===================== helpers ===================== */
function mk(w, h, fn, srgb = true) {
    const c = document.createElement('canvas');
    c.width = w; c.height = h;
    fn(c.getContext('2d'), w, h);
    const t = new THREE.CanvasTexture(c);
    t.wrapS = THREE.RepeatWrapping;
    if (srgb) t.colorSpace = SRGB;
    return t;
}

function blobs(g, w, h, cols, n, r) {
    for (let i = 0; i < n; i++) {
        g.fillStyle = cols[i % cols.length];
        g.beginPath();
        g.ellipse(Math.random() * w, Math.random() * h, Math.random() * r + 4, Math.random() * r * 0.6 + 3, Math.random() * 3, 0, 6.3);
        g.fill();
    }
}

function bxOf(arr) {
    const q = new THREE.Box3();
    arr.forEach((o) => q.expandByObject(o));
    return q;
}

function disposeTree(root) {
    root.traverse((o) => {
        o.geometry?.dispose();
        [].concat(o.material || []).forEach((m) => {
            for (const k in m) {
                const v = m[k];
                if (v && v.isTexture) v.dispose();
            }
            m.dispose?.();
        });
    });
}

/* ===================== scene ===================== */
function createSpaceIntro(container, hooks) {
    let disposed = false;
    let raf = 0;
    const timers = [];
    const cleanups = [];
    const size = () => ({
        w: container.clientWidth || window.innerWidth,
        h: container.clientHeight || window.innerHeight,
    });

    /* ---------- renderer / scene / camera ---------- */
    const R = new THREE.WebGLRenderer({ antialias: true });
    R.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    R.toneMapping = THREE.ACESFilmicToneMapping;
    R.toneMappingExposure = 0.75;
    R.outputColorSpace = SRGB;
    container.appendChild(R.domElement);

    /* ---------- Camera Position & Look-At Target ---------- */
    const CAM_X = 0;
    const CAM_Y = 0;
    const CAM_Z = 9.5;

    const LOOK_X = 0;
    const LOOK_Y = 0;
    const LOOK_Z = 0;

    const CAM_POS = new V(CAM_X, CAM_Y, CAM_Z);
    const LOOK_TARGET = new V(LOOK_X, LOOK_Y, LOOK_Z);

    const S = new THREE.Scene();
    const C = new THREE.PerspectiveCamera(40, 1, 0.1, 400);
    C.position.copy(CAM_POS);
    C.lookAt(LOOK_TARGET);
    S.add(C);

    function resize() {
        const { w, h } = size();
        R.setSize(w, h);
        C.aspect = w / h;
        C.updateProjectionMatrix();
    }
    resize();

    /* ---------- loaders (cached / instant) ---------- */
    const TL = new THREE.TextureLoader();
    function lt(urls, ok) {
        for (const u of urls) {
            if (spaceAssetCache.textures.has(u)) {
                ok(spaceAssetCache.textures.get(u));
                return;
            }
        }
        for (const u of urls) {
            if (spaceAssetCache.loadingPromises.has(u)) {
                spaceAssetCache.loadingPromises.get(u).then((t) => {
                    if (disposed) return;
                    if (t) ok(t);
                    else if (urls.length > 1) lt(urls.slice(1), ok);
                });
                return;
            }
        }
        TL.load(
            urls[0],
            (t) => {
                if (disposed) { t.dispose(); return; }
                t.anisotropy = 8;
                spaceAssetCache.textures.set(urls[0], t);
                ok(t);
            },
            undefined,
            () => { if (urls.length > 1) lt(urls.slice(1), ok); }
        );
    }
    function lg(urls, ok) {
        for (const u of urls) {
            if (spaceAssetCache.gltfs.has(u)) {
                const g = spaceAssetCache.gltfs.get(u);
                ok({ ...g, scene: g.scene.clone(true) });
                return;
            }
        }
        for (const u of urls) {
            if (spaceAssetCache.loadingPromises.has(u)) {
                spaceAssetCache.loadingPromises.get(u).then((g) => {
                    if (disposed) return;
                    if (g) ok({ ...g, scene: g.scene.clone(true) });
                    else if (urls.length > 1) lg(urls.slice(1), ok);
                });
                return;
            }
        }
        new GLTFLoader().load(
            urls[0],
            (g) => {
                if (disposed) return;
                spaceAssetCache.gltfs.set(urls[0], g);
                ok({ ...g, scene: g.scene.clone(true) });
            },
            undefined,
            () => { if (urls.length > 1) lg(urls.slice(1), ok); }
        );
    }

    /* ---------- glow sprite helper ---------- */
    const GT = mk(64, 64, (g) => {
        const r = g.createRadialGradient(32, 32, 0, 32, 32, 32);
        r.addColorStop(0, 'rgba(255,255,255,1)');
        r.addColorStop(0.3, 'rgba(255,255,255,.4)');
        r.addColorStop(1, 'rgba(255,255,255,0)');
        g.fillStyle = r;
        g.fillRect(0, 0, 64, 64);
    });
    function spr(col, sz, op) {
        const s = new THREE.Sprite(new THREE.SpriteMaterial({
            map: GT, color: col, blending: THREE.AdditiveBlending,
            transparent: true, depthWrite: false, opacity: op,
        }));
        s.scale.set(sz, sz, 1);
        return s;
    }

    /* ---------- environment + lights ---------- */
    (function envMap() {
        const s = new THREE.Scene();
        s.add(new THREE.Mesh(new THREE.SphereGeometry(10, 16, 16), new THREE.MeshBasicMaterial({ side: THREE.BackSide, color: 0x010308 })));
        const pl = (c, x, y, z, w, h) => {
            const m = new THREE.Mesh(new THREE.PlaneGeometry(w, h), new THREE.MeshBasicMaterial({ color: c, side: THREE.DoubleSide }));
            m.position.set(x, y, z); m.lookAt(0, 0, 0); s.add(m);
        };
        pl(new THREE.Color(1.8, 1.6, 1.4), -6, 5, 4, 6, 4);
        pl(new THREE.Color(0.12, 0.28, 0.75), 2, -6, 2, 10, 3);
        pl(new THREE.Color(0.15, 0.15, 0.2), 6, 1, -4, 3, 5);
        const pm = new THREE.PMREMGenerator(R);
        S.environment = pm.fromScene(s, 0.04).texture;
        pm.dispose();
        disposeTree(s);
    })();

    const SUN = new V(-6, 6, 5).normalize();
    const dl = new THREE.DirectionalLight(0xfff1dc, 1.7);
    dl.position.copy(SUN).multiplyScalar(20);
    S.add(dl, new THREE.AmbientLight(0x0a1426, 0.18));

    /* ---------- 3D starfield, 3 depth layers ---------- */
    const LAY = [];
    [[1800, -150, -120, 1.2], [1100, -100, -60, 1.7], [450, -55, -28, 2.5]].forEach((d) => {
        const p = [], c = [];
        const col = [[1, 1, 1], [0.7, 0.82, 1], [1, 0.88, 0.7]];
        for (let i = 0; i < d[0]; i++) {
            const z = d[1] + Math.random() * (d[2] - d[1]);
            const q = col[Math.floor(Math.random() * 3)];
            const b = 0.5 + Math.random() * 0.5;
            p.push((Math.random() - 0.5) * 2 * Math.abs(z) * 0.95, (Math.random() - 0.5) * 2 * Math.abs(z) * 0.55, z);
            c.push(q[0] * b, q[1] * b, q[2] * b);
        }
        const g = new THREE.BufferGeometry();
        g.setAttribute('position', new THREE.Float32BufferAttribute(p, 3));
        g.setAttribute('color', new THREE.Float32BufferAttribute(c, 3));
        const pt = new THREE.Points(g, new THREE.PointsMaterial({
            size: d[3], sizeAttenuation: false, map: GT, vertexColors: true,
            transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, opacity: 0,
        }));
        S.add(pt);
        LAY.push(pt);
    });

    /* ---------- planets ---------- */
    const PL = [];
    // The Earth shader samples raw texture values (no colour-space decode),
    // so its textures are intentionally left without an sRGB colorSpace.
    const U = {
        dayT: { value: mk(512, 256, (g, w, h) => { g.fillStyle = '#14508f'; g.fillRect(0, 0, w, h); blobs(g, w, h, ['#2f7a3a', '#6d8a45', '#a08a55'], 70, 38); }, false) },
        nightT: { value: mk(4, 4, (g) => { g.fillStyle = '#000'; g.fillRect(0, 0, 4, 4); }, false) },
        sun: { value: SUN },
        rot: { value: 0 },
    };
    const ER = 3.4;
    const E = new THREE.Group();
    const earth = new THREE.Mesh(new THREE.SphereGeometry(ER, 96, 64), new THREE.ShaderMaterial({
        uniforms: U,
        vertexShader: 'varying vec2 u;varying vec3 n;void main(){u=uv;n=normalize(mat3(modelMatrix)*normal);gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.);}',
        fragmentShader: 'uniform sampler2D dayT,nightT;uniform vec3 sun;uniform float rot;varying vec2 u;varying vec3 n;void main(){vec2 q=vec2(u.x+rot,u.y);float d=dot(normalize(n),sun);vec3 day=texture2D(dayT,q).rgb,ni=texture2D(nightT,q).rgb;float k=smoothstep(-.12,.18,d);vec3 c=mix(ni*vec3(1.5,1.1,.6)*1.6+day*.015,day*(max(d,0.)*1.1+.03),k);c+=vec3(.9,.45,.25)*smoothstep(0.,.25,.25-abs(d))*.1;gl_FragColor=vec4(c,1.);}',
    }));
    E.add(earth);

    function atmo(sc, side, mode) {
        return new THREE.Mesh(new THREE.SphereGeometry(ER * sc, 64, 48), new THREE.ShaderMaterial({
            transparent: true, side, depthWrite: false, blending: THREE.AdditiveBlending,
            uniforms: { sun: { value: SUN }, mode: { value: mode } },
            vertexShader: 'varying vec3 nv,nw;void main(){nv=normalize(normalMatrix*normal);nw=normalize(mat3(modelMatrix)*normal);gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.);}',
            fragmentShader: 'uniform vec3 sun;uniform float mode;varying vec3 nv,nw;void main(){float c=dot(nv,vec3(0.,0.,1.));float i=mode>0.?pow(clamp(-c/.5,0.,1.),2.2)*1.6:pow(1.-clamp(c,0.,1.),3.5)*1.1;float l=.3+.7*smoothstep(-.4,.6,dot(nw,sun));gl_FragColor=vec4(vec3(.25,.55,1.)*i*l,i*l);}',
        }));
    }
    E.add(atmo(1.14, THREE.FrontSide, 1), atmo(1.015, THREE.BackSide, -1));

    const moon = new THREE.Mesh(new THREE.SphereGeometry(0.6, 48, 32), new THREE.MeshStandardMaterial({
        roughness: 1, metalness: 0,
        map: mk(512, 256, (g, w, h) => { g.fillStyle = '#8d8b88'; g.fillRect(0, 0, w, h); blobs(g, w, h, ['#6f6d6a', '#a3a09b', '#5d5b59'], 120, 16); }),
    }));
    const mars = new THREE.Mesh(new THREE.SphereGeometry(1.3, 64, 48), new THREE.MeshStandardMaterial({
        roughness: 1, metalness: 0,
        map: mk(512, 256, (g, w, h) => {
            g.fillStyle = '#b4552f'; g.fillRect(0, 0, w, h);
            blobs(g, w, h, ['#8f3d22', '#c86a3c', '#6e3220'], 110, 30);
            g.fillStyle = '#f1e6dc'; g.fillRect(0, 0, w, 9); g.fillRect(0, h - 9, w, 9);
        }),
    }));

    [[E, -2.6, -0.6, -1], [moon, -1, 5.2, -9], [mars, 14, 2.6, -18]].forEach((d) => {
        d[0].userData.b = new V(d[1], d[2], d[3]);
        S.add(d[0]);
        PL.push(d[0]);
    });

    lt([earthDayUrl, CD + 'textures/earth.jpg'], (t) => { t.wrapS = THREE.RepeatWrapping; U.dayT.value = t; });
    lt([earthNightUrl, CD + 'textures/earth-night.jpg'], (t) => { t.wrapS = THREE.RepeatWrapping; U.nightT.value = t; });
    lt([moonUrl, CD + 'textures/moon.jpg'], (t) => { t.colorSpace = SRGB; moon.material.map = t; moon.material.needsUpdate = true; });
    lt([marsUrl, TX + 'marsmap1k.jpg'], (t) => { t.colorSpace = SRGB; mars.material.map = t; mars.material.needsUpdate = true; });

    /* ---------- sun (attached to the camera so it stays upper-left) ---------- */
    const sunPos = new V(-5.6, 3.1, -10);   // screen direction of the sun
    const SUNU = { time: { value: 0 } };
    const sunMesh = new THREE.Mesh(new THREE.PlaneGeometry(30, 30), new THREE.ShaderMaterial({   // 30 = total size incl. corona
        uniforms: SUNU, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
        vertexShader: 'varying vec2 v;void main(){v=uv;gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.);}',
        fragmentShader:
            'uniform float time;varying vec2 v;' +
            'float h(vec2 p){return fract(sin(dot(p,vec2(127.1,311.7)))*43758.5453);}' +
            'float n(vec2 p){vec2 i=floor(p),f=fract(p);f=f*f*(3.-2.*f);return mix(mix(h(i),h(i+vec2(1.,0.)),f.x),mix(h(i+vec2(0.,1.)),h(i+vec2(1.,1.)),f.x),f.y);}' +
            'float fbm(vec2 p){float a=.5,s=0.;for(int i=0;i<5;i++){s+=a*n(p);p*=2.03;a*=.5;}return s;}' +
            'void main(){vec2 q=v*2.-1.;float r=length(q),R=.16;' +
            'float disc=smoothstep(R,R-.008,r);float mu=sqrt(max(0.,1.-(r/R)*(r/R)));' +
            'float g=fbm(q/R*3.5+vec2(time*.04,0.));float g2=fbm(q/R*9.-time*.03);' +
            'vec3 hot=vec3(1.,.97,.85),mid=vec3(1.,.62,.16);' +
            'vec3 sc=mix(mid,hot,pow(mu,.6)+(g-.5)*.5)*(.9+.35*g2)*(.6+.55*pow(mu,.45))*1.7;' +
            'float d=max(r-R,0.);float ang=atan(q.y,q.x);' +
            'float ray=.65+.35*sin(ang*7.+fbm(vec2(ang*2.,time*.05))*8.);' +
            'float gl=(exp(-d*16.)*.95+exp(-d*5.)*.28)*(.75+.25*ray)+exp(-d*1.8)*.05;' +
            'vec3 cor=mix(vec3(1.,.85,.5),vec3(1.,.5,.15),clamp(d*4.,0.,1.))*gl;' +
            'vec3 c=mix(cor,sc,disc)*smoothstep(1.,.55,r);gl_FragColor=vec4(c,1.);}',
    }));
    sunMesh.position.copy(sunPos).multiplyScalar(6);   // pushed back to depth 60 so planets pass in front
    C.add(sunMesh);
    const stk = spr(0x9fc4ff, 1, 0.22);
    stk.scale.set(15, 0.35, 1);
    stk.material.depthTest = false;
    stk.position.copy(sunPos);
    C.add(stk);

    /* ---------- spacecraft (real Orion model, procedural fallback) ---------- */
    const CR = new THREE.Group(), CW = new THREE.Group(), P = {};
    CR.add(CW);
    CR.rotation.set(0.25, 0, -1.2);
    CR.position.set(-15, 0.25, 2);
    S.add(CR);

    function fb() {
        const g = new THREE.Group();
        const gold = new THREE.MeshStandardMaterial({ color: 0xb08a4a, metalness: 0.9, roughness: 0.35 });
        const wh = new THREE.MeshStandardMaterial({ color: 0xcfd3da, metalness: 0.5, roughness: 0.4 });
        const dk = new THREE.MeshStandardMaterial({ color: 0x2a2c30, metalness: 0.8, roughness: 0.4 });
        const pn = new THREE.MeshStandardMaterial({ color: 0x14306a, metalness: 0.7, roughness: 0.3, emissive: 0x061430 });
        const cm = new THREE.Mesh(new THREE.CylinderGeometry(0.14, 0.5, 0.62, 48), wh); cm.position.y = 0.52;
        const sm = new THREE.Mesh(new THREE.CylinderGeometry(0.5, 0.5, 0.6, 48), gold); sm.position.y = -0.09;
        const nz = new THREE.Mesh(new THREE.CylinderGeometry(0.14, 0.26, 0.3, 32, 1, true), dk); nz.position.y = -0.54;
        g.add(cm, sm, nz);
        [-1, 1].forEach((s) => {
            for (let i = 0; i < 4; i++) {
                const p = new THREE.Mesh(new THREE.BoxGeometry(0.3, 0.014, 0.9), pn);
                p.position.set(s * (0.75 + i * 0.32), -0.05, 0);
                g.add(p);
            }
        });
        return { g, cm: [cm], sm: [sm, nz] };
    }

    function finish(m, cm, sm) {
        const w = new THREE.Group();
        w.add(m);
        const b = new THREE.Box3().setFromObject(w), sz = b.getSize(new V());
        m.position.sub(b.getCenter(new V()));
        const cb = bxOf(cm.length ? cm : [m]), sb = bxOf(sm.length ? sm : [m]);
        const cc = cb.getCenter(new V()), cs = cb.getSize(new V()), rad = Math.max(cs.x, cs.z) / 2;
        const hat = spr(0xbfe8ff, rad * 0.9, 1);
        hat.material.visible = false;
        hat.position.set(cc.x, cc.y - cs.y * 0.1, cc.z + rad * 0.82);
        w.add(hat);
        const eng = new THREE.Group();
        const cone = new THREE.Mesh(new THREE.ConeGeometry(rad * 0.28, rad * 1.4, 24, 1, true), new THREE.MeshBasicMaterial({ color: new THREE.Color(2.4, 1.1, 0.35), transparent: true, opacity: 0.7, blending: THREE.AdditiveBlending, depthWrite: false, side: THREE.DoubleSide }));
        const core = new THREE.Mesh(new THREE.SphereGeometry(rad * 0.45, 24, 16), new THREE.MeshBasicMaterial({ color: new THREE.Color(3, 1.7, 0.7), transparent: true, opacity: 0, blending: THREE.AdditiveBlending, depthWrite: false }));
        const gl = spr(0xff7a30, rad * 1.2, 0.9);
        gl.visible = false;
        cone.visible = false;
        cone.rotation.x = Math.PI; cone.position.y = -rad * 0.7;
        core.position.y = -rad * 0.5;
        eng.add(cone, core, gl);
        P.cone = cone; P.core = core;
        eng.position.y = sb.min.y;
        w.add(eng);
        w.scale.setScalar(2.6 / Math.max(sz.x, sz.y, sz.z));
        if (P.cur) { CW.remove(P.cur); disposeTree(P.cur); }
        P.cur = w; P.eng = eng; P.hat = hat;
        CW.add(w);
    }

    const f0 = fb();
    finish(f0.g, f0.cm, f0.sm);

    // lg([orionUrl, CD + 'models/orion.glb'], (g) => {
    lg([artemisUrl, CD + 'models/artemis_ii_web.glb'], (g) => {
        const m = g.scene;
        const N = (re, no) => {
            const r = [];
            m.traverse((o) => { if (o.isMesh && re.test(o.name) && !(no && no.test(o.name))) r.push(o); });
            return r;
        };
        const cmL = N(/CM/i, /face/i), smL = N(/SM/i);
        let dir = new V(-1, 0, 0);
        m.updateMatrixWorld(true);
        if (cmL.length && smL.length) {
            const d = bxOf(cmL).getCenter(new V()).sub(bxOf(smL).getCenter(new V()));
            if (d.length() > 1e-4) dir = d.normalize();
        }
        m.quaternion.setFromUnitVectors(dir, new V(0, 1, 0));
        m.updateMatrixWorld(true);
        m.traverse((o) => {
            if (o.isMesh) {
                o.frustumCulled = false;
                [].concat(o.material).forEach((q) => { q.envMapIntensity = 1.1; q.side = THREE.DoubleSide; });
            }
        });
        finish(m, cmL, smL);
    });

    /* ---------- flow state ---------- */
    let mode = 'S1';   // S1 = idle space, T1 = launch + zoom, END = faded to black
    let t0 = 0;
    const STN = 260;
    const stp = new Float32Array(STN * 6);
    const sto = [];
    const stg = new THREE.BufferGeometry();
    stg.setAttribute('position', new THREE.BufferAttribute(stp, 3));
    for (let i = 0; i < STN; i++) {
        const r = 1.2 + Math.random() * 5, a = Math.random() * 6.28;
        sto.push([Math.random() * 30 - 12, r * Math.cos(a), r * Math.sin(a)]);
    }
    const stm = new THREE.LineSegments(stg, new THREE.LineBasicMaterial({ color: 0xbfd8ff, transparent: true, opacity: 0, blending: THREE.AdditiveBlending, depthWrite: false }));
    stm.frustumCulled = false;
    S.add(stm);
    const CAM0 = CAM_POS.clone(), hp = new V();
    const LOOK0 = LOOK_TARGET.clone();

    function updT1(tt, dt) {
        const s = ease(cl(tt / 1.2)), spd = cl((tt - 0.2) / 1.4);
        const nose = new V(0, 1, 0).applyQuaternion(CR.quaternion).normalize();
        if (P.core) {
            P.core.material.opacity = 0.95 * s;
            P.core.scale.set(0.35 + 0.65 * s, 1.8 - 0.8 * s, 0.35 + 0.65 * s);
            P.cone.material.opacity = 0.7 * (1 - s) + 0.25;
            P.eng.scale.set(1, 0.7 + 2.2 * s + 0.12 * Math.sin(tt * 43), 1);
        }
        CR.position.addScaledVector(nose, dt * spd * spd * 5);
        const s1 = new V().crossVectors(nose, new V(0, 0, 1)).normalize();
        const s2 = new V().crossVectors(nose, s1);
        for (let i = 0; i < STN; i++) {
            const o = sto[i];
            o[0] -= dt * (8 + 60 * spd);
            if (o[0] < -14) o[0] = 16 + Math.random() * 4;
            const p = CR.position.clone().addScaledVector(nose, o[0]).addScaledVector(s1, o[1]).addScaledVector(s2, o[2]);
            const q = p.clone().addScaledVector(nose, 0.2 + spd * 3.5);
            stp.set([p.x, p.y, p.z, q.x, q.y, q.z], i * 6);
        }
        stg.attributes.position.needsUpdate = true;
        stm.material.opacity = 0.75 * spd;

        P.hat.getWorldPosition(hp);
        const kd = ease(cl((tt - 0.3) / 1.7));
        const end = hp.clone().sub(hp.clone().sub(CAM0).normalize().multiplyScalar(0.55));
        C.position.lerpVectors(CAM0, end, kd);
        C.lookAt(new V().lerpVectors(LOOK0, hp, kd));

        // screen goes fully black between 1.8 s and 2.15 s of the launch
        hooks.onFade(cl((tt - 1.8) / 0.35));
        if (tt >= 2.15 && mode === 'T1') endIntro();
    }

    function endIntro() {
        mode = 'END';
        hooks.onFade(1);
        cancelAnimationFrame(raf);   // stop rendering once faded to black
        /* >>> The intro ends here (screen is fully black). Next scene starts via onLaunchDone. <<< */
        hooks.onLaunchDone?.();
    }

    function startLaunch() {
        if (mode !== 'S1') return;
        mode = 'T1';
        t0 = performance.now();
        C.position.copy(CAM0);
        hooks.onLaunching();
    }

    /* ---------- S1 idle / entrance ---------- */
    window.addEventListener('resize', resize);
    cleanups.push(() => {
        window.removeEventListener('resize', resize);
    });

    function updS1(t, launched) {
        PL.forEach((p, i) => {
            const k = ease(cl((t - TIMING.planetsStart - i * TIMING.planetsStagger) / TIMING.planetsDuration));
            const b = p.userData.b;
            p.position.set(
                b.x + Math.sin(t * 0.1 + i) * 0.18,
                b.y + 26 * (1 - k) + Math.cos(t * 0.13 + i * 2) * 0.12,   // was: b.y + Math.cos(...)
                b.z
            );
            if (i) p.rotation.y = t * (0.02 + i * 0.01);
        });
        const kc = ease(cl((t - TIMING.shipStart) / TIMING.shipDuration));
        if (!launched) CR.position.set(-15 + 17 * kc, 0.25 + Math.sin(t * 0.8) * 0.06, 2);
        CW.rotation.set(Math.sin(t * 0.37) * 0.1, 0.5 + Math.sin(t * 0.5) * 0.35, 0);
        if (P.eng && !launched) {
            P.eng.scale.set(1 + 0.1 * Math.sin(t * 31), 0.7 + (1 - kc) * 2.2 + 0.12 * Math.sin(t * 43), 1 + 0.1 * Math.sin(t * 37));
        }
        if (P.hat) P.hat.material.opacity = 0.55 + 0.45 * Math.sin(t * 2.2);
        U.rot.value = t * 0.004;
        SUNU.time.value = t;
    }

    /* ---------- UI timers ---------- */
    timers.push(setTimeout(() => hooks.onHud(true), 50));
    timers.push(setTimeout(() => hooks.onLabel('READY'), TIMING.readyText * 1000));

    /* ---------- main loop ---------- */
    const T0 = performance.now();
    let lastN = performance.now();
    function tick(now) {
        raf = requestAnimationFrame(tick);
        if (mode === 'END') return;
        const dt = Math.min((now - lastN) / 1000, 0.05);
        lastN = now;
        const t = (now - T0) / 1000, tt = (now - t0) / 1000;
        updS1(t, mode !== 'S1');
        if (mode === 'S1') {
            C.position.copy(CAM_POS);
            C.lookAt(LOOK_TARGET);
            const starK = cl(t / TIMING.starsFade);
            LAY.forEach((l, k) => {
                l.material.opacity = starK;   // NEW
                l.rotation.z = t * 0.0015 * (k + 1);
            });
        }
        if (mode === 'T1') updT1(tt, dt);
        R.render(S, C);
    }
    raf = requestAnimationFrame(tick);

    return {
        startLaunch,
        dispose() {
            disposed = true;
            cancelAnimationFrame(raf);
            timers.forEach(clearTimeout);
            cleanups.forEach((f) => f());
            disposeTree(S);
            S.environment?.dispose();
            GT.dispose();
            R.dispose();
            R.forceContextLoss();
            R.domElement.remove();
        },
    };
}

/* ===================== React component ===================== */
export default function SpaceIntro({ onLaunchStart, onLaunchDone, className = '', style }) {
    const mountRef = useRef(null);
    const rootRef = useRef(null);
    const fadeRef = useRef(null);
    const apiRef = useRef(null);
    const cbRef = useRef({});
    cbRef.current = { onLaunchStart, onLaunchDone };

    const [hudOn, setHudOn] = useState(false);
    const [launching, setLaunching] = useState(false);
    const [label, setLabel] = useState('ENTERING ORBIT');

    useEffect(() => {
        const api = createSpaceIntro(mountRef.current, {
            onHud: (v) => setHudOn(v),
            onLabel: (s) => setLabel(s),
            onFade: (v) => { if (fadeRef.current) fadeRef.current.style.opacity = v; },
            onLaunching: () => {
                setLaunching(true);   // quick 0.4 s fade-out for the title + button
                setHudOn(false);
                setLabel('LAUNCH');
                cbRef.current.onLaunchStart?.();
            },
            onLaunchDone: () => cbRef.current.onLaunchDone?.(),
        });
        apiRef.current = api;
        return () => {
            api.dispose();
            apiRef.current = null;
        };
    }, []);

    return (
        <div className={`space-intro ${className}`} style={style} ref={rootRef}>
            <div className="si-mount" ref={mountRef} />
            <div className="si-fade" ref={fadeRef} />

            <div className="si-pnl si-log">
                <span>S1 &middot; SPACE</span> &middot; <span>{label}</span>
            </div>

            <div className={`si-hud${hudOn ? ' on' : ''}${launching ? ' fast' : ''}`}>
                <h1 className="si-title">ARTEMIS<small>ORION &middot; LUNAR MISSION</small></h1>
                <div className="si-lw">
                    <svg className="si-ring" viewBox="0 0 264 76" preserveAspectRatio="none">
                        <polygon points="18,1 246,1 263,18 263,58 246,75 18,75 1,58 1,18" />
                    </svg>
                    <svg className="si-ring b" viewBox="0 0 264 76" preserveAspectRatio="none">
                        <polygon points="18,1 246,1 263,18 263,58 246,75 18,75 1,58 1,18" />
                    </svg>
                    <button type="button" className="si-go" onClick={() => apiRef.current?.startLaunch()}>
                        Launch
                    </button>
                </div>
            </div>
        </div>
    );
}
