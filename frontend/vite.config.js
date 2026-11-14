import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
    plugins: [react()],
    server: {
        allowedHosts: true,

        port: 5173,
        // // forwards /api/* to FastAPI, so no CORS trouble in dev
        proxy: { '/api': 'http://localhost:8000' },
        // // proxy: {
        // //     '/api': 'http://127.0.0.1:8000'
        // // },
    },
    assetsInclude: ['**/*.glb'],
    build: {
        chunkSizeWarningLimit: 900,
        rollupOptions: {
            output: {
                manualChunks(id) {
                    if (id.includes('node_modules/three')) return 'three';
                    if (id.includes('livekit')) return 'livekit';
                    if (id.includes('node_modules/react')) return 'react';
                },
            },
        },
    },
});
