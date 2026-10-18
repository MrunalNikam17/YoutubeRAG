import { useEffect, useRef } from 'react';

import type { ChatEntry } from '../types';
import { ChatMessage } from './ChatMessage';

interface ChatWindowProps {
    messages: ChatEntry[];
    onSourceClick: (seconds: number) => void;
    isSending?: boolean;
}

export function ChatWindow({ messages, onSourceClick, isSending = false }: ChatWindowProps) {
    const endRef = useRef<HTMLDivElement | null>(null);
    const latestUserRef = useRef<HTMLDivElement | null>(null);
    const latestUserId = messages.reduce<string | null>(
        (latest, message) => message.role === 'user' ? message.id : latest,
        null,
    );

    useEffect(() => {
        const latestMessage = messages[messages.length - 1];
        if (latestMessage?.role === 'assistant' && latestUserRef.current) {
            latestUserRef.current.scrollIntoView({ behavior: 'smooth', block: 'start' });
            return;
        }
        endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
    }, [messages.length, isSending]);

    return (
        <div className="space-y-3 pr-1">
            {messages.length === 0 ? (
                <div className="rounded-3xl border border-dashed border-slate-700/60 bg-slate-950/40 px-4 py-8 text-center text-sm text-slate-400">
                    Ask a question about the current YouTube video.
                </div>
            ) : (
                messages.map((message) => (
                    <div key={message.id} ref={message.id === latestUserId ? latestUserRef : null}>
                        <ChatMessage message={message} onSourceClick={onSourceClick} />
                    </div>
                ))
            )}
            {isSending ? (
                <div className="rounded-3xl border border-slate-700/60 bg-slate-900/80 px-4 py-3 text-sm text-slate-200">
                    Thinking...
                </div>
            ) : null}
            <div ref={endRef} />
        </div>
    );
}
