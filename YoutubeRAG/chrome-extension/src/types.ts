import type { ApiSource } from './services/api';

export type ChatRole = 'user' | 'assistant';

export interface ChatEntry {
    id: string;
    role: ChatRole;
    content: string;
    sources?: ApiSource[];
    isError?: boolean;
}

export interface CurrentVideoState {
    videoId: string;
    title: string;
    url: string;
    isShorts: boolean;
    timestamp: number;
}
