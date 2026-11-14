export const HOME_ACCENT = '#7fb8ff';

export const ENV_ORDER = ['spacecraft', 'habitat', 'suit'];

export const ENVIRONMENTS = {
    spacecraft: { id: 'spacecraft', name: 'Spacecraft', short: 'Craft', o2: 21, psi: 14.7 },
    habitat: { id: 'habitat', name: 'Moon Habitat', short: 'Habitat', o2: 30, psi: 10.2 },
    suit: { id: 'suit', name: 'Space Suit', short: 'Suit', o2: 100, psi: 4.3 },
};

export const CATEGORY_ORDER = ['prevention', 'flammability', 'detection', 'suppression'];

export const CATEGORIES = {
    prevention: {
        id: 'prevention', name: 'Prevention', short: 'Prevention', accent: '#ffe14d',
        aliases: ['ignition', 'materials', 'material', 'ignition sources', 'material selection'],
    },
    flammability: {
        id: 'flammability', name: 'Flammability & Fire Behavior', short: 'Flammability', accent: '#ff6a2a',
        aliases: ['flame-spread', 'flame spread', 'flame', 'spread', 'fire behavior', 'environment', 'env'],
    },
    detection: {
        id: 'detection', name: 'Detection', short: 'Detection', accent: '#b79cff',
        aliases: ['smoke', 'aerosol', 'smoke and aerosol sensing'],
    },
    suppression: {
        id: 'suppression', name: 'Suppression', short: 'Suppression', accent: '#9fe8ff',
        aliases: ['extinction', 'extinct', 'extinguishing', 'recovery'],
    },
};

// "Flame" | "flame-spread" | "Smoke" | "env" ... -> id or null
export function resolveCategory(raw) {
    if (!raw) return null;
    const q = String(raw).trim().toLowerCase();
    return CATEGORY_ORDER.find((id) => {
        const c = CATEGORIES[id];
        return [c.id, c.name, c.short, ...c.aliases].some((s) => s.toLowerCase() === q);
    }) || null;
}