export function LoadingState({ label = 'Loading...' }: { label?: string }) {
    return (
        <div className="flex items-center gap-3 rounded-2xl border border-slate-700/60 bg-slate-900/60 px-4 py-3 text-sm text-slate-200 shadow-glow">
            <span className="inline-flex h-4 w-4 animate-spin rounded-full border-2 border-violet-400 border-t-transparent" />
            <span>{label}</span>
        </div>
    );
}
