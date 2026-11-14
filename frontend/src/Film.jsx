import { lazy, Suspense, useCallback, useEffect, useRef, useState } from 'react';
import { Route, Routes, useLocation } from 'react-router-dom';
import { LiveKitRoom } from '@livekit/components-react';
import OpenningScene from './openningScene/OpenningScene.jsx';
import { DashboardProvider } from './coreSolution/DashboardContext.jsx';
// heavy routes load on demand so the opening scene shows up fast
const CabinView = lazy(() => import('./cabinScene/CabinScene.jsx'));
const FlameApp = lazy(() => import('./coreSolution/FlameApp.jsx'));
const About = lazy(() => import('./about/About.jsx'));
import { DeafenProvider, DeafenAudioRenderer } from './coreSolution/DeafenContext.jsx';

const API_URL = import.meta.env.VITE_API_URL || '';
const RETRY_MS = 3000;
// One token per page load (Round 12 item 9): a second request within 15 s reuses the first one, so a remount can never start a second agent session.
let sharedToken = null, sharedAt = 0;
function fetchToken() {
    if (sharedToken && Date.now() - sharedAt < 15000) return sharedToken;
    sharedAt = Date.now();
    sharedToken = fetch(`${API_URL}/api/token`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({}) })
        .then((res) => { if (!res.ok) throw new Error(`Token request failed (${res.status})`); return res.json(); })
        .catch((e) => { sharedToken = null; throw e; });
    return sharedToken;
}

export default function Film() {
    const [conn, setConn] = useState(null); // { server_url, participant_token }
    const [retry, setRetry] = useState(0);
    const connRef = useRef(null);
    const pending = useRef(null);           // in-flight token request, shared by every caller
    const gen = useRef(0);   // add next to connRef / pending

    const connect = useCallback(() => {
        if (connRef.current) return Promise.resolve(connRef.current);
        if (pending.current) return pending.current;
        const myGen = gen.current;
        pending.current = (async () => {
            try {
                const data = await fetchToken();
                if (myGen !== gen.current) return null;   // disconnected meanwhile: drop it
                connRef.current = data;
                setConn(data);
                return data;
            } finally {
                if (myGen === gen.current) pending.current = null;
            }
        })();
        return pending.current;
    }, []);

    const disconnect = useCallback(() => {
        gen.current++;            // invalidates any in-flight request
        sharedToken = null;
        connRef.current = null;
        pending.current = null;
        setConn(null);
    }, []);
    const location = useLocation();
    const { pathname } = location;

    // About is an overlay: keep rendering the page it was opened from underneath it.
    const isAbout = pathname === '/about';
    const routesLocation = isAbout
        ? (location.state?.backgroundLocation ??
            { pathname: '/home', search: '', hash: '', state: null, key: 'about-bg' }) // opened /about directly
        : location;
    useEffect(() => {
        document.title =
            pathname === '/home' ? 'Cabin · Flame in Freefall'
                : pathname === '/solution' ? 'Dashboard · Flame in Freefall'
                    : pathname === '/about' ? 'About · Flame in Freefall'
                        : 'Flame in Freefall';
    }, [pathname]);

    connRef.current = conn;

    // Any page except the opening scene: if not connected, try to connect (retry on failure).
    useEffect(() => {
        if (pathname === '/' || conn) return;
        let t;
        connect().catch((e) => {
            console.warn('[connect] failed, retrying:', e.message);
            t = setTimeout(() => setRetry((n) => n + 1), RETRY_MS);
        });
        return () => clearTimeout(t);
    }, [pathname, conn, retry, connect]);

    return (
        <LiveKitRoom
            serverUrl={conn?.server_url}
            token={conn?.participant_token}
            connect={!!conn}
            audio
            video={false}
            onDisconnected={() => setConn(null)}
        >
            <DeafenProvider>
                <DashboardProvider>
                    <Suspense fallback={<div style={{ position: 'fixed', inset: 0, background: '#05080f' }} />}>
                    <Routes location={routesLocation}>
                        <Route path="/" element={<OpenningScene onConnect={connect} onDisconnect={disconnect} />} />
                        <Route path="/home" element={
                            <div style={{ width: '100vw', height: '100vh' }}>
                                <CabinView showStateSwitcher={false} intro="Welcome I am Flamo" />
                            </div>
                        } />
                        <Route path="/solution" element={
                            <div style={{ width: '100vw', height: '100vh' }}>
                                <FlameApp />
                            </div>
                        } />
                    </Routes>
                    {isAbout && <About />}
                    </Suspense>
                </DashboardProvider>
                <DeafenAudioRenderer />
            </DeafenProvider>
        </LiveKitRoom>
    );
}