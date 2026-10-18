export interface YoutubeVideoInfo {
    videoId: string;
    title: string;
    url: string;
    isShorts: boolean;
}

const VIDEO_ID_REGEX = /^[A-Za-z0-9_-]{11}$/;

export function extractVideoIdFromUrl(input: string): string | null {
    if (!input) {
        return null;
    }

    const trimmed = input.trim();
    if (VIDEO_ID_REGEX.test(trimmed)) {
        return trimmed;
    }

    try {
        const url = new URL(trimmed);
        const host = url.hostname.toLowerCase();
        const candidate = url.searchParams.get('v');
        if (candidate && VIDEO_ID_REGEX.test(candidate)) {
            return candidate;
        }

        if (host.includes('youtu.be')) {
            const shortId = url.pathname.split('/').filter(Boolean)[0];
            if (shortId && VIDEO_ID_REGEX.test(shortId)) {
                return shortId;
            }
        }

        if (url.pathname.startsWith('/shorts/')) {
            const shortsId = url.pathname.split('/').filter(Boolean)[1];
            if (shortsId && VIDEO_ID_REGEX.test(shortsId)) {
                return shortsId;
            }
        }

        if (url.pathname.startsWith('/embed/')) {
            const embedId = url.pathname.split('/').filter(Boolean)[1];
            if (embedId && VIDEO_ID_REGEX.test(embedId)) {
                return embedId;
            }
        }
    } catch {
        return null;
    }

    return null;
}

export function extractVideoIdFromLocation(locationHref: string): string | null {
    return extractVideoIdFromUrl(locationHref);
}

export function isYouTubeHost(hostname: string): boolean {
    return hostname.includes('youtube.com') || hostname.includes('youtu.be');
}

export function formatTimestamp(totalSeconds: number): string {
    const seconds = Math.max(0, Math.floor(totalSeconds));
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    const remainingSeconds = seconds % 60;

    if (hours > 0) {
        return `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:${String(remainingSeconds).padStart(2, '0')}`;
    }

    return `${String(minutes).padStart(2, '0')}:${String(remainingSeconds).padStart(2, '0')}`;
}

export function buildTimestampUrl(videoId: string, totalSeconds: number): string {
    const seconds = Math.max(0, Math.floor(totalSeconds));
    return `https://www.youtube.com/watch?v=${videoId}&t=${seconds}s`;
}

export function getCurrentYouTubeInfo(): YoutubeVideoInfo | null {
    if (typeof window === 'undefined' || !isYouTubeHost(window.location.hostname)) {
        return null;
    }

    const videoId = extractVideoIdFromLocation(window.location.href);
    if (!videoId) {
        return null;
    }

    const title = document.title.replace(/\s*-\s*YouTube\s*$/i, '').trim() || 'YouTube video';
    return {
        videoId,
        title,
        url: window.location.href,
        isShorts: window.location.pathname.includes('/shorts/'),
    };
}
