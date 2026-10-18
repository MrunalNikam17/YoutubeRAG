import { formatTimestamp } from '../utils/youtube';
import type { CurrentVideoState } from '../types';

interface VideoInfoProps {
    video: CurrentVideoState | null;
    loadStatus: string;
    languageLabel: string;
    translated: boolean;
}

export function VideoInfo({ video, loadStatus, languageLabel, translated }: VideoInfoProps) {
    return (
        <section className="shrink-0 rounded-3xl border border-slate-700/60 bg-slate-900/70 p-3 shadow-glow backdrop-blur">
            <div className="flex items-start justify-between gap-3">
                <div>
                    <p className="text-xs uppercase tracking-[0.28em] text-slate-400">Current video</p>
                    <h2 className="mt-1 text-base font-semibold text-white">{video?.title || 'Detecting video...'}</h2>
                    <p className="mt-1 text-xs text-slate-400">
                        {video ? `Video ID: ${video.videoId}` : 'Open a supported YouTube watch page to begin.'}
                    </p>
                </div>
                <div className="rounded-full border border-violet-400/30 bg-violet-400/10 px-3 py-1 text-xs text-violet-200">
                    {loadStatus}
                </div>
            </div>

            <div className="mt-3 grid grid-cols-2 gap-2 text-sm text-slate-200">
                <StatusCard label="Language" value={languageLabel} />
                <StatusCard label="Translation" value={translated ? 'Hindi/other → English ✓' : 'English ✓'} />
            </div>

            {video?.isShorts ? (
                <p className="mt-3 rounded-2xl border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-100">
                    Shorts are detected, but transcript availability may be limited.
                </p>
            ) : null}

            {video ? (
                <p className="mt-3 text-xs text-slate-400">Loaded at {new Date(video.timestamp).toLocaleTimeString()}</p>
            ) : null}
        </section>
    );
}

function StatusCard({ label, value }: { label: string; value: string }) {
    return (
        <div className="min-w-0 rounded-2xl border border-slate-700/60 bg-slate-950/70 px-3 py-2">
            <p className="text-[11px] uppercase tracking-[0.24em] text-slate-500">{label}</p>
            <p className="mt-1 break-words text-sm text-slate-100">{value}</p>
        </div>
    );
}
