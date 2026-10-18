export interface ApiSource {
    start_time: number;
    end_time: number;
    excerpt?: string | null;
    language?: string | null;
}

export interface VideoLoadResponse {
    success: boolean;
    video_id: string;
    language: string;
    normalized_language: string;
    translated: boolean;
    message: string;
    title?: string | null;
}

export interface ChatResponse {
    success: boolean;
    video_id: string;
    session_id: string;
    answer: string;
    sources: ApiSource[];
    language: string;
    normalized_language: string;
    translated: boolean;
    message: string;
}

export interface ChatRequestPayload {
    video_id: string;
    question: string;
    session_id: string;
}

export interface VideoSummarySection {
    start_time: number;
    end_time: number;
    summary: string;
}

export interface VideoSummaryResponse {
    success: boolean;
    video_id: string;
    summary: string;
    sections: VideoSummarySection[];
    message: string;
}

const CANDIDATE_BACKEND_URLS = [
    'http://127.0.0.1:8001',
    'http://127.0.0.1:8000',
    'http://localhost:8001',
    'http://localhost:8000',
    'http://127.0.0.1:8002',
    'http://localhost:8002',
];

let activeBackendUrl: string | null = null;

async function checkUrlHealth(url: string, timeoutMs = 2000): Promise<boolean> {
    try {
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), timeoutMs);
        const response = await fetch(`${url}/api/health`, {
            signal: controller.signal,
        });
        clearTimeout(timer);
        return response.ok;
    } catch {
        return false;
    }
}

export async function detectBackendUrl(): Promise<string> {
    if (activeBackendUrl && (await checkUrlHealth(activeBackendUrl))) {
        return activeBackendUrl;
    }

    const configured = (import.meta.env.VITE_BACKEND_URL as string | undefined)?.trim();
    if (configured && (await checkUrlHealth(configured))) {
        activeBackendUrl = configured;
        return configured;
    }

    try {
        if (typeof chrome !== 'undefined' && chrome.storage?.local) {
            const stored = await chrome.storage.local.get('customBackendUrl');
            const saved = stored.customBackendUrl as string | undefined;
            if (saved?.trim() && (await checkUrlHealth(saved.trim()))) {
                activeBackendUrl = saved.trim();
                return activeBackendUrl;
            }
        }
    } catch {
        // Ignore storage access errors
    }

    for (const url of CANDIDATE_BACKEND_URLS) {
        if (await checkUrlHealth(url)) {
            activeBackendUrl = url;
            try {
                if (typeof chrome !== 'undefined' && chrome.storage?.local) {
                    await chrome.storage.local.set({ customBackendUrl: url });
                }
            } catch {
                // Ignore storage errors
            }
            return url;
        }
    }

    return activeBackendUrl || CANDIDATE_BACKEND_URLS[0];
}

export async function getBackendUrl(): Promise<string> {
    if (activeBackendUrl) {
        return activeBackendUrl;
    }
    return detectBackendUrl();
}

async function readJsonResponse<T>(response: Response): Promise<T> {
    const payload = await response.json().catch(() => null);
    if (!response.ok) {
        const detail = payload?.detail || payload?.message || response.statusText || 'Request failed';
        throw new Error(detail);
    }
    return payload as T;
}

async function requestHeaders(): Promise<Record<string, string>> {
    const headers: Record<string, string> = { 'Content-Type': 'application/json' };
    if (typeof chrome !== 'undefined' && chrome.storage?.local) {
        const stored = await chrome.storage.local.get('apiKey');
        const apiKey = typeof stored.apiKey === 'string' ? stored.apiKey.trim() : '';
        if (apiKey) {
            headers['X-API-Key'] = apiKey;
        }
    }
    return headers;
}

export async function loadVideo(videoId: string): Promise<VideoLoadResponse> {
    const baseUrl = await getBackendUrl();
    const response = await fetch(`${baseUrl}/api/video/load`, {
        method: 'POST',
        headers: await requestHeaders(),
        body: JSON.stringify({ video_id: videoId }),
    });
    return readJsonResponse<VideoLoadResponse>(response);
}

export async function askQuestion(payload: ChatRequestPayload): Promise<ChatResponse> {
    const baseUrl = await getBackendUrl();
    const response = await fetch(`${baseUrl}/api/chat`, {
        method: 'POST',
        headers: await requestHeaders(),
        body: JSON.stringify(payload),
    });
    return readJsonResponse<ChatResponse>(response);
}

export async function getVideoSummary(videoId: string): Promise<VideoSummaryResponse> {
    const baseUrl = await getBackendUrl();
    const response = await fetch(`${baseUrl}/api/video/summary`, {
        method: 'POST',
        headers: await requestHeaders(),
        body: JSON.stringify({ video_id: videoId }),
    });
    return readJsonResponse<VideoSummaryResponse>(response);
}

export async function pingBackend(): Promise<boolean> {
    const url = await detectBackendUrl();
    return checkUrlHealth(url);
}

export function getBackendBaseUrl(): string {
    return activeBackendUrl || CANDIDATE_BACKEND_URLS[0];
}
