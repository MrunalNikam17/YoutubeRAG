interface CurrentVideoState {
    videoId: string;
    title: string;
    url: string;
    isShorts: boolean;
    timestamp: number;
}

const VIDEO_ID_REGEX = /^[A-Za-z0-9_-]{11}$/;

function extractVideoIdFromUrl(input: string): string | null {
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

function extractVideoIdFromLocation(locationHref: string): string | null {
    return extractVideoIdFromUrl(locationHref);
}

function isYouTubeHost(hostname: string): boolean {
    return hostname.includes('youtube.com') || hostname.includes('youtu.be');
}

function getCurrentYouTubeInfo() {
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

function publishState() {
    const info = getCurrentYouTubeInfo();
    const state: CurrentVideoState | null = info
        ? { ...info, timestamp: Date.now() }
        : null;

    void chrome.runtime.sendMessage({ type: 'YT_VIDEO_CHANGED', payload: state });
    void chrome.storage.session.set({ currentVideoState: state });
}

function watchUrlChanges() {
    let lastVideoId = extractVideoIdFromLocation(window.location.href);

    const emitIfChanged = () => {
        const nextVideoId = extractVideoIdFromLocation(window.location.href);
        if (nextVideoId !== lastVideoId) {
            lastVideoId = nextVideoId;
            publishState();
        }
    };

    const originalPushState = history.pushState;
    history.pushState = function (...args) {
        const result = originalPushState.apply(this, args as Parameters<History['pushState']>);
        window.dispatchEvent(new Event('yt-url-changed'));
        return result;
    };

    const originalReplaceState = history.replaceState;
    history.replaceState = function (...args) {
        const result = originalReplaceState.apply(this, args as Parameters<History['replaceState']>);
        window.dispatchEvent(new Event('yt-url-changed'));
        return result;
    };

    window.addEventListener('popstate', emitIfChanged);
    window.addEventListener('yt-url-changed', emitIfChanged as EventListener);

    const observer = new MutationObserver(() => {
        emitIfChanged();
    });
    observer.observe(document.documentElement, { childList: true, subtree: true });

    setInterval(emitIfChanged, 1000);
}

if (isYouTubeHost(window.location.hostname)) {
    publishState();
    watchUrlChanges();
}
