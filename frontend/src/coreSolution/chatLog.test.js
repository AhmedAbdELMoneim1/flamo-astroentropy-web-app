import { describe, it, expect } from 'vitest';
import { createChatLog, nearBottom } from './chatLog.js';

// The behaviour before the fix, kept here to reproduce the live-test bug: one bubble per segment id, for ever.
function legacy() {
    const m = new Map(), texts = [];
    return { texts, upsert(id, text) { if (!m.has(id)) { m.set(id, texts.length); texts.push(''); } texts[m.get(id)] = text; } };
}
// what the DOM would show: apply the actions in order
function dom(chat) {
    const bubbles = new Map(), order = [];
    return { order, bubbles, send(role, id, text, final) {
        const r = chat.upsert(role, id, text, final);
        if (r.action === 'create') { bubbles.set(r.key, r.text); order.push(r.key); }
        else if (r.action === 'update') bubbles.set(r.key, r.text);
        return r;
    }, texts: () => order.map((k) => bubbles.get(k)) };
}

describe('chat bubbles with repeated segment ids', () => {
    it('reproduces the bug: the old keying overwrites an earlier bubble', () => {
        const l = legacy();
        l.upsert('SG_1', 'Hello, I am Flamo.');
        l.upsert('SG_2', 'What is BRE?');
        l.upsert('SG_1', 'BRE is an experiment.');      // the id comes back in a later turn
        expect(l.texts).toEqual(['BRE is an experiment.', 'What is BRE?']);   // the greeting is gone, the answer sits at the top
    });

    it('a reused id after a final segment is a new bubble at the bottom; the old one is untouched', () => {
        const d = dom(createChatLog());
        d.send('ai', 'SG_1', 'Hello, I am Flamo.', true);
        d.send('me', 'SG_2', 'What is BRE?', true);
        d.send('ai', 'SG_1', 'BRE is an experiment.', false);
        expect(d.texts()).toEqual(['Hello, I am Flamo.', 'What is BRE?', 'BRE is an experiment.']);
    });

    it('a growing segment stays one bubble, then freezes when final', () => {
        const d = dom(createChatLog());
        d.send('ai', 'A', 'BRE is', false); d.send('ai', 'A', 'BRE is an experiment', false); d.send('ai', 'A', 'BRE is an experiment.', true);
        expect(d.texts()).toEqual(['BRE is an experiment.']);
        expect(d.send('ai', 'A', 'BRE is an experiment.', true).action).toBe('ignore');   // the hook delivers every segment again
        expect(d.texts()).toHaveLength(1);
    });

    it('delivering all earlier segments again on every update changes nothing', () => {
        const d = dom(createChatLog());
        const segs = [['ai', 'S1', 'Hi.', true], ['me', 'S2', 'Ask.', true], ['ai', 'S3', 'Answer', false]];
        for (let i = 0; i < 4; i++) segs.forEach(([r, id, t, f]) => d.send(r, id, t, f));
        expect(d.texts()).toEqual(['Hi.', 'Ask.', 'Answer']);
    });

    it('an unfinished segment is frozen once the other speaker has spoken', () => {
        const d = dom(createChatLog());
        d.send('ai', 'X', 'Part one', false);
        d.send('me', 'Y', 'Interrupt', true);
        d.send('ai', 'X', 'A different answer', false);
        expect(d.texts()).toEqual(['Part one', 'Interrupt', 'A different answer']);
    });

    it('the same id for me and ai are different bubbles', () => {
        const d = dom(createChatLog());
        d.send('me', '1', 'question', true); d.send('ai', '1', 'answer', true);
        expect(d.texts()).toEqual(['question', 'answer']);
    });

    it('logs segment ids and final flags when debugging', () => {
        const lines = []; const c = createChatLog({ debug: true, log: (...a) => lines.push(a) });
        c.upsert('ai', 'S9', 'hello', true);
        expect(lines[0][1]).toMatchObject({ role: 'ai', id: 'S9', final: true });
    });

    it('scrolls only when the reader is near the bottom', () => {
        expect(nearBottom({ scrollHeight: 1000, scrollTop: 880, clientHeight: 100 })).toBe(true);
        expect(nearBottom({ scrollHeight: 1000, scrollTop: 300, clientHeight: 100 })).toBe(false);
    });
});
