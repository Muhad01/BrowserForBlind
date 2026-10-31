import { create } from "zustand";

import type { ConnectionStatus, WsClient } from "@/lib/wsClient";

interface ConnectionState {
  status: ConnectionStatus;
  client: WsClient | null;
  setStatus: (status: ConnectionStatus) => void;
  setClient: (client: WsClient | null) => void;
}

export const useConnectionStore = create<ConnectionState>((set) => ({
  status: "closed",
  client: null,
  setStatus: (status) => set({ status }),
  setClient: (client) => set({ client }),
}));
