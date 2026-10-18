import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import path from 'node:path';
import fs from 'node:fs';

function copyManifestPlugin() {
    return {
        name: 'copy-manifest-to-dist',
        writeBundle() {
            const source = path.resolve(__dirname, 'manifest.json');
            const destination = path.resolve(__dirname, 'dist', 'manifest.json');
            fs.mkdirSync(path.dirname(destination), { recursive: true });
            fs.copyFileSync(source, destination);
        },
    };
}

export default defineConfig({
    plugins: [react(), copyManifestPlugin()],
    publicDir: 'public',
    build: {
        outDir: 'dist',
        emptyOutDir: true,
        sourcemap: true,
        rollupOptions: {
            input: {
                sidepanel: path.resolve(__dirname, 'sidepanel.html'),
                content: path.resolve(__dirname, 'src/content/index.ts'),
                serviceWorker: path.resolve(__dirname, 'src/background/serviceWorker.ts'),
            },
            output: {
                entryFileNames: 'assets/[name].js',
                chunkFileNames: 'assets/[name]-[hash].js',
                assetFileNames: 'assets/[name][extname]',
            },
        },
    },
    resolve: {
        alias: {
            '@': path.resolve(__dirname, 'src'),
        },
    },
    test: {
        environment: 'jsdom',
        include: ['src/**/*.test.{ts,tsx}'],
    },
});
