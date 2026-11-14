import * as THREE from 'three';

THREE.Cache.enabled = true;

const done = new Set();
const IMG = /\.(jpe?g|png|webp)$/i;

export function preloadWorlds(urls) {
    const run = () => urls.forEach((u) => {
        if (!u || done.has(u)) return;
        done.add(u);
        if (IMG.test(u)) new THREE.ImageLoader().load(u, () => { }, undefined, () => done.delete(u));
        else {
            const f = new THREE.FileLoader();
            f.setResponseType('arraybuffer');
            f.load(u, () => { }, undefined, () => done.delete(u));
        }
    });
    (window.requestIdleCallback || ((fn) => setTimeout(fn, 600)))(run);
}