import { useEffect, useMemo, useRef, useState } from 'react';

import { askQuestion, loadVideo, pingBackend } from '../services/api';
import { buildTimestampUrl, extractVideoIdFromUrl } from '../utils/youtube';
import type { ChatEntry, CurrentVideoState } from '../types';
import { ChatWindow } from '../components/ChatWindow';
import { ErrorMessage } from '../components/ErrorMessage';
import { InputBox } from '../components/InputBox';
import { LoadingState } from '../components/LoadingState';
import { VideoInfo } from '../components/VideoInfo';

interface StoredSessionState {
    currentVideoState: CurrentVideoState | null;
}

function tabToVideoState(tab: any): CurrentVideoState | null {
    if (!tab.url) {
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

function createId() {
    return crypto.randomUUID();
}

async function getOrCreateSessionId(): Promise<string> {
    const sessionStored = await chrome.storage.session.get('yt-chat-session-id');
    const localStored = await chrome.storage.local.get('yt-chat-session-id');
    const storedId = sessionStored['yt-chat-session-id'] ?? localStored['yt-chat-session-id'];
    if (storedId) {
        const id = storedId as string;
        await chrome.storage.session.set({ 'yt-chat-session-id': id });
        return id;
    }
    const next = createId();
    await chrome.storage.local.set({ 'yt-chat-session-id': next });
    await chrome.storage.session.set({ 'yt-chat-session-id': next });
    return next;
}

export function App() {
    const [sessionId, setSessionId] = useState<string>('');
    const [video, setVideo] = useState<CurrentVideoState | null>(null);
    const [messages, setMessages] = useState<ChatEntry[]>([]);
    const [isChatHydrated, setIsChatHydrated] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [loadStatus, setLoadStatus] = useState('Detecting video...');
    const [languageLabel, setLanguageLabel] = useState('Waiting for transcript');
    const [translated, setTranslated] = useState(false);
    const [videoReady, setVideoReady] = useState(false);
    const [isLoadingVideo, setIsLoadingVideo] = useState(false);
    const [isSending, setIsSending] = useState(false);
    const [backendOnline, setBackendOnline] = useState<boolean | null>(null);

    const lastLoadedVideoId = useRef<string | null>(null);
    const previousVideoId = useRef<string | null>(null);
    const hydratedVideoId = useRef<string | null>(null);
    const activeRequestId = useRef<string | null>(null);
    const messagesRef = useRef<ChatEntry[]>([]);

    const updateMessages = (
        update: (current: ChatEntry[]) => ChatEntry[],
        videoId = video?.videoId,
    ): Promise<void> => {
        const nextMessages = update(messagesRef.current);
        messagesRef.current = nextMessages;
        setMessages(nextMessages);
        if (videoId && hydratedVideoId.current === videoId) {
            return chrome.storage.session.set({ [`chat:${videoId}`]: nextMessages });
        }
        return Promise.resolve();
    };

    const syncActiveTab = async () => {
        try {
            let tabs = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
            if (!tabs.length || !tabs[0]?.url) {
                tabs = await chrome.tabs.query({ active: true, currentWindow: true });
            }
            const tab = tabs[0];
            const nextVideo = tab ? tabToVideoState(tab) : null;
            if (nextVideo?.videoId) {
                setVideo((prev) => {
                    if (prev?.videoId === nextVideo.videoId) {
                        return prev;
                    }
                    return nextVideo;
                });
            }
        } catch {
            // Ignore tab query errors
        }
    };

    useEffect(() => {
        console.log('[RAG-DEBUG] App mounted');
        return () => {
            console.log('[RAG-DEBUG] App unmounted');
        };
    }, []);

    useEffect(() => {
        void (async () => {
            const id = await getOrCreateSessionId();
            setSessionId(id);
            setBackendOnline(await pingBackend());

            const stored = await chrome.storage.session.get('currentVideoState');
            const nextVideo = (stored.currentVideoState as CurrentVideoState | null) ?? null;
            if (nextVideo?.videoId) {
                setVideo(nextVideo);
            } else {
                await syncActiveTab();
            }
        })();

        const handleStorageChange: Parameters<typeof chrome.storage.onChanged.addListener>[0] = (changes, areaName) => {
            if (areaName !== 'session') {
                return;
            }
            const next = changes.currentVideoState?.newValue as CurrentVideoState | undefined;
            if (next?.videoId) {
                setVideo((prev) => (prev?.videoId === next.videoId ? prev : next));
            }
        };

        chrome.storage.onChanged.addListener(handleStorageChange);

        const intervalId = window.setInterval(async () => {
            void syncActiveTab();
            const online = await pingBackend();
            setBackendOnline(online);
        }, 2000);

        return () => {
            chrome.storage.onChanged.removeListener(handleStorageChange);
            window.clearInterval(intervalId);
        };
    }, []);

    useEffect(() => {
        const nextVideoId = video?.videoId;
        if (!nextVideoId) {
            return;
        }
        let isCurrent = true;
        const previousId = previousVideoId.current;
        if (previousId !== nextVideoId) {
            hydratedVideoId.current = null;
            setIsChatHydrated(false);
        }
        if (previousId && previousId !== nextVideoId) {
            console.log('[RAG-DEBUG] Clearing messages after video ID change', { previousId, nextVideoId });
            messagesRef.current = [];
            setMessages([]);
            setError(null);
            setVideoReady(false);
            setIsSending(false);
            activeRequestId.current = null;
            setTranslated(false);
            setLanguageLabel('Waiting for transcript');
        }
        previousVideoId.current = nextVideoId;

        void chrome.storage.session.get(`chat:${nextVideoId}`).then((stored) => {
            if (!isCurrent || previousVideoId.current !== nextVideoId) {
                return;
            }
            const savedMessages = stored[`chat:${nextVideoId}`];
            const restoredMessages = Array.isArray(savedMessages) ? savedMessages as ChatEntry[] : [];
            messagesRef.current = restoredMessages;
            setMessages(restoredMessages);
            hydratedVideoId.current = nextVideoId;
            setIsChatHydrated(true);
        }).catch((err) => {
            console.error('[RAG-DEBUG] Unable to restore chat history', err);
            if (isCurrent && previousVideoId.current === nextVideoId) {
                hydratedVideoId.current = nextVideoId;
                setIsChatHydrated(true);
            }
        });

        return () => {
            isCurrent = false;
        };
    }, [video?.videoId]);

    useEffect(() => {
        const videoId = video?.videoId;
        if (!videoId || hydratedVideoId.current !== videoId) {
            return;
        }
        void chrome.storage.session.set({ [`chat:${videoId}`]: messages }).catch((err) => {
            console.error('[RAG-DEBUG] Unable to persist chat history', err);
        });
    }, [messages, video?.videoId]);

    useEffect(() => {
        if (!backendOnline || !video?.videoId) {
            return;
        }
        if (video.videoId === lastLoadedVideoId.current) {
            return;
        }

        let isMounted = true;
        void (async () => {
            setIsLoadingVideo(true);
            setLoadStatus('Loading transcript...');
            try {
                const result = await loadVideo(video.videoId);
                if (!isMounted) return;
                if (!result.success) {
                    throw new Error(result.message || 'Unable to load video');
                }
                lastLoadedVideoId.current = video.videoId;
                setTranslated(result.translated);
                setLanguageLabel(result.translated ? `${result.language} → English` : result.language.toUpperCase());
                setLoadStatus(result.translated ? 'Transcript translated and ready ✓' : 'Transcript ready ✓');
                setVideoReady(true);
                setError(null);
            } catch (err) {
                if (!isMounted) return;
                const message = err instanceof Error ? err.message : 'Unable to load the video transcript.';
                setError(message);
                setLoadStatus('Transcript unavailable');
                setVideoReady(false);
            } finally {
                if (isMounted) {
                    setIsLoadingVideo(false);
                }
            }
        })();

        return () => {
            isMounted = false;
        };
    }, [video?.videoId, backendOnline]);


    const banner = useMemo(() => {
        if (!backendOnline) {
            return 'Backend offline';
        }
        if (isLoadingVideo) {
            return 'Building video knowledge base...';
        }
        if (videoReady) {
            return 'Ready ✓';
        }
        return loadStatus;
    }, [backendOnline, isLoadingVideo, loadStatus, videoReady]);

    const clearChat = () => {
        console.log('[RAG-DEBUG] Clearing messages from Clear chat');
        void updateMessages(() => []);
    };

    const handleSourceClick = async (seconds: number) => {
        if (!video?.videoId) {
            return;
        }
        const url = buildTimestampUrl(video.videoId, seconds);
        const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
        const tab = tabs[0];
        if (tab?.id) {
            await chrome.tabs.update(tab.id, { url });
        } else {
            await chrome.tabs.create({ url });
        }
    };

    const appendErrorMessage = (message: string) => {
        setError(message);
        void updateMessages((current) => [
            ...current,
            {
                id: createId(),
                role: 'assistant',
                content: message,
                isError: true,
            },
        ]);
    };

    const handleSend = async (question: string): Promise<boolean> => {
        if (!isChatHydrated) {
            return false;
        }
        if (!video?.videoId) {
            appendErrorMessage('Video not detected yet');
            return false;
        }
        if (!sessionId) {
            appendErrorMessage('Session not ready');
            return false;
        }
        if (backendOnline !== true) {
            appendErrorMessage('Backend offline');
            return false;
        }
        if (isLoadingVideo || !videoReady) {
            appendErrorMessage('Video still loading');
            return false;
        }

        const videoId = video.videoId;
        const currentSessionId = sessionId;
        const requestId = createId();
        activeRequestId.current = requestId;
        setIsSending(true);
        const userMessage: ChatEntry = {
            id: createId(),
            role: 'user',
            content: question,
        };
        try {
            await updateMessages((current) => [...current, userMessage], videoId);
        } catch (err) {
            console.error('[RAG-DEBUG] Unable to persist the accepted question', err);
            appendErrorMessage('Unable to save this message. Please try again.');
            setIsSending(false);
            activeRequestId.current = null;
            return false;
        }
        setError(null);

        void (async () => {
            try {
                const response = await askQuestion({ video_id: videoId, question, session_id: currentSessionId });
                if (!response.success) {
                    throw new Error(response.message || 'Unable to answer the question.');
                }
                if (typeof response.answer !== 'string' || !response.answer.trim()) {
                    throw new Error('The backend returned source timestamps without answer text. Please try again.');
                }
                if (previousVideoId.current !== videoId || activeRequestId.current !== requestId) {
                    return;
                }

                const assistantMessage: ChatEntry = {
                    id: createId(),
                    role: 'assistant',
                    content: response.answer,
                    sources: response.sources,
                };
                await updateMessages((current) => [...current, assistantMessage], videoId);
            } catch (err) {
                if (previousVideoId.current === videoId && activeRequestId.current === requestId) {
                    appendErrorMessage(err instanceof Error ? err.message : 'The backend did not respond.');
                }
            } finally {
                if (activeRequestId.current === requestId) {
                    activeRequestId.current = null;
                    setIsSending(false);
                }
            }
        })();

        return true;
    };

    return (
        <div className="flex h-full min-h-0 flex-col gap-3 overflow-y-auto p-3 text-slate-100">
            <header className="shrink-0 rounded-3xl border border-slate-700/60 bg-slate-900/70 p-4 shadow-glow backdrop-blur">
                <div className="flex items-center justify-between gap-4">
                    <div>
                        <p className="text-xs uppercase tracking-[0.32em] text-slate-400">AI YouTube Video Chatbot</p>
                        <h1 className="mt-1 text-lg font-semibold text-white">Side Panel Assistant</h1>
                    </div>
                    <div className="rounded-full border border-violet-400/30 bg-violet-400/10 px-3 py-1 text-xs text-violet-100">
                        {banner}
                    </div>
                </div>
            </header>

            <VideoInfo video={video} loadStatus={banner} languageLabel={languageLabel} translated={translated} />

            {backendOnline === false ? <ErrorMessage message="The FastAPI backend is unreachable. Start it with uvicorn backend.main:app --reload." /> : null}
            {error ? <ErrorMessage message={error} /> : null}

            <section className="flex min-h-[140px] flex-1 flex-col overflow-hidden rounded-3xl border border-slate-700/60 bg-slate-950/60 p-4 shadow-glow backdrop-blur">
                <div className="mb-3 flex shrink-0 items-center justify-between gap-3">
                    <div>
                        <p className="text-xs uppercase tracking-[0.24em] text-slate-500">Conversation</p>
                        <p className="text-xs text-slate-300">Current video transcript</p>
                    </div>
                    <button
                        type="button"
                        onClick={clearChat}
                        className="rounded-full border border-slate-700 bg-slate-900 px-4 py-2 text-xs font-medium text-slate-200 transition hover:border-violet-400 hover:text-white"
                    >
                        Clear chat
                    </button>
                </div>

                <div className="min-h-0 flex-1 overflow-y-auto pr-1">
                    <ChatWindow messages={messages} onSourceClick={handleSourceClick} isSending={isSending} />
                </div>
            </section>

            {isLoadingVideo ? <LoadingState label="Detecting transcript and building video knowledge base..." /> : null}

            <div className="shrink-0">
                <InputBox onSend={handleSend} disabled={isSending || !isChatHydrated} />
            </div>
        </div>
    );
}
