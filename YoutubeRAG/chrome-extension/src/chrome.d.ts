declare namespace chrome {
    namespace storage {
        namespace local {
            function get(keys: string | string[] | Record<string, unknown>): Promise<Record<string, unknown>>;
            function set(items: Record<string, unknown>): Promise<void>;
        }

        namespace session {
            function get(keys: string | string[] | Record<string, unknown>): Promise<Record<string, unknown>>;
            function set(items: Record<string, unknown>): Promise<void>;
        }

        const onChanged: {
            addListener(callback: (changes: Record<string, { oldValue?: unknown; newValue?: unknown }>, areaName: string) => void): void;
            removeListener(callback: (changes: Record<string, { oldValue?: unknown; newValue?: unknown }>, areaName: string) => void): void;
        };
    }

    namespace runtime {
        function sendMessage(message: unknown): Promise<unknown>;
        const onInstalled: { addListener(callback: () => void): void };
        const onMessage: {
            addListener(
                callback: (
                    message: any,
                    sender: any,
                    sendResponse: (response?: unknown) => void,
                ) => boolean | void,
            ): void;
        };
    }

    namespace tabs {
        interface Tab {
            id?: number;
            index?: number;
            windowId?: number;
            highlighted?: boolean;
            active?: boolean;
            pinned?: boolean;
            url?: string;
            title?: string;
            favIconUrl?: string;
            status?: string;
            incognito?: boolean;
            width?: number;
            height?: number;
            sessionId?: string;
        }

        function query(queryInfo: { active?: boolean; currentWindow?: boolean; lastFocusedWindow?: boolean }): Promise<Tab[]>;
        function get(tabId: number): Promise<Tab>;
        function update(tabId: number, updateProperties: { url?: string }): Promise<void>;
        function create(createProperties: { url?: string }): Promise<void>;
        const onActivated: {
            addListener(callback: (activeInfo: { tabId: number; windowId: number }) => void): void;
        };
        const onUpdated: {
            addListener(
                callback: (
                    tabId: number,
                    changeInfo: { url?: string; status?: string; [key: string]: unknown },
                    tab: Tab,
                ) => void,
            ): void;
        };
    }

    namespace sidePanel {
        function setPanelBehavior(options: { openPanelOnActionClick: boolean }): Promise<void>;
        function open(options: { windowId?: number; tabId?: number }): Promise<void>;
    }
}

