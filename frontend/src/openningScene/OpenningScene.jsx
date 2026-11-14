import React, { useEffect, useRef, useState, useCallback } from 'react';
import * as THREE from 'three';
import './OpenningScene.css';

import earthDayUrl from '../assets/earth_day.webp';
import earthNightUrl from '../assets/earth_night.webp';
import moonUrl from '../assets/moon.webp';
import marsUrl from '../assets/mars.webp';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { DRACOLoader } from 'three/examples/jsm/loaders/DRACOLoader.js';
import artemisIIUrl from '../assets/artemis_ii_web.glb';
import orionUrl from '../assets/orion.glb';
import { spaceAssetCache } from '../SpaceIntro.jsx';
import { useNavigate } from 'react-router-dom';
import { MeshoptDecoder } from 'three/examples/jsm/libs/meshopt_decoder.module.js';

/* ===================== CONFIG ===================== */
export const CONFIG = {
    T: {
        planetsDrop: 0.8,   // seconds for the planets to drop in
        btnReady: -0.5,      // seconds before the Start Mission button appears
    },
    maxDpr: 2,
    bg: 0x000000,
    btn: { down: 70 },   // pixels to push the Launch button lower (0 = original position)
};

/* ===================== helpers ===================== */
const clamp = (x, a = 0, b = 1) => Math.min(b, Math.max(a, x));

/* ===================== space scene ===================== */
const SPACE_T = {
    starsFade: 0.0,
    planetsStart: 0.2,
    planetsStagger: 0.3,
    planetsDuration: CONFIG.T.planetsDrop,
    shipStart: 0.8,
    shipDuration: 2.0,
    hudAt: 0.1,
    readyAt: CONFIG.T.btnReady,
};
const easeOut3 = (k) => 1 - Math.pow(1 - k, 3);

function ssTex(w, h, fn, srgb = true) {
    const c = document.createElement('canvas');
    c.width = w; c.height = h;
    fn(c.getContext('2d'), w, h);
    const t = new THREE.CanvasTexture(c);
    t.wrapS = THREE.RepeatWrapping;
    if (srgb) t.colorSpace = THREE.SRGBColorSpace;
    return t;
}
function ssBlobs(g, w, h, cols, n, r) {
    for (let i = 0; i < n; i++) {
        g.fillStyle = cols[i % cols.length];
        g.beginPath();
        g.ellipse(Math.random() * w, Math.random() * h, Math.random() * r + 4, Math.random() * r * 0.6 + 3, Math.random() * 3, 0, 6.3);
        g.fill();
    }
}
function ssGlow() {
    const c = document.createElement('canvas'); c.width = c.height = 64;
    const g = c.getContext('2d');
    const r = g.createRadialGradient(32, 32, 0, 32, 32, 32);
    r.addColorStop(0, 'rgba(255,255,255,1)');
    r.addColorStop(0.3, 'rgba(255,255,255,.4)');
    r.addColorStop(1, 'rgba(255,255,255,0)');
    g.fillStyle = r; g.fillRect(0, 0, 64, 64);
    return new THREE.CanvasTexture(c);
}
function ssSprite(GT, col, sz, op) {
    const s = new THREE.Sprite(new THREE.SpriteMaterial({
        map: GT, color: col, blending: THREE.AdditiveBlending,
        transparent: true, depthWrite: false, opacity: op,
    }));
    s.scale.set(sz, sz, 1);
    return s;
}

