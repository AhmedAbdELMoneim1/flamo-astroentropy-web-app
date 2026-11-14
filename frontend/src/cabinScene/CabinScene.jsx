import { useEffect, useRef, useState } from 'react';
import * as THREE from 'three'; // written for three r186
import Ember, { createBus, pointLight, ambientLight, LIGHT_SCALE } from '../siAssistant/Ember.js';
import './CabinScene.css';
import { useNavigate, useLocation } from 'react-router-dom';
import earthDayUrl from '../assets/earth_day.webp'
import earthNightUrl from '../assets/earth_night.webp';
import { useAgentState } from '../siAssistant/useAgentState.js';
import { useLocalParticipant } from '@livekit/components-react';
import { useDashboard } from '../coreSolution/DashboardContext.jsx';
import { CATEGORIES } from '../coreSolution/categories';
import { preloadWorlds } from '../preloadWorlds.js';
import { useDeafen } from '../coreSolution/DeafenContext.jsx';
// add one import per asset the habitat, suit and spacecraft scenes use, for example:
// import suitModelUrl from '../assets/suit.glb';


/* ------------------------------------------------------------------ *
 *  Constants
 * ------------------------------------------------------------------ */
const V = THREE.Vector3;

const CAT = [
    {
        id: 'prevention', name: 'Prevention', lines: ['PREVENTION'], icon: 'prevention',
        desc: 'Ignition sources and material selection',
        color: '#ffb347',
        subs: [
            { id: 'ign', name: 'Ignition', color: '#ffe14d' },
            { id: 'mat', name: 'Materials', color: '#ffb347' },
        ],
    },
    {
        id: 'flammability', name: 'Flammability & fire behavior', lines: ['FLAMMABILITY &', 'FIRE BEHAVIOR'], icon: 'spread',
        desc: 'How flames grow and spread in microgravity',
        color: '#ff6a2a',
        subs: [{ id: 'spread', name: 'Flame spread', color: '#ff6a2a' }],
    },
    {
        id: 'detection', name: 'Detection', lines: ['DETECTION'], icon: 'detect',
        desc: 'Smoke and aerosol sensing',
        color: '#b79cff',
        subs: [{ id: 'smoke', name: 'Smoke', color: '#b79cff' }],
    },
    {
        id: 'suppression', name: 'Suppression', lines: ['SUPPRESSION'], icon: 'ext',
        desc: 'Extinguishing and recovery tests',
        color: '#9fe8ff',
        subs: [{ id: 'ext', name: 'Suppression', color: '#9fe8ff' }],
    },
];

const STS = [
    ['connecting', 'Connecting'],
    ['idle', 'Idle'],
    ['listening', 'Listening'],
    ['thinking', 'Thinking'],
    ['speaking', 'Speaking'],
    ['disconnected', 'Disconnected'],
];

/* ------------------------------------------------------------------ *
 *  Texture / canvas helpers
 * ------------------------------------------------------------------ */
