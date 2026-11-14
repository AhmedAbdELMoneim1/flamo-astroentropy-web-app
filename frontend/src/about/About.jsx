import { useCallback, useEffect, useRef, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import './About.css';
import { HOME_ACCENT } from '../coreSolution/categories';
import photo1 from '../assets/team/abdullahMostafa.webp';
import photo2 from '../assets/team/ahmedAbdElMoneim.webp';
import photo3 from '../assets/team/ahmedHassan.webp';
import photo4 from '../assets/team/karimAhmed.webp';
import photo5 from '../assets/team/moatazMohammed.webp';

/* ---- edit your team here ---- */
const TEAM = [
    {
        name: 'Abdullah Mostafa',
        role: 'The Director',
        bio: '',
        photo: photo1,
        links: {
            github: 'https://github.com/AbdullahMostafa24',
            linkedin: 'https://www.linkedin.com/in/abdullah-mostafa-8b940934a/'
        }
    },
    {
        name: 'Ahmed AbdElMoneim',
        role: 'Mr Entropy',
        bio: '',
        photo: photo2,
        links: {
            github: 'https://github.com/AhmedAbdELMoneim1',
            linkedin: 'https://www.linkedin.com/in/ahmed-abd-elmoneim-5925642b0/'

        }
    },
    {
        name: 'Ahmed Hassan',
        role: 'Batman',
        bio: '',
        photo: photo3,
        links: {
            github: 'https://github.com/ahmedhassan0a',
            linkedin: 'https://www.linkedin.com/in/ahmed-hassan-789354250/'
        }
    },
    {
        name: 'kaream Ahmed',
        role: 'Mr RAG',
        bio: '',
        photo: photo4,
        links: {
            github: 'https://github.com/Kareamahmed',
            linkedin: 'https://www.linkedin.com/in/kaream-ahmed/'
        }
    },
    {
        name: 'Moataz Mohammed',
        role: 'Diplomat',
        bio: '',
        photo: photo5,
        links: {
            github: 'https://github.com/0xMotazMohamed',
            linkedin: 'https://www.linkedin.com/in/moataz-m-ali-73045b277/'
        }
    },
];

/* ---- edit the solution text here ---- */
const SOLUTION = {
    challenge: 'Describe the NASA challenge in two or three sentences: what problem crews face with fire in microgravity and on the Moon.',
    solution: 'Flame in Freefall is a voice-driven copilot. Crews ask questions out loud, and the system answers with data from NASA microgravity combustion experiments, shown live on a dashboard.',
    steps: [
        { t: 'Ask', d: 'The crew talks to Flamo, the voice agent, or types in the chat.' },
        { t: 'Analyse', d: 'The agent picks a category, sets the conditions (oxygen, pressure, flow, gravity) and finds the matching runs.' },
        { t: 'Show', d: 'The dashboard displays the summary, charts, rankings, run table and safety takeaway. The 3D scene follows the chosen environment.' },
        { t: 'Explore', d: 'The crew moves the sliders and the system updates its answer to the new conditions.' },
    ],
    features: [
        { t: 'Voice copilot', d: 'Hands-free talking with Flamo, with a chat fallback.' },
        { t: 'Six categories', d: 'Flammability, materials, smoke, suppression, ignition and environment, each with its own dashboard.' },
        { t: 'Three environments', d: 'Spacecraft, Moon base and space suit, each with its own atmosphere.' },
        { t: 'Interactive parameters', d: 'Change the conditions and see how the risk changes.' },
    ],
};
const TABS = [
    { id: 'team', label: 'Team', icon: 'M9 11a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM2 20v-1a5 5 0 0 1 5-5h4a5 5 0 0 1 5 5v1M17 11a3 3 0 1 0 0-6M19 20v-1a5 5 0 0 0-3-4.5' },
    { id: 'solution', label: 'Solution', icon: 'M12 2C21 9 19 21 12 21C5 21 3 14 7 9C8 13 10 13 11 11C12 8 10 5 12 2Z' },
];

const FONT_ID = 'flame-dashboard-fonts';
const FONT_HREF = 'https://fonts.googleapis.com/css2?family=Orbitron:wght@500;700&family=Share+Tech+Mono&display=swap';
const SLIDE_MS = 320; // keep in sync with About.css

const GithubIcon = () => (
    <svg viewBox="0 0 24 24" aria-hidden="true" fill="currentColor">
        <path d="M12 .297c-6.63 0-12 5.373-12 12 0 5.303 3.438 9.8 8.205 11.385.6.113.82-.258.82-.577 0-.285-.01-1.04-.015-2.04-3.338.724-4.042-1.61-4.042-1.61C4.422 18.07 3.633 17.7 3.633 17.7c-1.087-.744.084-.729.084-.729 1.205.084 1.838 1.236 1.838 1.236 1.07 1.835 2.809 1.305 3.495.998.108-.776.417-1.305.76-1.605-2.665-.3-5.466-1.332-5.466-5.93 0-1.31.465-2.38 1.235-3.22-.135-.303-.54-1.523.105-3.176 0 0 1.005-.322 3.3 1.23.96-.267 1.98-.399 3-.405 1.02.006 2.04.138 3 .405 2.28-1.552 3.285-1.23 3.285-1.23.645 1.653.24 2.873.12 3.176.765.84 1.23 1.91 1.23 3.22 0 4.61-2.805 5.625-5.475 5.92.42.36.81 1.096.81 2.22 0 1.606-.015 2.896-.015 3.286 0 .315.21.69.825.57C20.565 22.092 24 17.592 24 12.297c0-6.627-5.373-12-12-12" />
    </svg>
);

const LinkedinIcon = () => (
    <svg viewBox="0 0 24 24" aria-hidden="true" fill="currentColor">
        <path d="M20.447 20.452h-3.554v-5.569c0-1.328-.027-3.037-1.852-3.037-1.853 0-2.136 1.445-2.136 2.939v5.667H9.351V9h3.414v1.561h.046c.477-.9 1.637-1.85 3.37-1.85 3.601 0 4.267 2.37 4.267 5.455v6.286zM5.337 7.433c-1.144 0-2.063-.926-2.063-2.065 0-1.138.92-2.063 2.063-2.063 1.14 0 2.064.925 2.064 2.063 0 1.139-.925 2.065-2.064 2.065zm1.782 13.019H3.555V9h3.564v11.452zM22.225 0H1.771C.792 0 0 .774 0 1.729v20.542C0 23.227.792 24 1.771 24h20.451C23.2 24 24 23.227 24 22.271V1.729C24 .774 23.2 0 22.222 0h.003z" />
    </svg>
);

const initials = (n) => n.split(/\s+/).map((w) => w[0]).slice(0, 2).join('').toUpperCase();

export default function About() {
    const navigate = useNavigate();
    const { state } = useLocation();
    const [open, setOpen] = useState(false);
    const [tab, setTab] = useState('team');
    const accent = state?.accent ?? HOME_ACCENT;   // sent by FlameApp; the cabin sends none -> home accent
    const closing = useRef(false);
    const panelRef = useRef(null);

    // slide in on mount
    useEffect(() => {
        if (!document.getElementById(FONT_ID)) {
            const l = document.createElement('link');
            l.id = FONT_ID; l.rel = 'stylesheet'; l.href = FONT_HREF;
            document.head.appendChild(l);
        }
        let id2;
        const id1 = requestAnimationFrame(() => {
            id2 = requestAnimationFrame(() => { setOpen(true); panelRef.current?.focus(); });
        });
        return () => { cancelAnimationFrame(id1); cancelAnimationFrame(id2); };
    }, []);

    // slide out, then leave the route
    const close = useCallback(() => {
        if (closing.current) return;
        closing.current = true;
        setOpen(false);
        setTimeout(() => {
            if (state?.backgroundLocation) navigate(-1);          // back to the page underneath
            else navigate('/home', { replace: true });             // opened /about directly
        }, SLIDE_MS);
    }, [navigate, state]);

    useEffect(() => {
        const onKey = (e) => { if (e.key === 'Escape') close(); };
        window.addEventListener('keydown', onKey);
        return () => window.removeEventListener('keydown', onKey);
    }, [close]);

    return (
        <div className={`ab-root${open ? ' open' : ''}`} style={{ '--a': accent }}>
            <div className="ab-backdrop" onClick={close} />

            <main ref={panelRef} tabIndex={-1} className="ab-panel" role="dialog" aria-modal="true" aria-label="About">
                <header className="ab-head">
                    <div>
                        <span className="ab-kicker">FLAME IN FREEFALL · NASA CHALLENGE</span>
                        <h1>{tab === 'team' ? 'About the team' : 'About the solution'}</h1>
                        <p>An SI-powered copilot that turns NASA microgravity combustion data into fire-safety insights for crews headed to the Moon and Mars.</p>
                    </div>
                    <button type="button" className="ab-close" onClick={close} aria-label="Close about page">✕ CLOSE</button>
                </header>

                <div
                    className="ab-tabs"
                    role="tablist"
                    aria-label="About sections"
                    onKeyDown={(e) => {
                        if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
                            e.preventDefault();
                            setTab((t) => (t === 'team' ? 'solution' : 'team'));
                        }
                    }}
                >
                    {TABS.map((t) => (
                        <button
                            key={t.id}
                            type="button"
                            role="tab"
                            className="ab-tab"
                            aria-selected={tab === t.id}
                            tabIndex={tab === t.id ? 0 : -1}
                            onClick={() => setTab(t.id)}
                        >
                            <svg viewBox="0 0 24 24" aria-hidden="true"><path d={t.icon} /></svg>
                            <span>{t.label}</span>
                        </button>
                    ))}
                </div>

                {tab === 'team' ? (
                    <section className="ab-grid" role="tabpanel">
                        {TEAM.map((m) => (
                            <article className="ab-card ab-member" key={m.name}>
                                <div className="ab-ava">
                                    {m.photo ? <img src={m.photo} alt={m.name} /> : <span>{initials(m.name)}</span>}
                                </div>
                                <h2>{m.name}</h2>
                                <h3>{m.role}</h3>
                                <p>{m.bio}</p>
                                {(m.links?.github || m.links?.linkedin) && (
                                    <div className="ab-links">
                                        {m.links?.github && (
                                            <a href={m.links.github} target="_blank" rel="noreferrer" aria-label={`${m.name} on GitHub`} title="GitHub">
                                                <GithubIcon />
                                            </a>
                                        )}
                                        {m.links?.linkedin && (
                                            <a href={m.links.linkedin} target="_blank" rel="noreferrer" aria-label={`${m.name} on LinkedIn`} title="LinkedIn">
                                                <LinkedinIcon />
                                            </a>
                                        )}
                                    </div>
                                )}
                            </article>
                        ))}
                    </section>
                ) : (
                    <section className="ab-sol" role="tabpanel">
                        <article className="ab-block">
                            <h3>The challenge</h3>
                            <p>{SOLUTION.challenge}</p>
                        </article>
                        <article className="ab-block">
                            <h3>Our solution</h3>
                            <p>{SOLUTION.solution}</p>
                        </article>
                        <article className="ab-block">
                            <h3>How it works</h3>
                            <ol className="ab-steps">
                                {SOLUTION.steps.map((s) => (
                                    <li key={s.t}><b>{s.t}</b><span>{s.d}</span></li>
                                ))}
                            </ol>
                        </article>
                        <div className="ab-feats">
                            {SOLUTION.features.map((f) => (
                                <article className="ab-card ab-feat" key={f.t}>
                                    <h2>{f.t}</h2>
                                    <p>{f.d}</p>
                                </article>
                            ))}
                        </div>
                    </section>
                )}
            </main>
        </div>
    );
}