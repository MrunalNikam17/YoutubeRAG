/** @type {import('tailwindcss').Config} */
export default {
    content: ['./sidepanel.html', './src/**/*.{ts,tsx,html}'],
    theme: {
        extend: {
            colors: {
                panel: {
                    950: '#020617',
                    900: '#0f172a',
                    800: '#1e293b',
                    700: '#334155',
                    600: '#475569',
                    500: '#64748b',
                    200: '#e2e8f0',
                    100: '#f1f5f9',
                },
                accent: {
                    500: '#8b5cf6',
                    400: '#a78bfa',
                    300: '#c4b5fd',
                },
            },
            boxShadow: {
                glow: '0 0 30px rgba(139, 92, 246, 0.18)',
            },
        },
    },
    plugins: [],
};
