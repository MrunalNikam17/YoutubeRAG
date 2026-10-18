import { extractVideoIdFromUrl } from '../utils/youtube';

interface VideoState {
    videoId: string;
    title: string;
    url: string;
    isShorts: boolean;
    timestamp: number;
}

function tabToVideoState(tab: chrome.tabs.Tab | undefined): VideoState | null {
    if (!tab?.url) {
        return null;
    }
    const videoId = extractVideoIdFromUrl(tab.url);
    if (!videoId) {
        return null;
    }
    const title = (tab.title ?? 'YouTube video').replace(/\s*-\s*YouTube\s*$/i, '').trim() || 'YouTube video';
    return {
        videoId,
        title,
        url: tab.url,
        isShorts: tab.url.includes('/shorts/'),
        timestamp: Date.now(),
    };
}

async function setVideoState(state: VideoState | null) {
    try {
        const current = await getVideoState();
        if (current?.videoId === state?.videoId) {
            return;
        }
        await chrome.storage.session.set({ currentVideoState: state });
    } catch {
        // Fallback for storage errors
    }
}

async function getVideoState(): Promise<VideoState | null> {
    try {
        const result = await chrome.storage.session.get('currentVideoState');
        return (result.currentVideoState as VideoState | null) ?? null;
    } catch {
        return null;
    }
}

// Enable opening the side panel when the extension icon is clicked
if (chrome.sidePanel?.setPanelBehavior) {
    chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true }).catch(() => {});
}

chrome.runtime.onInstalled.addListener(async () => {
    try {
        const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
        const state = tabToVideoState(tab);
        await setVideoState(state);
    } catch {
        // Ignore initialization errors
    }
});

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (message?.type === 'YT_VIDEO_CHANGED') {
        void setVideoState(message.payload as VideoState | null);
        sendResponse({ ok: true });
        return true;
    }

    if (message?.type === 'GET_CURRENT_VIDEO_STATE') {
        void getVideoState().then((state) => sendResponse({ ok: true, state })).catch((error) => sendResponse({ ok: false, error: String(error) }));
        return true;
    }

    return false;
});

chrome.tabs.onActivated.addListener(async (activeInfo) => {
    try {
        const tab = await chrome.tabs.get(activeInfo.tabId);
        const state = tabToVideoState(tab);
        if (state) {
            await setVideoState(state);
        }
    } catch {
        // Tab might not be accessible
    }
});

chrome.tabs.onUpdated.addListener(async (tabId, changeInfo, tab) => {
    if (changeInfo.url || changeInfo.status === 'complete') {
        try {
            const [activeTab] = await chrome.tabs.query({ active: true, currentWindow: true });
            if (activeTab && activeTab.id === tabId) {
                const state = tabToVideoState(tab);
                if (state) {
                    await setVideoState(state);
                }
            }
        } catch {
            // Ignore tab query errors
        }
    }
});

