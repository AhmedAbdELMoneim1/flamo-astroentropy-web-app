import { useCallback, useEffect, useState } from 'react';
import { CATEGORIES, resolveCategory } from './categories';

const readUrl = () =>
    resolveCategory(new URLSearchParams(window.location.search).get('cat'));

const urlCat = () => resolveCategory(new URLSearchParams(window.location.search).get('cat'));

export function useCategoryParam(fallback = 'flame-spread') {
    const [category, setCat] = useState(() => readUrl() ?? fallback);

    // browser back/forward
    useEffect(() => {
        const onPop = () => setCat(readUrl() ?? fallback);
        window.addEventListener('popstate', onPop);
        return () => window.removeEventListener('popstate', onPop);
    }, [fallback]);

    const setCategory = useCallback((id) => {
        if (!CATEGORIES[id]) return;
        setCat(id);
        const url = new URL(window.location.href);
        if (url.searchParams.get('cat') === CATEGORIES[id].short) return;
        url.searchParams.set('cat', CATEGORIES[id].short);
        window.history.pushState(null, '', url);
    }, []);

    return [category, setCategory];
}