function buildSpaceLayer(renderer, aspect, hooks) {
    /* ---------- Camera Position & Look-At Target ---------- */
    const CAM_X = -1;
    const CAM_Y = 0;
    const CAM_Z = 15;

    const LOOK_X = 0;
    const LOOK_Y = 0;
    const LOOK_Z = 0;

    const CAM_POS = new THREE.Vector3(CAM_X, CAM_Y, CAM_Z);
    const LOOK_TARGET = new THREE.Vector3(LOOK_X, LOOK_Y, LOOK_Z);

    const S = new THREE.Scene();
    const C = new THREE.PerspectiveCamera(40, aspect, 0.1, 400);
    C.position.copy(CAM_POS);
    C.lookAt(LOOK_TARGET);
    S.add(C);
    const GT = ssGlow();

    const texLoader = new THREE.TextureLoader();
    const loadReal = (urls, apply, isSRGB = true) => {
        const arr = Array.isArray(urls) ? urls : [urls];
        for (const u of arr) {
            if (spaceAssetCache.textures.has(u)) {
                apply(spaceAssetCache.textures.get(u));
                return;
            }
        }
        for (const u of arr) {
            if (spaceAssetCache.loadingPromises.has(u)) {
                spaceAssetCache.loadingPromises.get(u).then((t) => {
                    if (t) apply(t);
                    else if (arr.length > 1) loadReal(arr.slice(1), apply, isSRGB);
                });
                return;
            }
        }
        texLoader.load(
            arr[0],
            (tex) => {
                if (isSRGB) tex.colorSpace = THREE.SRGBColorSpace;
                tex.anisotropy = 8;
                tex.wrapS = THREE.RepeatWrapping;
                spaceAssetCache.textures.set(arr[0], tex);
                apply(tex);
            },
            undefined,
            () => { if (arr.length > 1) loadReal(arr.slice(1), apply, isSRGB); }
        );
    };

    /* env map */
    const SUN_POS = new THREE.Vector3(-6.5, 2.7, 6);   // the ONE place to move the sun
    const SUN_DIR = SUN_POS.clone().normalize();       // light direction comes from it

    /* lights: the sun is the only light */
    const SUN = {
        intensity: 3.2,       // overall brightness of the sunlight (Earth follows it too)
        color: 0xfff1dc,      // warm white; use 0xffffff for neutral
    };
    const dl = new THREE.DirectionalLight(SUN.color, SUN.intensity);
    dl.position.copy(SUN_DIR).multiplyScalar(20);
    const AMBIENT = {
        intensity: 0.25,      // 0 = pitch black dark side, 0.1 = faint, 0.5 = quite bright
        color: 0x4a6fa5,      // cool blue fill; use 0xffffff for neutral
    };
    const amb = new THREE.AmbientLight(AMBIENT.color, AMBIENT.intensity);
    S.add(dl, amb);

    /* starfield - 3 depth layers */
    const LAY = [];
    [[1400, -150, -120, 0.9], [700, -100, -60, 1.2], [250, -55, -28, 1.6]].forEach(([count, zMin, zMax, sz]) => {
        const p = [], col = [], palette = [[1, 1, 1], [0.7, 0.82, 1], [1, 0.88, 0.7]];
        for (let i = 0; i < count; i++) {
            const z = zMin + Math.random() * (zMax - zMin);
            const q = palette[Math.floor(Math.random() * 3)], b = 0.2 + Math.random() * 0.4;
            p.push((Math.random() - 0.5) * 2 * Math.abs(z) * 0.95, (Math.random() - 0.5) * 2 * Math.abs(z) * 0.55, z);
            col.push(q[0] * b, q[1] * b, q[2] * b);
        }
        const g = new THREE.BufferGeometry();
        g.setAttribute('position', new THREE.Float32BufferAttribute(p, 3));
        g.setAttribute('color', new THREE.Float32BufferAttribute(col, 3));
        const pt = new THREE.Points(g, new THREE.PointsMaterial({
            size: sz, sizeAttenuation: false, map: GT, vertexColors: true,
            transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, opacity: 0.6,
        }));
        S.add(pt); LAY.push(pt);
    });

    /* planets */
    const PL = [];
    const ER = 3.4;
    const EARTH_START_LON = 20;   // longitude facing the camera: 20 = Africa, 78 = India, 10 = Europe/Africa, -75 = Americas
    const EARTH_START = (EARTH_START_LON + 100) / 360;   // converts it to a texture offset
    const earthU = {
        dayT: { value: ssTex(512, 256, (g, w, h) => { g.fillStyle = '#14508f'; g.fillRect(0, 0, w, h); ssBlobs(g, w, h, ['#2f7a3a', '#6d8a45', '#a08a55'], 70, 38); }, false) },
        nightT: { value: ssTex(4, 4, (g) => { g.fillStyle = '#000'; g.fillRect(0, 0, 4, 4); }, false) },
        sun: { value: SUN_DIR }, rot: { value: 0 },
        sunI: { value: SUN.intensity * 0.4 },
        ambI: { value: 0.07 },
        ambC: { value: new THREE.Color(0x8899bb) },
        soft: { value: 5 },
        city: { value: 1 },                   // night-side city lights: 0 = off
        lightStart: { value: 0.005 },
        lightFade: { value: 0.1 },
    };
    const E = new THREE.Group();
    E.add(new THREE.Mesh(new THREE.SphereGeometry(ER, 96, 64), new THREE.ShaderMaterial({
        uniforms: earthU,
        vertexShader: 'varying vec2 u;varying vec3 n;void main(){u=uv;n=normalize(mat3(modelMatrix)*normal);gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.);}',
        fragmentShader: 'uniform float lightStart,lightFade,city;uniform sampler2D dayT,nightT;uniform vec3 sun;uniform float rot;varying vec2 u;varying vec3 n;void main(){vec2 q=vec2(u.x+rot,u.y);float d=dot(normalize(n),sun);vec3 day=texture2D(dayT,q).rgb,ni=texture2D(nightT,q).rgb;float k=smoothstep(-.12,.18,d);float g=smoothstep(.06,.2,ni.r);float lm=1.-smoothstep(-lightStart-lightFade,-lightStart,d);vec3 c=mix(ni*g*lm*city*vec3(1.5,1.1,.6)*1.6+day*.1,day*(max(d,0.)*2.0+.03),k);c+=vec3(.225,.1125,.0625)*smoothstep(0.,.35,.2-abs(d))*.1;gl_FragColor=vec4(c,1.);}',
    })));
    const atmo = (sc, side, mode) => new THREE.Mesh(new THREE.SphereGeometry(ER * sc, 64, 48), new THREE.ShaderMaterial({
        transparent: true, side, depthWrite: false, blending: THREE.AdditiveBlending,
        uniforms: { sun: { value: SUN_DIR }, mode: { value: mode } },
        vertexShader: 'varying vec3 nv,nw;void main(){nv=normalize(normalMatrix*normal);nw=normalize(mat3(modelMatrix)*normal);gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.);}',
        fragmentShader: 'uniform vec3 sun;uniform float mode;varying vec3 nv,nw;void main(){float c=dot(nv,vec3(0.,0.,1.));float i=mode>0.?pow(clamp(-c/.5,0.,1.),2.2)*0.45:pow(1.-clamp(c,0.,1.),3.5)*0.5;float l=.04+.96*smoothstep(-.1,.5,dot(nw,sun));gl_FragColor=vec4(vec3(.25,.55,1.)*i*l,i*l);}',
    }));
    E.add(atmo(1.14, THREE.FrontSide, 1), atmo(1.015, THREE.BackSide, -1));
    const moon = new THREE.Mesh(new THREE.SphereGeometry(0.6, 48, 32), new THREE.MeshStandardMaterial({ roughness: 1, metalness: 0, map: ssTex(512, 256, (g, w, h) => { g.fillStyle = '#8d8b88'; g.fillRect(0, 0, w, h); ssBlobs(g, w, h, ['#6f6d6a', '#a3a09b', '#5d5b59'], 120, 16); }) }));
    const mars = new THREE.Mesh(new THREE.SphereGeometry(1.3, 64, 48), new THREE.MeshStandardMaterial({ roughness: 1, metalness: 0, map: ssTex(512, 256, (g, w, h) => { g.fillStyle = '#b4552f'; g.fillRect(0, 0, w, h); ssBlobs(g, w, h, ['#8f3d22', '#c86a3c', '#6e3220'], 110, 30); g.fillStyle = '#f1e6dc'; g.fillRect(0, 0, w, 9); g.fillRect(0, h - 9, w, 9); }) }));

    moon.material.envMapIntensity = 0.25;
    mars.material.envMapIntensity = 0.25;

    // Earth (-2.6, -0.6, 0), Moon (0, 5.2, -9), Mars (14, 2.6, -18)
    [[E, -3, -0.8, 4], [mars, 5, 10.2, -24], [moon, 4, 1.6, 5]].forEach(([obj, x, y, z]) => {
        obj.userData.b = new THREE.Vector3(x, y, z); S.add(obj); PL.push(obj);
    });

    let texLeft = 4;
    loadReal([earthDayUrl], (t) => { t.wrapS = THREE.RepeatWrapping; earthU.dayT.value = t; texLeft--; }, false);
    loadReal([earthNightUrl], (t) => { t.wrapS = THREE.RepeatWrapping; earthU.nightT.value = t; texLeft--; }, false);
    loadReal([moonUrl], (t) => { moon.material.map = t; moon.material.needsUpdate = true; texLeft--; }, true);
    loadReal([marsUrl], (t) => { mars.material.map = t; mars.material.needsUpdate = true; texLeft--; }, true);

    /* sun with corona fbm shader */
    const SUNU = { time: { value: 0 }, glowK: { value: 3.0 } };
    const sunMesh = new THREE.Mesh(new THREE.PlaneGeometry(30, 30), new THREE.ShaderMaterial({
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
    }));
    sunMesh.position.copy(SUN_POS);
    const SUN_SIZE = 1.3;   // 1 = current size, 0.5 = half, 2 = double
    sunMesh.scale.setScalar((SUN_POS.distanceTo(CAM_POS) / 70) * SUN_SIZE);
    S.add(sunMesh);

    /* spacecraft */
    const CR = new THREE.Group(), CW = new THREE.Group(), P = {};
    CR.add(CW);
    CR.rotation.set(-0.8, 3.9, -1.6);
    CR.position.set(0, 0, 9);
    S.add(CR);

    function buildFB() {
        const g = new THREE.Group();
        const gold = new THREE.MeshStandardMaterial({ color: 0xb08a4a, metalness: 0.9, roughness: 0.35 });
        const wh = new THREE.MeshStandardMaterial({ color: 0xcfd3da, metalness: 0.5, roughness: 0.4 });
        const dk = new THREE.MeshStandardMaterial({ color: 0x2a2c30, metalness: 0.8, roughness: 0.4 });
        const pn = new THREE.MeshStandardMaterial({ color: 0x14306a, metalness: 0.7, roughness: 0.3, emissive: new THREE.Color(0x061430) });
        const cm = new THREE.Mesh(new THREE.CylinderGeometry(0.14, 0.5, 0.62, 48), wh); cm.position.y = 0.52;
        const sm = new THREE.Mesh(new THREE.CylinderGeometry(0.5, 0.5, 0.6, 48), gold); sm.position.y = -0.09;
        const nz = new THREE.Mesh(new THREE.CylinderGeometry(0.14, 0.26, 0.3, 32, 1, true), dk); nz.position.y = -0.54;
        g.add(cm, sm, nz);
        [-1, 1].forEach((side) => { for (let i = 0; i < 4; i++) { const p = new THREE.Mesh(new THREE.BoxGeometry(0.3, 0.014, 0.9), pn); p.position.set(side * (0.75 + i * 0.32), -0.05, 0); g.add(p); } });
        return { g, cm: [cm], sm: [sm, nz] };
    }
    const bxOf = (arr) => { const b = new THREE.Box3(); arr.forEach((o) => b.expandByObject(o)); return b; };

    function finishShip(m, cmL, smL) {
        const w = new THREE.Group(); w.add(m);
        const b = new THREE.Box3().setFromObject(w), sz = b.getSize(new THREE.Vector3());
        m.position.sub(b.getCenter(new THREE.Vector3()));
        const cb = bxOf(cmL.length ? cmL : [m]), cs = cb.getSize(new THREE.Vector3()), cc = cb.getCenter(new THREE.Vector3()), rad = Math.max(cs.x, cs.z) / 2;
        const hat = ssSprite(GT, 0xbfe8ff, rad * 0.9, 1);
        hat.visible = false;
        hat.position.set(cc.x, cc.y - cs.y * 0.1, cc.z + rad * 0.82);
        w.add(hat);

        w.scale.setScalar(2.6 / Math.max(sz.x, sz.y, sz.z));
        if (P.cur) CW.remove(P.cur); P.cur = w; P.hat = hat; CW.add(w);
    }

    const f0 = buildFB(); finishShip(f0.g, f0.cm, f0.sm);
    let shipDisposed = false;
    // Force-uploads textures and compiles shaders for everything, including off-screen and hidden objects.
    function warmUp() {
        const culled = [];
        S.traverse((o) => { if (o.frustumCulled) { culled.push(o); o.frustumCulled = false; } });
        const vis = CR.visible; CR.visible = true;
        [earthU.dayT.value, earthU.nightT.value, moon.material.map, mars.material.map]
            .forEach((t) => t && renderer.initTexture(t));
        renderer.compile(S, C);
        renderer.render(S, C);
        culled.forEach((o) => { o.frustumCulled = true; });
        CR.visible = vis;
    }
    let shipReady = false, shipReadyAt = null, loadLogged = false;   // the entrance starts only once the real model is in
    const MODEL_TIMEOUT = 20;                                         // seconds: after this, keep the placeholder ship
    CR.visible = false;

    const applyModel = (gltf) => {
        const model = gltf.scene.clone(true);
        const N = (re, no) => {
            const r = [];
            model.traverse((o) => { if (o.isMesh && re.test(o.name) && !(no && no.test(o.name))) r.push(o); });
            return r;
        };
        const cmL = N(/CM/i, /face/i), smL = N(/SM/i);
        let dir = new THREE.Vector3(-1, 0, 0);
        model.updateMatrixWorld(true);
        if (cmL.length && smL.length) {
            const d = bxOf(cmL).getCenter(new THREE.Vector3()).sub(bxOf(smL).getCenter(new THREE.Vector3()));
            if (d.length() > 1e-4) dir = d.normalize();
        }
        model.quaternion.setFromUnitVectors(dir, new THREE.Vector3(0, 1, 0));
        model.rotateX(Math.PI / 2);
        model.rotateY(Math.PI / 2);
        model.rotateZ(Math.PI / 2);
        model.updateMatrixWorld(true);
        model.traverse((o) => {
            if (o.isMesh) {
                o.frustumCulled = false;
                [].concat(o.material).forEach((q) => { q.envMapIntensity = 1.1; q.side = THREE.DoubleSide; });
            }
        });
        finishShip(model, cmL, smL);
        warmUp();
        shipReady = true;
    };

    const loadGltf = (urls) => {
        const arr = Array.isArray(urls) ? urls : [urls];
        const u = arr[0];
        const next = () => {
            if (arr.length > 1) loadGltf(arr.slice(1));
            else { console.error('[ship] all model sources failed, using placeholder'); shipReady = true; }
        };   // all sources failed: use the placeholder

        if (spaceAssetCache.gltfs.has(u)) {
            applyModel(spaceAssetCache.gltfs.get(u));
            return;
        }
        if (spaceAssetCache.loadingPromises.has(u)) {
            spaceAssetCache.loadingPromises.get(u).then((g) => {
                if (shipDisposed) return;
                if (g) applyModel(g);
                else next();
            });
            return;
        }
        const draco = new DRACOLoader().setDecoderPath('/draco/');
        const loader = new GLTFLoader().setDRACOLoader(draco);
        loader.setMeshoptDecoder(MeshoptDecoder);
        loader.load(
            u,
            (gltf) => {
                if (shipDisposed) return;
                spaceAssetCache.gltfs.set(u, gltf);
                applyModel(gltf);
            },
            undefined,
            (e) => {
                console.warn('Model failed to load:', u, e);
                next();
            }
        );
    };
    loadGltf([artemisIIUrl, orionUrl]);

    /* mission-start flight (ship leaves) */
    let mode = 'S1', t0 = 0, pendingLaunch = false, hudSent = false, readySent = false;
    const CAM0 = CAM_POS.clone(), hp = new THREE.Vector3();
    const LOOK0 = LOOK_TARGET.clone();
    const STN = 260, stp = new Float32Array(STN * 6), sto = [];
    const stg = new THREE.BufferGeometry();
    stg.setAttribute('position', new THREE.BufferAttribute(stp, 3));
    for (let i = 0; i < STN; i++) {
        const r = 1.2 + Math.random() * 5, a = Math.random() * 6.28;
        sto.push([Math.random() * 30 - 12, r * Math.cos(a), r * Math.sin(a)]);
    }
    const stm = new THREE.LineSegments(stg, new THREE.LineBasicMaterial({ color: 0xbfd8ff, transparent: true, opacity: 0, blending: THREE.AdditiveBlending, depthWrite: false }));
    stm.frustumCulled = false; S.add(stm);

    function endIntro() { mode = 'END'; hooks.onFade(1); hooks.onLaunchDone(); }

    function updT1(tt, dt) {
        const s = easeOut3(clamp(tt / 1.2)), sp2 = clamp((tt - 0.2) / 1.4);
        const nose = new THREE.Vector3(0, 1, 0).applyQuaternion(CR.quaternion).normalize();
        if (P.core) {
            P.core.material.opacity = 0.95 * s;
            P.core.scale.set(0.35 + 0.65 * s, 1.8 - 0.8 * s, 0.35 + 0.65 * s);
            P.cone.material.opacity = 0.7 * (1 - s) + 0.25;
            P.eng.scale.set(1, 0.7 + 2.2 * s + 0.12 * Math.sin(tt * 43), 1);
        }
        CR.position.addScaledVector(nose, dt * sp2 * sp2 * 5);
        const s1 = new THREE.Vector3().crossVectors(nose, new THREE.Vector3(0, 0, 1)).normalize();
        const s2 = new THREE.Vector3().crossVectors(nose, s1);
        for (let i = 0; i < STN; i++) {
            const o = sto[i];
            o[0] -= dt * (8 + 60 * sp2);
            if (o[0] < -14) o[0] = 16 + Math.random() * 4;
            const p = CR.position.clone().addScaledVector(nose, o[0]).addScaledVector(s1, o[1]).addScaledVector(s2, o[2]);
            const q = p.clone().addScaledVector(nose, 0.2 + sp2 * 3.5);
            stp.set([p.x, p.y, p.z, q.x, q.y, q.z], i * 6);
        }
        stg.attributes.position.needsUpdate = true;
        stm.material.opacity = 0.75 * sp2;
        if (P.hat) {
            P.hat.getWorldPosition(hp);
            const kd = easeOut3(clamp((tt - 0.3) / 1.7));
            const end = hp.clone().sub(hp.clone().sub(CAM0).normalize().multiplyScalar(0.55));
            C.position.lerpVectors(CAM0, end, kd);
            C.lookAt(new THREE.Vector3().lerpVectors(LOOK0, hp, kd));
        }
        hooks.onFade(clamp((tt - 1.8) / 0.35));
        if (tt >= 2.15 && mode === 'T1') endIntro();
    }

    /* entrance: planets drop in, ship slides in from left */
    function updS1(ts, launched) {
        PL.forEach((p, i) => {
            const k = easeOut3(clamp((ts - SPACE_T.planetsStart - i * SPACE_T.planetsStagger) / (SPACE_T.planetsDuration || 0.001)));
            const b = p.userData.b;
            p.position.set(
                b.x + Math.sin(ts * 0.1 + i) * 0.18,
                b.y + 26 * (1 - k) + Math.cos(ts * 0.13 + i * 2) * 0.12,
                b.z
            );
            if (i) p.rotation.y = ts * (0.02 + i * 0.01);
        });
        const ks = easeOut3(clamp((ts - SPACE_T.planetsStart - PL.length * SPACE_T.planetsStagger) / (SPACE_T.planetsDuration || 0.001)));
        sunMesh.position.set(SUN_POS.x, SUN_POS.y + 26 * (1 - ks), SUN_POS.z);
        if (!shipReady && ts > MODEL_TIMEOUT) {
            console.warn('[ship] TIMEOUT -> placeholder');
            shipReady = true;   // too slow: go on with the placeholder
        }
        if (shipReady && shipReadyAt == null && ts >= SPACE_T.shipStart) { shipReadyAt = ts; CR.visible = true; }
        const kc = shipReadyAt == null ? 0 : easeOut3(clamp((ts - shipReadyAt) / SPACE_T.shipDuration));
        if (!launched) CR.position.set(-14 + 15 * kc,
            0.4 + Math.sin(ts * 0.8) * 0.06,
            9);
        CW.rotation.set(Math.sin(ts * 0.1) * 0.1, 0.5 + Math.sin(ts * 0.5) * 0.1, 0);
        if (P.eng && !launched) {
            P.eng.scale.set(1 + 0.1 * Math.sin(ts * 31), 0.7 + (1 - kc) * 2.2 + 0.12 * Math.sin(ts * 43), 1 + 0.1 * Math.sin(ts * 37));
        }
        if (P.hat) P.hat.material.opacity = 0.55 + 0.45 * Math.sin(ts * 2.2);
        earthU.rot.value = EARTH_START - ts * 0.004;
        SUNU.time.value = ts;
    }

    /* hover picking */
    const ray = new THREE.Raycaster(), ndc = new THREE.Vector2(), hb = new THREE.Box3(), hc = new THREE.Vector3(), he = new THREE.Vector3();

    const SHIP_R = 1.3;   // finishShip scales the longest side to 2.6, so the radius is constant
    const aw = new THREE.Vector3(), ar = new THREE.Vector3(), aRight = new THREE.Vector3();

    return {
        // is the pointer (ndc -1..1) over the ship? Only before launch.
        pick(nx, ny) {
            if (mode !== 'S1' || !P.cur) return false;
            ray.setFromCamera(ndc.set(nx, ny), C);
            hb.setFromObject(P.cur);
            if (!ray.ray.intersectsBox(hb)) return false;                       // cheap pre-check
            return ray.intersectObject(P.cur, true).some((h) => h.object.isMesh); // ignore the invisible hatch sprite
        },
        // ship centre + on-screen radius, in px (stable: no bounding box)
        anchor(w, h) {
            if (!P.cur) return null;
            C.updateMatrixWorld();
            P.cur.getWorldPosition(aw);                       // model is centred inside its wrapper
            aRight.setFromMatrixColumn(C.matrixWorld, 0).multiplyScalar(SHIP_R);
            ar.copy(aw).add(aRight);
            aw.project(C); ar.project(C);
            return {
                x: (aw.x * 0.5 + 0.5) * w,
                y: (-aw.y * 0.5 + 0.5) * h,
                r: Math.abs((ar.x - aw.x) * 0.5 * w),
            };
        },
        render(ts, dt) {
            dt = Math.min(dt, 0.05);
            if (mode !== 'END') {
                if (!hudSent && ts >= SPACE_T.hudAt) { hudSent = true; hooks.onHud(true); }
                if (shipReadyAt == null && !loadLogged) { loadLogged = true; hooks.onLog('LOADING SPACECRAFT...'); }
                if (!readySent && ts >= SPACE_T.readyAt && shipReadyAt != null && ts >= shipReadyAt + SPACE_T.shipDuration * 0.5) {
                    readySent = true; hooks.onLog('READY'); hooks.onReady(true);
                }
                if (pendingLaunch && mode === 'S1') { pendingLaunch = false; mode = 'T1'; t0 = ts; C.position.copy(CAM0); }
                LAY.forEach((l, k) => { l.material.opacity = 0.6; l.rotation.z = ts * 0.0015 * (k + 1); });
                updS1(ts, mode !== 'S1');
                if (mode === 'S1') {
                    C.position.copy(CAM_POS);
                    C.lookAt(LOOK_TARGET);
                }
                if (mode === 'T1') updT1(ts - t0, dt);
            }
            sunMesh.quaternion.copy(C.quaternion);
            renderer.render(S, C);
        },
        warmUp,
        texturesReady: () => texLeft <= 0,
        progress: () => (4 - texLeft + (shipReady ? 1 : 0)) / 5,   // 4 textures + the ship model
        resize(a) {
            C.aspect = a;
            C.updateProjectionMatrix();
        },
        startMission() {
            if (mode !== 'S1' || pendingLaunch) return false;
            pendingLaunch = true;
            return true;
        },
        dispose() {
            shipDisposed = true;
            S.traverse((o) => {
                o.geometry?.dispose();
                [].concat(o.material || []).forEach((m) => m.dispose?.());
            });
            earthU.dayT.value.dispose(); earthU.nightT.value.dispose();
        },
    };
}

