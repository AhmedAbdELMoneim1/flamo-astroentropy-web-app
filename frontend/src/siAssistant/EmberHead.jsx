import { useEffect, useRef } from 'react';
import * as THREE from 'three'; // written for three r186
import Ember, { createBus } from './Ember';

/**
 * Ember's animated head in its own canvas — drop it anywhere (chat header, voice panel, button...).
 *
 * Props
 *   state      'connecting' | 'idle' | 'listening' | 'thinking' | 'speaking' | 'disconnected'
 *   amplitude  0..1 mouth opening while state === 'speaking'
 *   alert      true turns Ember red
 *   accent     CSS color for the accent variable (default '#7fb8ff')
 *   size       width and height in px, or any CSS size (default 160)
 *   className / style
 */
export default function EmberHead({ state = 'idle', amplitude = 0, alert = false, accent = '#7fb8ff', size = 160, className = '', style }) {
    const hostRef = useRef(null);
    const busRef = useRef(null);
    const initial = useRef({ state, amplitude, alert });

    useEffect(() => {
        const host = hostRef.current;
        const bus = createBus();
        busRef.current = bus;

        const ember = new Ember({ scene: new THREE.Scene(), bus, host });
        ember.dock(host); // creates its own transparent renderer inside `host`
        bus.emit('agent:state', initial.current.state);
        bus.emit('agent:amplitude', initial.current.amplitude);
        bus.emit('verdict:update', initial.current.alert ? 100 : 0);

        let raf = 0, last = performance.now(), disposed = false;
        (function loop(now) {
            if (disposed) return;
            raf = requestAnimationFrame(loop);
            const dt = Math.min((now - last) / 1000, 0.05); last = now;
            ember.tick(dt);
        })(last);

        const ro = new ResizeObserver(() => {
            const d = ember.docked; if (!d) return;
            const w = host.clientWidth || 1, h = host.clientHeight || 1;
            d.r.setSize(w, h); d.c.aspect = w / h; d.c.updateProjectionMatrix();
            d.r.render(d.s, d.c); // setSize clears the canvas, so redraw immediately before paint
        });
        ro.observe(host);

        return () => {
            disposed = true;
            cancelAnimationFrame(raf);
            ro.disconnect();
            ember.undock();
            busRef.current = null;
        };
    }, []);

    useEffect(() => { busRef.current?.emit('agent:state', state); }, [state]);
    useEffect(() => { busRef.current?.emit('agent:amplitude', amplitude); }, [amplitude]);
    useEffect(() => { busRef.current?.emit('verdict:update', alert ? 100 : 0); }, [alert]);
    useEffect(() => {
        hostRef.current?.style.setProperty('--accent', accent);
        busRef.current?.emit('category:select');
    }, [accent]);

    const dim = typeof size === 'number' ? size + 'px' : size;
    return <div ref={hostRef} className={className} style={{ width: dim, height: dim, ...style }} />;
}
