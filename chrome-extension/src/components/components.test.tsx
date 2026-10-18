import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { ChatMessage } from './ChatMessage';
import { InputBox } from './InputBox';

describe('ChatMessage', () => {
    it('shows source timestamps and forwards source clicks', () => {
        const onSourceClick = vi.fn();
        render(
            <ChatMessage
                message={{
                    id: 'answer-1',
                    role: 'assistant',
                    content: 'Grounded answer',
                    sources: [{ start_time: 65, end_time: 70, excerpt: 'Evidence' }],
                }}
                onSourceClick={onSourceClick}
            />,
        );

        fireEvent.click(screen.getByRole('button', { name: 'Source 01:05' }));

        expect(onSourceClick).toHaveBeenCalledWith(65);
    });

    it('shows an error state for empty answers', () => {
        render(
            <ChatMessage
                message={{ id: 'empty', role: 'assistant', content: '' }}
                onSourceClick={vi.fn()}
            />,
        );

        expect(screen.getByText('No answer text was saved for this response. Please ask again.')).toBeTruthy();
    });
});

describe('InputBox', () => {
    it('trims a submitted question and clears it after success', async () => {
        const onSend = vi.fn().mockResolvedValue(true);
        render(<InputBox onSend={onSend} />);
        const input = screen.getByPlaceholderText('Ask something about this video...') as HTMLTextAreaElement;

        fireEvent.change(input, { target: { value: '  What is RAG?  ' } });
        fireEvent.click(screen.getByRole('button', { name: 'Send' }));

        expect(onSend).toHaveBeenCalledWith('What is RAG?');
        await vi.waitFor(() => expect(input.value).toBe(''));
    });
});
