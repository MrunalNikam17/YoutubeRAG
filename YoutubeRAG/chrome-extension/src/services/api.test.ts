import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

describe('extension API service', () => {
    let fetchMock: ReturnType<typeof vi.fn>;

    beforeEach(() => {
        vi.resetModules();
        fetchMock = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
            if (!init?.method || init.method === 'GET') {
                return new Response(JSON.stringify({ status: 'ok' }), { status: 200 });
            }
            if (String(_input).endsWith('/api/video/summary')) {
                return new Response(JSON.stringify({
                    success: true,
                    video_id: 'J5_-l7WIO_w',
                    summary: 'Overview',
                    sections: [{ start_time: 0, end_time: 10, summary: 'Section' }],
                    message: 'ok',
                }), { status: 200 });
            }
            return new Response(JSON.stringify({
                success: true,
                video_id: 'J5_-l7WIO_w',
                language: 'en',
                normalized_language: 'en',
                translated: false,
                message: 'ok',
            }), { status: 200 });
        });
        vi.stubGlobal('fetch', fetchMock);
        vi.stubGlobal('chrome', {
            storage: {
                local: {
                    get: vi.fn(async (key: string) => key === 'apiKey' ? { apiKey: ' test-key ' } : {}),
                    set: vi.fn(),
                },
            },
        });
    });

    afterEach(() => {
        vi.unstubAllGlobals();
        vi.restoreAllMocks();
    });

    it('loads a video with the stored API key', async () => {
        const api = await import('./api');

        const response = await api.loadVideo('J5_-l7WIO_w');

        expect(response.success).toBe(true);
        const request = fetchMock.mock.calls.find(([url]) => String(url).endsWith('/api/video/load'));
        expect(request?.[1]?.headers).toEqual({
            'Content-Type': 'application/json',
            'X-API-Key': 'test-key',
        });
    });

    it('returns summary sections from the summary endpoint', async () => {
        const api = await import('./api');

        const response = await api.getVideoSummary('J5_-l7WIO_w');

        expect(response.summary).toBe('Overview');
        expect(response.sections[0]).toEqual({ start_time: 0, end_time: 10, summary: 'Section' });
    });
});
