// The chat log's bookkeeping, separate from the DOM so it can be tested.
//
// Live-test bug: bubbles were keyed only by the transcription segment id. When an id came back in a later turn
// (or a finished segment was delivered again) the new text overwrote an older bubble higher up the log.
//
// Rules:
//   - a bubble is keyed by role + segment id + how often that id has started a bubble before;
//   - once a segment is final, or the other speaker has spoken since, its bubble is frozen: the same text again is ignored;
//   - a final segment's id coming back with DIFFERENT text is a new bubble at the bottom, never an overwrite;
//   - earlier bubbles never move and are never cleared (only the 100-bubble cap removes the oldest).

export function createChatLog({ debug = false, log = console.debug } = {}) {
    const bubbles = new Map();          // key -> { text, final, seq }
    const reuse = new Map();            // role|id -> how many times this id started a new bubble
    let turn = 0, lastRole = null, seq = 0;

    /** @returns {{action: 'create'|'update'|'ignore', key: string, role: string, text: string, final: boolean}} */
    function upsert(role, id, text, final = false) {
        role = role === 'me' ? 'me' : 'ai';
        const base = `${role}|${id}`;
        if (debug) log('[chat] segment', { role, id, final, text: String(text).slice(0, 40), turn });
        let n = reuse.get(base) ?? 0;
        let key = `${base}|${n}`;
        const b = bubbles.get(key);
        if (b) {
            if (b.final || b.turn !== turn) {
                if (b.text === text) return { action: 'ignore', key, role, text, final };      // a replay of a finished bubble
                // the id came back with other text: a new bubble (keyed by the id's next use), the old one stays as it was
                reuse.set(base, ++n); key = `${base}|${n}`;
            } else {
                b.text = text; b.final = !!final;
                return { action: 'update', key, role, text, final: !!final };
            }
        }
        if (role !== lastRole) { turn++; lastRole = role; }
        bubbles.set(key, { text, final: !!final, turn, seq: ++seq });
        return { action: 'create', key, role, text, final: !!final };
    }
    return { upsert, size: () => bubbles.size };
}

/** Scroll to the bottom only if the reader is already near it. */
export const nearBottom = (el, slack = 64) => el.scrollHeight - el.scrollTop - el.clientHeight <= slack;
