import { formatTimestamp } from '../utils/youtube';
import type { ChatEntry } from '../types';

interface ChatMessageProps {
    message: ChatEntry;
    onSourceClick: (seconds: number) => void;
}

export function ChatMessage({ message, onSourceClick }: ChatMessageProps) {
    const isUser = message.role === 'user';
    const hasContent = typeof message.content === 'string' && message.content.trim().length > 0;

    return (
        <article
            className={[
                'rounded-3xl border px-4 py-3 shadow-sm',
                isUser
                    ? 'ml-8 border-violet-400/30 bg-violet-500/10 text-violet-50'
                    : 'mr-8 border-slate-700/60 bg-slate-900/80 text-slate-100',
                    message.isError || !hasContent ? 'border-rose-500/40 bg-rose-500/10 text-rose-50' : '',
            ].join(' ')}
        >
            <div className="flex items-center justify-between gap-3">
                <p className="text-xs uppercase tracking-[0.24em] text-slate-400">{isUser ? 'You' : 'AI'}</p>
                {message.isError ? <p className="text-xs text-rose-200">Error</p> : null}
            </div>

            <p className="mt-2 whitespace-pre-wrap text-sm leading-6">
                {hasContent ? message.content : 'No answer text was saved for this response. Please ask again.'}
            </p>

            {message.sources?.length ? (
                <div className="mt-3 flex flex-wrap gap-2">
                    {message.sources.map((source, index) => (
                        <button
                            key={`${source.start_time}-${index}`}
                            type="button"
                            onClick={() => onSourceClick(source.start_time)}
                            className="rounded-full border border-violet-400/30 bg-violet-500/10 px-3 py-1 text-xs text-violet-100 transition hover:bg-violet-500/20"
                            title="Jump to this timestamp"
                        >
                            Source {formatTimestamp(source.start_time)}
                        </button>
                    ))}
                </div>
            ) : null}
        </article>
    );
}
