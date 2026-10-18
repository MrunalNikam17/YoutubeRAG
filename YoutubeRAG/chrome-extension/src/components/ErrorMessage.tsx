export function ErrorMessage({ message }: { message: string }) {
    return (
        <div className="rounded-2xl border border-rose-500/40 bg-rose-500/10 px-4 py-3 text-sm text-rose-100">
            <p className="font-medium">Unable to continue</p>
            <p className="mt-1 leading-6 text-rose-100/90">{message}</p>
        </div>
    );
}