/* ===================== Stage: space scene only, drawn straight to the canvas ===================== */
function MissionStage({ onLaunchStart, onLaunchDone, className = '', style = {} }) {
    const containerRef = useRef(null);
    const canvasMountRef = useRef(null);
    const logRef = useRef(null);
    const fadeRef = useRef(null);
    const launchRef = useRef(null);
    const tipRef = useRef(null);
    const ptrRef = useRef(null);
    const cbRef = useRef({});
    cbRef.current = { onLaunchStart, onLaunchDone };

    const [hudVisible, setHudVisible] = useState(false);
    const [btnReady, setBtnReady] = useState(false);
    const [cover, setCover] = useState(true);
    const barRef = useRef(null);

    useEffect(() => {
        const container = containerRef.current;
        const canvasMount = canvasMountRef.current;
        if (!container || !canvasMount) return;

        const cleanups = [];
        const on = (tg, ev, fn) => { tg.addEventListener(ev, fn); cleanups.push(() => tg.removeEventListener(ev, fn)); };

        let disposed = false, finished = false;
        let raf = 0, t = 0, last = 0;
        let tipX = null, tipY = null;
        let spaceLog = 'ENTERING ORBIT';
        let launchFade = 0;

        const renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: 'high-performance' });
        renderer.outputColorSpace = THREE.SRGBColorSpace;
        renderer.toneMapping = THREE.NoToneMapping;   // render straight to screen, no tone mapping
        renderer.setClearColor(CONFIG.bg);
        renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, CONFIG.maxDpr));
        canvasMount.appendChild(renderer.domElement);

        const w0 = container.clientWidth || window.innerWidth;
        const h0 = container.clientHeight || window.innerHeight;
        renderer.setSize(w0, h0);

        const space = buildSpaceLayer(renderer, w0 / h0, {
            onHud: (v) => setHudVisible(v),
            onReady: (v) => setBtnReady(v),
            onLog: (s) => { spaceLog = s; },
            onFade: (v) => { launchFade = v; },
            onLaunchDone: () => {
                if (finished) return;
                finished = true;
                cancelAnimationFrame(raf);
                cbRef.current.onLaunchDone?.();
            },
        });

        launchRef.current = () => {
            if (space.startMission()) {
                setHudVisible(false);
                setBtnReady(false);
                spaceLog = 'Start Mission';
                cbRef.current.onLaunchStart?.();
            }
        };

        function resize() {
            const w = container.clientWidth || window.innerWidth;
            const h = container.clientHeight || window.innerHeight;
            renderer.setSize(w, h);
            space.resize(w / h);
        }

        const born = performance.now();
        let warm = false, warmed = false;
        function frame(now) {
            raf = requestAnimationFrame(frame);
            const dt = Math.min((now - last) / 1000, 0.25);
            last = now;
            if (!warm) {
                if (!warmed && (space.texturesReady() || now - born > 3000)) { space.warmUp(); warmed = true; }
                space.render(0, 0.016);
                const p = Math.max(space.progress(), Math.min(1, (now - born) / 4000) * 0.9);   // never looks stuck
                if (barRef.current) barRef.current.style.width = (p * 100).toFixed(0) + '%';
                if ((space.progress() >= 1 && now - born > 1000)) {
                    if (barRef.current) barRef.current.style.width = '100%';
                    warm = true; setCover(false);
                }
                return;
            }
            t += dt;
            space.render(t, dt);

            // hover label
            const tip = tipRef.current, ptr = ptrRef.current;
            if (tip) {
                const w = container.clientWidth, h = container.clientHeight;
                const over = !!ptr && space.pick(ptr.x, ptr.y);
                if (over) {
                    const a = space.anchor(w, h);
                    if (a) {
                        const tx = Math.min(a.x + a.r + 28, w - tip.offsetWidth - 16);
                        const ty = Math.min(h - tip.offsetHeight - 16, Math.max(16, a.y - tip.offsetHeight / 2));
                        if (tipX == null) { tipX = tx; tipY = ty; }          // first frame: no slide-in
                        else {
                            const k = 1 - Math.exp(-dt * 12);                // smooth follow
                            tipX += (tx - tipX) * k;
                            tipY += (ty - tipY) * k;
                        }
                        tip.style.transform = `translate3d(${Math.round(tipX)}px, ${Math.round(tipY)}px, 0)`;
                    }
                } else {
                    tipX = tipY = null;
                }
                tip.classList.toggle('on', over);
                container.style.cursor = over ? 'pointer' : '';
            }
            if (logRef.current && logRef.current.textContent !== spaceLog) logRef.current.textContent = spaceLog;
            if (fadeRef.current) fadeRef.current.style.opacity = launchFade;
        }

        on(window, 'resize', resize);
        on(container, 'pointermove', (e) => {
            const r = container.getBoundingClientRect();
            ptrRef.current = { x: ((e.clientX - r.left) / r.width) * 2 - 1, y: -((e.clientY - r.top) / r.height) * 2 + 1 };
        });
        on(container, 'pointerleave', () => { ptrRef.current = null; });
        on(document, 'visibilitychange', () => {
            if (finished || disposed) return;
            cancelAnimationFrame(raf);
            if (!document.hidden) { last = performance.now(); raf = requestAnimationFrame(frame); }
        });

        last = performance.now();
        raf = requestAnimationFrame(frame);

        return () => {
            disposed = true;
            cancelAnimationFrame(raf);
            cleanups.forEach((f) => f());
            space.dispose();
            renderer.dispose();
            renderer.forceContextLoss();
            if (renderer.domElement.parentElement) renderer.domElement.remove();
        };
    }, []);

    return (
        <div className={`control-center-root ${className}`} style={style} ref={containerRef}>
            <div className="fo" ref={canvasMountRef} />
            <div className="fo-ui">
                <div style={{
                    position: 'absolute', inset: 0, background: '#000', zIndex: 20, pointerEvents: 'none',
                    opacity: cover ? 1 : 0, transition: 'opacity 0.7s ease',
                    display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 14,
                }}>
                    <span style={{ color: '#7fb8ff', letterSpacing: '0.2em', fontSize: 13, fontFamily: '"Share Tech Mono", monospace' }}>
                        LOADING MISSION
                    </span>
                    <div style={{ width: 'min(320px, 70vw)', height: 4, background: 'rgba(127,184,255,.2)' }}>
                        <div ref={barRef} style={{ width: '0%', height: '100%', background: '#7fb8ff', transition: 'width 0.25s ease' }} />
                    </div>
                </div>

                {/* start button (appears after the spacecraft arrives) */}
                <div className={`ss-hud${hudVisible ? ' on' : ''}`}>
                    <div
                        className="ss-lw"
                        style={{
                            position: 'relative',
                            top: CONFIG.btn.down,
                            opacity: btnReady ? 1 : 0,
                            pointerEvents: btnReady ? 'auto' : 'none',
                            transition: 'opacity 0.6s ease',
                        }}>
                        <svg className="ss-ring" viewBox="0 0 264 76" preserveAspectRatio="none">
                            <polygon points="18,1 246,1 263,18 263,58 246,75 18,75 1,58 1,18" />
                        </svg>
                        <svg className="ss-ring b" viewBox="0 0 264 76" preserveAspectRatio="none">
                            <polygon points="18,1 246,1 263,18 263,58 246,75 18,75 1,58 1,18" />
                        </svg>
                        <button type="button" className="ss-go" onClick={() => launchRef.current?.()}>
                            Start Mission
                        </button>
                    </div>
                </div>

                <div className="ss-tip" ref={tipRef} aria-hidden="true">
                    <div className="ss-tip-n">Orion · Artemis II</div>
                    <p className="ss-tip-p">
                        During Artemis II, a smoke alarm went off about 80,000 miles from home.
                        The commander said it is a quick way to get everyone's attention.
                    </p>
                    <p className="ss-tip-p">
                        Fire has always been a deadly risk in space: Apollo 1 was lost to a fire in its
                        oxygen-filled cabin, Apollo 13 survived an oxygen tank explosion, and the Mir crew
                        survived a fire caused by an oxygen generator failure.
                    </p>
                </div>

                <div className="fo-fade" ref={fadeRef} />
            </div>
        </div>
    );
}

/* ===================== Public component ===================== */
export default function OpenningScene({ onConnect, onDisconnect, ...props }) {
    const navigate = useNavigate();

    // arriving at the opening scene (including coming back from the cabin): close any live connection
    useEffect(() => { onDisconnect?.(); }, []); // eslint-disable-line react-hooks/exhaustive-deps
    const [launched, setLaunched] = useState(false);
    const [error, setError] = useState('');

    // The token request lives in Film.jsx; here we only show its errors.
    const connect = useCallback(async () => {
        setError('');
        try {
            await onConnect?.();
        } catch (e) {
            setError(e.message);
        }
    }, [onConnect]);

    const handleLaunchDone = useCallback(() => {
        setLaunched(true);
        navigate('/home');
    }, [navigate]);

    return (
        <>
            <MissionStage {...props} onLaunchStart={connect} onLaunchDone={handleLaunchDone} />
            {launched && (
                <div className="cc-connecting">
                    {error ? (
                        <>
                            <span>Connection failed: {error}</span>
                            <button type="button" className="fo-done-replay" onClick={connect}>Retry</button>
                        </>
                    ) : (
                        <span>CONNECTING…</span>
                    )}
                </div>
            )}
        </>
    );
}