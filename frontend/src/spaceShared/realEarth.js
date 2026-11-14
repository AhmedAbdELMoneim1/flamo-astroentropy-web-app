import * as THREE from 'three';
import earthDayUrl from '../assets/earth_day.webp';
import earthNightUrl from '../assets/earth_night.webp';

/* Same Earth as OpenningScene: day/night shader + city lights + atmosphere glow.
   createRealEarth({ radius, sun: THREE.Vector3 })  ->  { group, update(t), dispose() }  */
export function createRealEarth({ radius, sun, startLon = 20, orient = [0, 0, 0] }) {
    const SUN = sun.clone().normalize();
    const START = (startLon + 100) / 360;            // longitude facing the camera: 20 = Africa, 78 = India, -75 = Americas

    const tex1 = (r, g, b) => { const t = new THREE.DataTexture(new Uint8Array([r, g, b, 255]), 1, 1); t.needsUpdate = true; return t; };
    const blankDay = tex1(20, 80, 143), blankNight = tex1(0, 0, 0);   // shown until the jpgs load
    const U = {
        dayT: { value: blankDay }, nightT: { value: blankNight },
        sun: { value: SUN }, rot: { value: START },
        city: { value: 1 }, lightStart: { value: 0.005 }, lightFade: { value: 0.1 },
    };

    const group = new THREE.Group();
    const sphere = new THREE.Mesh(new THREE.SphereGeometry(radius, 96, 64), new THREE.ShaderMaterial({
        uniforms: U,
        vertexShader: 'varying vec2 u;varying vec3 n;void main(){u=uv;n=normalize(normal);gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.);}',
        fragmentShader: 'uniform float lightStart,lightFade,city;uniform sampler2D dayT,nightT;uniform vec3 sun;uniform float rot;varying vec2 u;varying vec3 n;void main(){vec2 q=vec2(u.x+rot,u.y);float d=dot(normalize(n),sun);vec3 day=texture2D(dayT,q).rgb,ni=texture2D(nightT,q).rgb;float k=smoothstep(-.12,.18,d);float g=smoothstep(.06,.2,ni.r);float lm=1.-smoothstep(-lightStart-lightFade,-lightStart,d);vec3 c=mix(ni*g*lm*city*vec3(1.5,1.1,.6)*1.6+day*.1,day*(max(d,0.)*2.0+.03),k);c+=vec3(.225,.1125,.0625)*smoothstep(0.,.35,.2-abs(d))*.1;gl_FragColor=vec4(c,1.);}',
    }));
    const atmo = (sc, side, mode) => new THREE.Mesh(new THREE.SphereGeometry(radius * sc, 64, 48), new THREE.ShaderMaterial({
        transparent: true, side, depthWrite: false, blending: THREE.AdditiveBlending,
        uniforms: { sun: { value: SUN }, mode: { value: mode } },
        vertexShader: 'varying vec3 nv,nw;void main(){nv=normalize(normalMatrix*normal);nw=normalize(mat3(modelMatrix)*normal);gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.);}',
        fragmentShader: 'uniform vec3 sun;uniform float mode;varying vec3 nv,nw;void main(){float c=dot(nv,vec3(0.,0.,1.));float i=mode>0.?pow(clamp(-c/.5,0.,1.),2.2)*0.45:pow(1.-clamp(c,0.,1.),3.5)*0.5;float l=.04+.96*smoothstep(-.1,.5,dot(nw,sun));gl_FragColor=vec4(vec3(.25,.55,1.)*i*l,i*l);}',
    }));
    // orient = [x, y, z] in degrees. The sun is converted to the sphere's own space, so lighting doesn't move.
    const D = THREE.MathUtils.degToRad;
    sphere.rotation.set(D(orient[0]), D(orient[1]), D(orient[2]));
    U.sun.value = SUN.clone().applyQuaternion(sphere.quaternion.clone().invert());
    group.add(sphere, atmo(1.14, THREE.FrontSide, 1), atmo(1.015, THREE.BackSide, -1));

    // textures are left untagged on purpose (the shader writes raw colour), same as OpenningScene
    let dead = false;
    const loaded = [];
    const loader = new THREE.TextureLoader();
    const load = (url, apply) => loader.load(url, (t) => {
        if (dead) { t.dispose(); return; }
        t.wrapS = THREE.RepeatWrapping; t.anisotropy = 8; loaded.push(t); apply(t);
    });
    load(earthDayUrl, (t) => { U.dayT.value = t; });
    load(earthNightUrl, (t) => { U.nightT.value = t; });

    return {
        group,
        update(t) { U.rot.value = START - t * 0.004; },
        dispose() {
            dead = true;
            group.traverse((o) => { o.geometry?.dispose(); o.material?.dispose?.(); });
            loaded.forEach((t) => t.dispose()); blankDay.dispose(); blankNight.dispose();
        },
    };
}