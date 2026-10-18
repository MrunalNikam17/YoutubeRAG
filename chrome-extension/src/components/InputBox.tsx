import { useState } from 'react';

interface InputBoxProps {
    onSend: (question: string) => boolean | Promise<boolean>;
    disabled?: boolean;
}

export function InputBox({ onSend, disabled = false }: InputBoxProps) {
    const [value, setValue] = useState('');

    const submit = async () => {
        const trimmed = value.trim();
        if (!trimmed || disabled) {
            return;
        }
        try {
            if (await onSend(trimmed)) {
                setValue('');
            }
        } catch (err) {
            console.error('Unable to submit question', err);
        }
    };

    return (
        <div className="rounded-3xl border border-slate-700/60 bg-slate-900/80 p-3 shadow-glow">
            <textarea
                value={value}
                onChange={(event) => setValue(event.target.value)}
                onKeyDown={(event) => {
                    if (event.key === 'Enter' && !event.shiftKey) {
                        event.preventDefault();
                        submit();
                    }
                }}
                rows={3}
                placeholder="Ask something about this video..."
                className="w-full resize-none rounded-2xl border border-slate-700 bg-slate-950/80 px-4 py-3 text-sm text-slate-100 outline-none transition placeholder:text-slate-500 focus:border-violet-400"
                disabled={disabled}
            />
            <div className="mt-3 flex items-center justify-between gap-3">
                <p className="text-xs text-slate-500">Press Enter to send. Shift+Enter for a new line.</p>
                <button
                    type="button"
                    onClick={submit}
                    disabled={disabled || !value.trim()}
                    className="rounded-full bg-violet-500 px-5 py-2 text-sm font-semibold text-white transition hover:bg-violet-400 disabled:cursor-not-allowed disabled:opacity-50"
                >
                    {disabled ? 'Sending...' : 'Send'}
                </button>
            </div>
        </div>
    );
}
