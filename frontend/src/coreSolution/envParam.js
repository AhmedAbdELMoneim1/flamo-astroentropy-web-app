// URL value <-> backend scenario id
const URL_TO_SCEN = { iss: 'iss', moonbase: 'moon_base', spacesuit: 'spacesuit' };
const SCEN_TO_URL = { iss: 'iss', moon_base: 'moonbase', spacesuit: 'spacesuit' };

export const DEFAULT_SCENARIO = 'iss';

// scenario id from the URL, or null if missing/unknown
export function readEnvUrl() {
    const raw = new URLSearchParams(window.location.search).get('env');
    return URL_TO_SCEN[String(raw ?? '').trim().toLowerCase()] ?? null;
}

// put the scenario in the URL (pushState, same as the category param)
export function writeEnvUrl(scenario) {
    const value = SCEN_TO_URL[scenario];
    if (!value) return;
    const url = new URL(window.location.href);
    if (url.searchParams.get('env') === value) return;
    url.searchParams.set('env', value);
    window.history.pushState(null, '', url);
}