function mk(w, h, fn) {
    const c = document.createElement('canvas');
    c.width = w; c.height = h;
    fn(c.getContext('2d'), w, h);
    const t = new THREE.CanvasTexture(c);
    t.wrapS = THREE.RepeatWrapping;
    t.colorSpace = THREE.SRGBColorSpace;
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

// 2x2 grid of main categories
function cellRect(i) {
    return { x: 90 + (i % 2) * 954, y: 310 + ((i / 2) | 0) * 526, w: 914, h: 480 };
}

// sub-category chips along the bottom of each card
const CHIP_W = 400, CHIP_H = 84;
function subRect(i, j) {
    const r = cellRect(i);
    return { x: r.x + 44 + j * (CHIP_W + 24), y: r.y + 350, w: CHIP_W, h: CHIP_H };
}

// mic button painted on the curved screen: top right, same line as "Welcome aboard, crew."
const MIC = { x: 1702, y: 140, w: 290, h: 120 };
const MIC_ICON = new Path2D('M12 3a3 3 0 0 1 3 3v5a3 3 0 0 1-6 0V6a3 3 0 0 1 3-3zM6 11a6 6 0 0 0 12 0M12 17v4');
const MIC_SLASH = new Path2D('M4 4L20 20');
const DEAF = { x: 1396, y: 140, w: 290, h: 120 };
const DEAF_ICON = new Path2D('M3 14v-2a9 9 0 0 1 18 0v2M3 14h3v6H4a1 1 0 0 1-1-1v-5zM21 14h-3v6h2a1 1 0 0 0 1-1v-5z');
const STATE_TEXT = {
    connecting: 'FLAMO · CONNECTING',
    idle: 'FLAMO · IDLE',
    listening: 'FLAMO · LISTENING',
    thinking: 'FLAMO · THINKING',
    speaking: 'FLAMO · SPEAKING',
    disconnected: 'FLAMO · DISCONNECTED',
};

function chm(g, x, y, w, h, c) {
    g.beginPath();
    g.moveTo(x, y); g.lineTo(x + w - c, y); g.lineTo(x + w, y + c);
    g.lineTo(x + w, y + h); g.lineTo(x + c, y + h); g.lineTo(x, y + h - c);
    g.closePath();
}

function rgba(h, a) {
    return `rgba(${parseInt(h.substr(1, 2), 16)},${parseInt(h.substr(3, 2), 16)},${parseInt(h.substr(5, 2), 16)},${a})`;
}

function icon(g, id, x, y, s) {
    g.save(); g.translate(x, y); g.scale(s / 100, s / 100);
    g.lineWidth = 7; g.lineCap = g.lineJoin = 'round'; g.beginPath();
    if (id === 'env') {
        g.arc(50, 50, 40, 0, 6.3); g.moveTo(10, 50); g.lineTo(90, 50);
        g.moveTo(50, 10); g.bezierCurveTo(20, 35, 20, 65, 50, 90);
        g.moveTo(50, 10); g.bezierCurveTo(80, 35, 80, 65, 50, 90);
    } else if (id === 'spread') {
        g.moveTo(50, 8); g.bezierCurveTo(95, 45, 85, 92, 50, 92); g.bezierCurveTo(15, 92, 8, 60, 30, 38);
        g.bezierCurveTo(34, 55, 44, 55, 46, 48); g.bezierCurveTo(52, 32, 44, 20, 50, 8);
    } else if (id === 'mat') {
        g.moveTo(50, 8); g.lineTo(88, 29); g.lineTo(88, 71); g.lineTo(50, 92); g.lineTo(12, 71); g.lineTo(12, 29); g.closePath();
        g.moveTo(12, 29); g.lineTo(50, 50); g.lineTo(88, 29); g.moveTo(50, 50); g.lineTo(50, 92);
    } else if (id === 'smoke') {
        g.moveTo(25, 78); g.arc(28, 62, 16, 2.2, 4.7); g.arc(52, 40, 22, 3.5, 5.9); g.arc(76, 60, 18, 4.4, 1.6); g.lineTo(25, 78);
    } else if (id === 'ign') {
        g.moveTo(58, 6); g.lineTo(20, 56); g.lineTo(48, 56); g.lineTo(40, 94); g.lineTo(80, 40); g.lineTo(52, 40); g.closePath();
    } else if (id === 'prevention') {            // shield + check
        g.moveTo(50, 6); g.lineTo(88, 20); g.lineTo(88, 52); g.bezierCurveTo(88, 74, 70, 88, 50, 94);
        g.bezierCurveTo(30, 88, 12, 74, 12, 52); g.lineTo(12, 20); g.closePath();
        g.moveTo(32, 50); g.lineTo(46, 64); g.lineTo(70, 36);
    } else if (id === 'detect') {                // sensor with signal arcs
        g.arc(50, 50, 10, 0, 6.3);
        [28, 44].forEach((r) => {
            g.moveTo(50 + Math.cos(-0.9) * r, 50 + Math.sin(-0.9) * r); g.arc(50, 50, r, -0.9, 0.9);
            g.moveTo(50 + Math.cos(2.24) * r, 50 + Math.sin(2.24) * r); g.arc(50, 50, r, 2.24, 4.04);
        });
    } else {                                     // 'ext'
        g.moveTo(50, 6); g.bezierCurveTo(78, 42, 86, 56, 86, 66); g.arc(50, 66, 36, 0, 3.1416); g.bezierCurveTo(14, 56, 22, 42, 50, 6);
    }
    g.stroke(); g.restore();
}

/* ------------------------------------------------------------------ *
 *  React component
 *
 *  Props
 *    agentState        'connecting' | 'idle' | 'listening' | 'thinking' | 'speaking' | 'disconnected'
 *    onStateChange     (state) => void        fired when the debug switcher changes state
 *    onCategorySelect  (id) => void           'env' | 'spread' | 'mat' | 'smoke' | 'ign' | 'ext'
 *    showStateSwitcher show the bottom-right state buttons (default true)
 *    intro             Ember's greeting bubble ('' to disable)
 *    className / style applied to the root element
 * ------------------------------------------------------------------ */
export default function CabinView({
    onStateChange,
    onCategorySelect,
    onDemo,
    showStateSwitcher = false,
    intro = "Hello! I'm Ember. Welcome aboard — pick a category to begin.",
    className = '',
    style,
}) {

    const navigate = useNavigate();
    const agentState = useAgentState();
    const { localParticipant, isMicrophoneEnabled } = useLocalParticipant();
    const navRef = useRef(navigate);
    navRef.current = navigate;
    const location = useLocation();
    const locRef = useRef(location);
    locRef.current = location;
    const DEST = '/solution';
    const rootRef = useRef(null);
    const canvasRef = useRef(null);
    const bubRef = useRef(null);
    const busRef = useRef(null);
    const cbRef = useRef({});
    const mutedRef = useRef(false);
    const { deafened, setDeafened } = useDeafen();
    const deafRef = useRef(false);
    const toggleDeafRef = useRef(() => { });
    const toggleRef = useRef(() => { });
    const redrawRef = useRef(null);
    const stateRef = useRef(agentState);
    const [state, setState] = useState(agentState);
    const [log, setLog] = useState('STATE ' + agentState.toUpperCase());

    cbRef.current = { onStateChange, onCategorySelect, onDemo };

    const muted = !isMicrophoneEnabled;
    mutedRef.current = muted;

    deafRef.current = deafened;
    toggleDeafRef.current = () => setDeafened((d) => !d);
    useEffect(() => { redrawRef.current?.(); }, [deafened]);

    toggleRef.current = () => localParticipant?.setMicrophoneEnabled(muted);   // muted -> turn on, else turn off
    /* voice: when the agent opens a view (view.open), go to the dashboard for that category */
    const { pillar, dashboard } = useDashboard();
    const lastDash = useRef(dashboard);          // ignore whatever was already there when the cabin mounted
    useEffect(() => {
        if (!dashboard || dashboard === lastDash.current) return;
        lastDash.current = dashboard;
        const cat = CATEGORIES[pillar];
        if (!cat) return;
        setLog('VOICE ' + cat.id.toUpperCase());
        navRef.current(`${DEST}?cat=${encodeURIComponent(cat.name)}`);
    }, [dashboard, pillar]);
    useEffect(() => { redrawRef.current?.(); }, [muted]);                      // repaint the screen when the state changes

    /* download the other 3D worlds' files in the background */
    useEffect(() => { preloadWorlds([/* suitModelUrl, habitatModelUrl, ... */]); }, []);

    /* keep internal state in sync with the prop */
    useEffect(() => {
        setState(agentState);
        setLog('STATE ' + agentState.toUpperCase());
    }, [agentState]);

    /* repaint the screen when the state changes */
    stateRef.current = state;
    useEffect(() => { redrawRef.current?.(); }, [state]);

    /* ------------------------- 3D scene ------------------------- */
    useEffect(() => {
        const root = rootRef.current, canvas = canvasRef.current, bubEl = bubRef.current;
        let disposed = false, raf = 0, hoverT = null, introT = null, bt = null, bh = null;

        const bus = createBus();
        busRef.current = bus;

        const size = () => ({ w: root.clientWidth || 1, h: root.clientHeight || 1 });
        let { w: W, h: H } = size();

        const R = new THREE.WebGLRenderer({ canvas, antialias: true });
        R.setPixelRatio(Math.min(devicePixelRatio, 2)); R.setSize(W, H, false);
        R.toneMapping = THREE.ACESFilmicToneMapping; R.toneMappingExposure = 0.9;

        /* ---------- scene ---------- */
        const SB = new THREE.Scene(), CB = new THREE.PerspectiveCamera(50, W / H, 0.05, 50);
        SB.environment = Ember.makeEnv(R); SB.background = new THREE.Color(0x05080f); SB.fog = new THREE.Fog(0x05080f, 7, 14);

        const wallT = mk(1024, 512, (g, w, h) => {
            g.fillStyle = '#8a929e'; g.fillRect(0, 0, w, h);
            for (let i = 0; i < 2500; i++) { const v = (110 + Math.random() * 60) | 0; g.fillStyle = `rgba(${v},${v},${v + 6},.35)`; g.fillRect(Math.random() * w, Math.random() * h, 5, 5); }
            g.strokeStyle = 'rgba(30,36,46,.7)'; g.lineWidth = 2;
            for (let i = 0; i <= w; i += 64) { g.beginPath(); g.moveTo(i, 0); g.lineTo(i, h); g.stroke(); }
            for (let i = 0; i <= h; i += 85) { g.beginPath(); g.moveTo(0, i); g.lineTo(w, i); g.stroke(); }
        });
        wallT.wrapT = THREE.RepeatWrapping; wallT.repeat.set(3, 2);
        const wall = new THREE.Mesh(new THREE.CylinderGeometry(3.4, 3.4, 12, 64, 1, true), new THREE.MeshStandardMaterial({ map: wallT, metalness: 0.4, roughness: 0.6, side: 1 }));
        wall.rotation.x = 1.5708; wall.position.z = -2; SB.add(wall);

        const dkM = new THREE.MeshStandardMaterial({ color: 0x2a3038, metalness: 0.7, roughness: 0.45 }),
            mtM = new THREE.MeshStandardMaterial({ color: 0x9aa3af, metalness: 0.9, roughness: 0.3 }),
            cwM = new THREE.MeshBasicMaterial({ color: new THREE.Color(1.6, 1.9, 2.4) });
        function box(w, h, d, x, y, z, m) { const o = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), m); o.position.set(x, y, z); SB.add(o); return o; }
        const endw = new THREE.Mesh(new THREE.CircleGeometry(3.4, 64), dkM); endw.position.z = -3.5; SB.add(endw); box(0.3, 0.05, 7, 0, 3.2, -1.5, cwM);

        [[-2.1, -1.4], [2.1, -1.4], [-2.9, 0.2], [2.9, 0.2]].forEach((p) => {
            const r = new THREE.Mesh(new THREE.CylinderGeometry(0.04, 0.04, 6, 16), mtM); r.rotation.x = 1.5708; r.position.set(p[0], p[1], -0.6); SB.add(r);
            const d = Math.hypot(p[0], p[1]);
            [-3, -1.4, 0.2].forEach((z) => {
                const q = new THREE.Mesh(new THREE.CylinderGeometry(0.02, 0.02, 3.4 - d, 8), mtM), m = d + (3.4 - d) / 2;
                q.position.set((p[0] / d) * m, (p[1] / d) * m, z); q.rotation.z = -Math.atan2(p[0], p[1]); SB.add(q);
            });
        });

        [[0, 0x15181d], [0.1, 0x15181d], [0.2, 0xd98a1a], [0.3, 0x15181d], [0.4, 0x2a62c9], [0.5, 0x15181d], [3.0, 0x15181d], [3.1, 0x2a62c9], [3.2, 0x15181d]].forEach((c) => {
            const a = 0.5 + c[0] * 1.6 + (c[0] > 2 ? 2.4 : 0), pts = [];
            for (let i = 0; i < 9; i++) pts.push(new V(Math.cos(a + Math.sin(i * 1.3) * 0.04) * 3.3, Math.sin(a + Math.sin(i * 1.3) * 0.04) * 3.3, 0.5 - i * 0.5));
            SB.add(new THREE.Mesh(new THREE.TubeGeometry(new THREE.CatmullRomCurve3(pts), 60, 0.035, 8), new THREE.MeshStandardMaterial({ color: c[1], roughness: 0.6, metalness: 0.2 })));
        });

        const panT = mk(128, 256, (g, w, h) => {
            g.fillStyle = '#0a0f16'; g.fillRect(0, 0, w, h);
            for (let i = 0; i < 30; i++) { g.fillStyle = ['#4fd6c9', '#7fb8ff', '#ffb347', '#39445a'][i % 4]; g.fillRect(10 + (i % 3) * 38, 12 + ((i / 3) | 0) * 24, 28, 12); }
            g.fillStyle = '#7fb8ff'; for (let i = 0; i < 5; i++) g.fillRect(10, h - 60 + i * 10, 20 + Math.random() * 90, 4);
        });
        [[-2.3, -0.4, 1.8], [2.3, -0.7, 1.2]].forEach((p) => {
            box(0.9, p[2], 0.08, p[0], p[1], -3.44, new THREE.MeshStandardMaterial({ color: 0xffffff, map: panT, emissive: 0xffffff, emissiveMap: panT, emissiveIntensity: 0.9, metalness: 0.5, roughness: 0.5 }));
        });

        /* ---------- real Earth, rendered to a texture for the porthole ---------- */
        const erT = new THREE.WebGLRenderTarget(512, 512, { samples: 4 });
        erT.texture.colorSpace = THREE.SRGBColorSpace;
        const ES = new THREE.Scene();
        const EC = new THREE.PerspectiveCamera(35, 1, 0.1, 100);
        EC.position.set(0, 0, 9); EC.lookAt(0, 0, 0);

        const SUN_DIR = new V(-6.5, 2.7, 6).normalize();
        const ER = 3.4;
        const earthU = {
            dayT: { value: null },
            nightT: { value: null },
            sun: { value: SUN_DIR }, rot: { value: 0.16 },       // 0.16 ≈ Africa/Europe facing the window
            city: { value: 1 }, lightStart: { value: 0.005 }, lightFade: { value: 0.1 },
        };
        const texLoader = new THREE.TextureLoader();
        const earthTex = [];
        texLoader.load(earthDayUrl, (t) => { t.wrapS = THREE.RepeatWrapping; t.anisotropy = 8; earthU.dayT.value = t; earthTex.push(t); });
        texLoader.load(earthNightUrl, (t) => { t.wrapS = THREE.RepeatWrapping; t.anisotropy = 8; earthU.nightT.value = t; earthTex.push(t); });
        const blank = new THREE.DataTexture(new Uint8Array([0, 0, 0, 255]), 1, 1); blank.needsUpdate = true;
        earthU.dayT.value = blank; earthU.nightT.value = blank;

        const EG = new THREE.Group();
        EG.add(new THREE.Mesh(new THREE.SphereGeometry(ER, 96, 64), new THREE.ShaderMaterial({
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
        EG.add(atmo(1.14, THREE.FrontSide, 1), atmo(1.015, THREE.BackSide, -1));
        EG.position.set(-0.6, -2.3, 0);        // offset down-left so the curved horizon shows in the window
        ES.add(EG);

        // a few stars behind it
        const sp = [];
        for (let i = 0; i < 300; i++) sp.push((Math.random() - 0.5) * 60, (Math.random() - 0.5) * 40, -20 - Math.random() * 20);
        const sGeo = new THREE.BufferGeometry(); sGeo.setAttribute('position', new THREE.Float32BufferAttribute(sp, 3));
        ES.add(new THREE.Points(sGeo, new THREE.PointsMaterial({ size: 1.2, sizeAttenuation: false, color: 0xffffff })));

        const ph = new THREE.Mesh(
            new THREE.CircleGeometry(0.4, 48),
            new THREE.MeshBasicMaterial({ map: erT.texture, toneMapped: false })
        );
        ph.position.set(2.3, 0.95, -3.44); SB.add(ph);
        const phr = new THREE.Mesh(new THREE.TorusGeometry(0.43, 0.06, 12, 48), mtM); phr.position.copy(ph.position); SB.add(phr);
        for (let i = 0; i < 8; i++) { const sc2 = new THREE.Mesh(new THREE.SphereGeometry(0.02, 8, 8), dkM); sc2.position.set(2.3 + Math.cos(i * 0.785) * 0.43, 0.95 + Math.sin(i * 0.785) * 0.43, -3.38); SB.add(sc2); }

        const AMB = [[-2.3, 1.25], [-2.3, 0.9], [0, -1.7]].map((p) => {
            const m = new THREE.MeshBasicMaterial({ color: new THREE.Color(3, 1.3, 0.1), transparent: true }), o = new THREE.Mesh(new THREE.SphereGeometry(0.07, 16, 12), m);
            o.position.set(p[0], p[1], -3.4); SB.add(o); return m;
        });
        const amL = pointLight(0xff9a2a, 1.4, 5); amL.position.set(-2.2, 1, -2.9); SB.add(amL);
        const cwL = pointLight(0xdfeaff, 1.9, 14); cwL.position.set(0, 2.4, -1.2);
        SB.add(cwL, pointLight(0xbfd8ff, 0.8, 10), ambientLight(0x8fa8c8, 0.5));
        SB.children[SB.children.length - 2].position.set(0, -1.5, -0.5);

        /* ---------- curved screen ---------- */
        const SR = 3, SL = 1.04, SH = 2.1, SCT = Math.PI - SL / 2;
        const scrCan = document.createElement('canvas'); scrCan.width = 2048; scrCan.height = 1376;
        const sg = scrCan.getContext('2d'), scrTex = new THREE.CanvasTexture(scrCan);
        scrTex.wrapS = THREE.RepeatWrapping; scrTex.repeat.x = -1; scrTex.offset.x = 1; scrTex.anisotropy = 8; scrTex.colorSpace = THREE.SRGBColorSpace;
        const scr = new THREE.Mesh(new THREE.CylinderGeometry(SR, SR, SH, 64, 1, true, SCT, SL), new THREE.MeshBasicMaterial({ map: scrTex, side: 1, toneMapped: false }));
        SB.add(scr);
        SB.add(new THREE.Mesh(new THREE.CylinderGeometry(SR + 0.02, SR + 0.02, SH + 0.22, 64, 1, true, SCT - 0.07, SL + 0.14), new THREE.MeshStandardMaterial({ color: 0x1a1f27, metalness: 0.8, roughness: 0.4, side: 1 })));
        [-1, 1].forEach((s) => {
            SB.add(new THREE.Mesh(new THREE.CylinderGeometry(SR + 0.01, SR + 0.01, 0.025, 64, 1, true, SCT - 0.07, SL + 0.14), new THREE.MeshBasicMaterial({ color: new THREE.Color(1.2, 1.8, 2.6), side: 1 })).translateY(s * (SH / 2 + 0.1)));
        });

        let hv = -1, hs = -1, hm = false, hd = false, hx = 0, hy = 0, nx = 0, ny = 0;   // hv = hovered card, hs = hovered chip, hm = mic hovered

        function drawScreen(hover, hSub = -1) {
            const g = sg, SW = 2048, SHt = 1376, bg = g.createLinearGradient(0, 0, 0, SHt);
            bg.addColorStop(0, '#071120'); bg.addColorStop(1, '#03060c'); g.fillStyle = bg; g.fillRect(0, 0, SW, SHt);
            g.strokeStyle = 'rgba(127,184,255,.07)'; g.lineWidth = 2;
            for (let i = 0; i < SW; i += 64) { g.beginPath(); g.moveTo(i, 0); g.lineTo(i, SHt); g.stroke(); }
            for (let i = 0; i < SHt; i += 64) { g.beginPath(); g.moveTo(0, i); g.lineTo(SW, i); g.stroke(); }
            g.fillStyle = '#7fb8ff'; g.font = '600 34px "Chakra Petch"'; g.fillText('ARTEMIS · CABIN HUB', 56, 92);
            g.fillStyle = '#eaf3ff'; g.font = '700 92px "Chakra Petch"'; g.fillText('Welcome aboard, crew.', 56, 200);
            g.fillStyle = '#9fb4d8'; g.font = '400 38px "Chakra Petch"'; g.fillText('Choose a category to begin your safety briefing.', 56, 262);

            // agent state, above the mic button (same style as "ARTEMIS · CABIN HUB")
            g.fillStyle = '#7fb8ff'; g.font = '600 34px "Chakra Petch"';
            g.fillText(STATE_TEXT[stateRef.current] || stateRef.current.toUpperCase(), 1648, 92);

            const btn = (q, on, c, ico, slash, title, sub, subCol) => {
                g.save();
                chm(g, q.x, q.y, q.w, q.h, 30);
                g.fillStyle = rgba(c, on ? 0.35 : 0.14);
                if (on) { g.shadowColor = c; g.shadowBlur = 40; }
                g.fill(); g.shadowBlur = 0;
                g.lineWidth = 4; g.strokeStyle = c; g.stroke();
                g.save();
                if (title == null) {                       // icon only: centered
                    const s = 72;
                    g.translate(q.x + (q.w - s) / 2, q.y + (q.h - s) / 2); g.scale(s / 24, s / 24);
                } else {
                    g.translate(q.x + 22, q.y + 28); g.scale(64 / 24, 64 / 24);
                }
                g.lineWidth = 2; g.lineCap = 'round'; g.lineJoin = 'round'; g.strokeStyle = c;
                g.stroke(ico); if (slash) g.stroke(MIC_SLASH);
                g.restore();
                if (title != null) {
                    g.fillStyle = c; g.font = '700 30px "Chakra Petch"'; g.fillText(title, q.x + 94, q.y + 54);
                    g.fillStyle = subCol; g.font = '400 21px "Chakra Petch"'; g.fillText(sub, q.x + 94, q.y + 90);
                }
                g.restore();
            };
            {
                const mu = mutedRef.current, df = deafRef.current;
                btn(DEAF, hd, df ? '#ff4d6d' : '#7fb8ff', DEAF_ICON, df,
                    df ? 'UNDEAFEN' : 'DEAFEN', df ? 'Sound off' : 'Sound on', '#9fb4d8');
                btn(MIC, hm, mu ? '#ff4d6d' : '#7fb8ff', MIC_ICON, mu,
                    mu ? 'UNMUTE' : 'MUTE', mu ? 'Mic off' : 'Mic on', '#9fb4d8');
            }

            CAT.forEach((c, i) => {
                const r = cellRect(i), on = i === hover, col = c.color;
                g.save(); chm(g, r.x, r.y, r.w, r.h, 44);
                g.fillStyle = on ? 'rgba(20,34,52,.98)' : 'rgba(11,17,26,.92)';
                if (on) { g.shadowColor = col; g.shadowBlur = 60; }
                g.fill(); g.restore();
                if (on) { chm(g, r.x, r.y, r.w, r.h, 44); g.fillStyle = rgba(col, 0.2); g.fill(); }
                g.fillStyle = col; g.fillRect(r.x, r.y, r.w - 44, 8); g.fillRect(r.x, r.y, 8, r.h - 44);
                g.strokeStyle = col; icon(g, c.icon, r.x + 44, r.y + 54, 100);

                // title (1 or 2 lines) + description
                g.fillStyle = on ? '#fff' : '#dff0ff'; g.font = '700 52px "Chakra Petch"';
                const two = c.lines.length > 1, ty = r.y + (two ? 216 : 240);
                c.lines.forEach((ln, k) => g.fillText(ln, r.x + 44, ty + k * 52));
                g.fillStyle = on ? '#cfe0f5' : '#8fa6c6'; g.font = '400 31px "Chakra Petch"';
                g.fillText(c.desc, r.x + 44, r.y + (two ? 318 : 300));

                // (no ring: the hub shows no gauge now that nothing on it is a measurement; Round 12 item 12)

                // sub-category chips
                c.subs.forEach((s, j) => {
                    const q = subRect(i, j), sOn = on && j === hSub;
                    chm(g, q.x, q.y, q.w, q.h, 18);
                    g.fillStyle = rgba(s.color, sOn ? 0.38 : 0.12); g.fill();
                    g.lineWidth = sOn ? 4 : 2; g.strokeStyle = rgba(s.color, sOn ? 1 : 0.6); g.stroke();
                    g.strokeStyle = s.color; icon(g, s.id === 'ext' ? 'ext' : s.id, q.x + 24, q.y + 20, 44);
                    g.fillStyle = sOn ? '#fff' : '#dff0ff'; g.font = '600 34px "Chakra Petch"';
                    g.fillText(s.name.toUpperCase(), q.x + 88, q.y + 55);
                });

                g.fillStyle = rgba(col, 0.8); g.fillRect(r.x + 44, r.y + r.h - 30, on ? 200 : 90, 6);
            });
            scrTex.needsUpdate = true;
        }
        drawScreen(-1);
        redrawRef.current = () => drawScreen(hv, hs);
        if (document.fonts && document.fonts.ready) document.fonts.ready.then(() => { if (!disposed) drawScreen(hv, hs); });

        const RC = new THREE.Raycaster(), mv = new THREE.Vector2();
        function screenPt(e) {
            const rect = canvas.getBoundingClientRect();
            mv.set(((e.clientX - rect.left) / rect.width) * 2 - 1, -((e.clientY - rect.top) / rect.height) * 2 + 1);
            RC.setFromCamera(mv, CB);
            const h = RC.intersectObject(scr)[0]; if (!h) return null;
            return { x: (1 - h.uv.x) * 2048, y: (1 - h.uv.y) * 1376 };
        }
        function hit(e) {
            const p = screenPt(e); if (!p) return -1;
            for (let i = 0; i < CAT.length; i++) {
                const r = cellRect(i);
                if (p.x >= r.x && p.x <= r.x + r.w && p.y >= r.y && p.y <= r.y + r.h) return i;
            }
            return -1;
        }
        function hitMic(e) {
            const p = screenPt(e);
            return !!p && p.x >= MIC.x && p.x <= MIC.x + MIC.w && p.y >= MIC.y && p.y <= MIC.y + MIC.h;
        }
        function hitDeaf(e) {
            const p = screenPt(e);
            return !!p && p.x >= DEAF.x && p.x <= DEAF.x + DEAF.w && p.y >= DEAF.y && p.y <= DEAF.y + DEAF.h;
        }

        /* ---------- Ember ---------- */
        const ember = new Ember({ scene: SB, bus, host: root });
        ember.pos.set(1.55, -0.8, -1.6); ember.root.scale.setScalar(0.75); ember.lookAt(CB.position);
        bus.emit('agent:state', agentState); // sync initial state

        function say(tx, hold) {
            clearInterval(bt); clearTimeout(bh); bubEl.style.opacity = 1; let i = 0; bubEl.textContent = '';
            bt = setInterval(() => {
                bubEl.textContent = tx.slice(0, ++i);
                if (i >= tx.length) { clearInterval(bt); if (hold) bh = setTimeout(() => { bubEl.style.opacity = 0; }, hold); }
            }, 22);
        }

        /* robot looks at the hovered category after a delay */
        let looking = false; const HOVER_DELAY = 500;
        function cellWorld(i) {
            const r = cellRect(i), u = 1 - (r.x + r.w / 2) / 2048, v = 1 - (r.y + r.h / 2) / 1376, th = SCT + u * SL;
            return new V(SR * Math.sin(th), (v - 0.5) * SH, SR * Math.cos(th));
        }

        const onMove = (e) => {
            const n = hit(e), m = hitMic(e), d = hitDeaf(e);
            canvas.style.cursor = (n >= 0 || m || d) ? 'pointer' : 'default';
            canvas.title = m ? (mutedRef.current ? 'Unmute microphone' : 'Mute microphone')
                : d ? (deafRef.current ? 'Hear Flamo again' : 'Silence Flamo')
                    : '';
            if (m !== hm || d !== hd) { hm = m; hd = d; drawScreen(hv, hs); }
            if (n === hv) return;
            hv = n; drawScreen(hv);
            if (n >= 0) { const r = cellRect(n); hx = ((r.x + r.w / 2) / 2048 - 0.5) * 2; hy = (0.5 - (r.y + r.h / 2) / 1376) * 2; } else { hx = hy = 0; }
            clearTimeout(hoverT);
            if (n >= 0) {
                if (looking) ember.lookAt(cellWorld(n));
                else hoverT = setTimeout(() => { if (hv >= 0) { looking = true; ember.lookAt(cellWorld(hv)); } }, HOVER_DELAY);
            } else if (looking) { looking = false; ember.lookAt(CB.position); }
        };
        const onLeave = () => { if (hv !== -1 || hm || hd) onMove({ clientX: -9999, clientY: -9999 }); };

        const onClick = (e) => {
            if (hitMic(e)) { toggleRef.current(); return; }
            if (hitDeaf(e)) { toggleDeafRef.current(); return; }
            const g = hit(e); if (g < 0) return;
            const card = CAT[g];
            root.style.setProperty('--accent', card.color);
            bus.emit('category:select', card.id);
            setLog('CATEGORY ' + card.id.toUpperCase());
            cbRef.current.onCategorySelect?.(card.id);
            navRef.current(`${DEST}?cat=${encodeURIComponent(card.name)}`);
        };
        canvas.addEventListener('pointermove', onMove);
        canvas.addEventListener('pointerleave', onLeave);
        canvas.addEventListener('click', onClick);

        /* ---------- resize ---------- */
        const ro = new ResizeObserver(() => {
            const s = size(); W = s.w; H = s.h;
            R.setSize(W, H, false); CB.aspect = W / H; CB.updateProjectionMatrix();
        });
        ro.observe(root);

        /* ---------- intro ---------- */
        if (intro) introT = setTimeout(() => say(intro, 5000), 1300);

        /* ---------- render loop ---------- */
        const ease = (k) => 1 - Math.pow(1 - k, 3), cl = (k) => Math.max(0, Math.min(1, k));
        const s2t0 = performance.now(), T0 = s2t0;
        let lastN = performance.now(), amp = 0, Ld = 2.1, Ly = -0.68;
        const sy = { next: 0, tgt: 0, left: 0 };

        (function tick(now) {
            if (disposed) return;
            raf = requestAnimationFrame(tick);
            const dt = Math.min((now - lastN) / 1000, 0.05); lastN = now; const t = (now - T0) / 1000;
            const ke = ease(cl((now - s2t0) / 1500));
            nx += (hx - nx) * 0.06; ny += (hy - ny) * 0.06;
            CB.position.set(nx * 0.18 + Math.sin(t * 0.3) * 0.02, ny * 0.1 + Math.cos(t * 0.4) * 0.015, 0.7 * (1 - ke));
            CB.lookAt(nx * 0.35, ny * 0.3, -3);
            AMB.forEach((m, i) => { m.opacity = 0.35 + 0.65 * Math.abs(Math.sin(t * 1.6 + i)); });
            amL.intensity = (0.5 + 1.2 * Math.abs(Math.sin(t * 1.6))) * LIGHT_SCALE;
            if (ember.S.state === 'speaking') {
                if (t > sy.next) {
                    if (sy.left > 0) { sy.left--; sy.tgt = 0.35 + Math.random() * 0.65; ember.S.shape = Math.random(); sy.next = t + 0.11 + Math.random() * 0.11; }
                    else { sy.tgt = 0.04; sy.next = t + 0.12 + Math.random() * 0.3; sy.left = 2 + ((Math.random() * 4) | 0); }
                }
                amp += (sy.tgt - amp) * 0.35; bus.emit('agent:amplitude', amp);
            }
            CB.updateMatrixWorld();
            const lis = ember.S.state === 'listening';
            Ld += ((lis ? 1.5 : 2.1) - Ld) * 0.08; Ly += ((lis ? -0.55 : -0.68) - Ly) * 0.08;
            const cp = new V(-0.78, Ly, 0.5).unproject(CB).sub(CB.position).normalize().multiplyScalar(Ld).add(CB.position);
            const fl = ember.inst.fl;
            ember.pos.set(cp.x + fl * 0.02 * Math.sin(t * 0.9), cp.y + fl * (0.07 * Math.sin(t * 1.3) + 0.025 * Math.sin(t * 2.1)), cp.z);
            ember.tick(dt);
            const v = ember.pos.clone().project(CB);
            bubEl.style.left = Math.max(330, (v.x * 0.5 + 0.5) * W - 50) + 'px';
            bubEl.style.top = Math.max(100, (-v.y * 0.5 + 0.5) * H - 70) + 'px';
            earthU.rot.value = 0.16 - t * 0.004;     // slow rotation, same as ControlCenter
            R.setRenderTarget(erT);
            R.render(ES, EC);
            R.setRenderTarget(null);
            R.render(SB, CB);
        })(performance.now());

        /* ---------- cleanup ---------- */
        return () => {
            disposed = true;
            cancelAnimationFrame(raf);
            clearTimeout(hoverT); clearTimeout(introT); clearInterval(bt); clearTimeout(bh);
            canvas.removeEventListener('pointermove', onMove);
            canvas.removeEventListener('pointerleave', onLeave);
            canvas.removeEventListener('click', onClick);
            redrawRef.current = null;
            ro.disconnect();
            SB.traverse((o) => {
                if (o.geometry) o.geometry.dispose();
                if (o.material) (Array.isArray(o.material) ? o.material : [o.material]).forEach((m) => { if (m.map) m.map.dispose(); m.dispose(); });
            });
            scrTex.dispose();
            R.dispose();
            busRef.current = null;
            erT.dispose(); sGeo.dispose(); blank.dispose();
            earthTex.forEach((t) => t.dispose());
            EG.traverse((o) => { o.geometry?.dispose(); o.material?.dispose?.(); });
        };
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    /* push agent state into the scene */
    useEffect(() => {
        if (busRef.current) busRef.current.emit('agent:state', state);
    }, [state]);

    const pickState = (k) => {
        setState(k);
        setLog('STATE ' + k.toUpperCase());
        if (cbRef.current.onStateChange) cbRef.current.onStateChange(k);
    };

    return (
        <div ref={rootRef} className={`cabin-view ${className}`.trim()} style={{ position: 'relative', ...style }}>
            <canvas ref={canvasRef} className="cv-canvas" />
            <nav className="cv-dock" aria-label="Project">
                <div className="cv-dock-grp">
                    <button type="button" className="cv-dock-btn primary" onClick={() => cbRef.current.onDemo?.()}>
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                            <path d="M1 6v16l7-4 8 4 7-4V2l-7 4-8-4zM8 2v16M16 6v16" />
                        </svg>
                        <span>DEMO</span>
                    </button>
                    <button
                        type="button"
                        className="cv-dock-btn"
                        onClick={() => navRef.current('/about', { state: { backgroundLocation: locRef.current } })}
                    >
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                            <path d="M9 11a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM2 20v-1a5 5 0 0 1 5-5h4a5 5 0 0 1 5 5v1M17 11a3 3 0 1 0 0-6M19 20v-1a5 5 0 0 0-3-4.5" />
                        </svg>
                        <span>ABOUT</span>
                    </button>
                </div>
            </nav>
            <div ref={bubRef} className="cv-pnl cv-bub" />
            {showStateSwitcher && (
                <div className="cv-pnl cv-sts">
                    {STS.map(([k, label]) => (
                        <button key={k} type="button" className={state === k ? 'on' : ''} onClick={() => pickState(k)}>
                            {label}
                        </button>
                    ))}
                </div>
            )}
        </div>
    );
}