/** WebSocket client: ticket fetch, connect, reconnect with backoff, send, onFrame. FR-55..66, NFR-REL-05 */

import { fetchWsTicket } from "@/lib/api";
import type { ClientEnvelope, ClientMessageType } from "@/lib/events";

export type ConnectionStatus = "connecting" | "open" | "reconnecting" | "closed";

export const BACKOFF_MS = [1000, 2000, 4000, 8000, 15000] as const;
export const AUTH_CLOSE_CODE = 4401;
export const RECONNECT_ANNOUNCE_MS = 3000;

export interface WsClientHandlers {
  onStatus?: (status: ConnectionStatus) => void;
  onFrame?: (data: unknown) => void;
  onAuthLost?: () => void;
  onOpen?: (info: { reconnect: boolean; disconnectedForMs: number }) => void;
}

export interface WsClientDeps {
  fetchTicket?: () => Promise<string>;
  webSocketCtor?: new (url: string) => WebSocket;
  randomUUID?: () => string;
  now?: () => number;
  setTimeoutFn?: (handler: () => void, timeout: number) => ReturnType<typeof setTimeout>;
  clearTimeoutFn?: (id: ReturnType<typeof setTimeout>) => void;
  wsUrl?: string;
}

export class WsClient {
  private socket: WebSocket | null = null;
  private closedByUser = false;
  private reconnectAttempt = 0;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private disconnectStartedAt: number | null = null;
  private everOpened = false;
  private handlers: WsClientHandlers;
  private readonly fetchTicket: () => Promise<string>;
  private readonly WebSocketCtor: new (url: string) => WebSocket;
  private readonly randomUUID: () => string;
  private readonly now: () => number;
  private readonly setTimeoutFn: (handler: () => void, timeout: number) => ReturnType<typeof setTimeout>;
  private readonly clearTimeoutFn: (id: ReturnType<typeof setTimeout>) => void;
  private readonly wsUrl: string;

  constructor(handlers: WsClientHandlers = {}, deps: WsClientDeps = {}) {
    this.handlers = handlers;
    this.fetchTicket = deps.fetchTicket ?? fetchWsTicket;
    this.WebSocketCtor = deps.webSocketCtor ?? WebSocket;
    this.randomUUID =
      deps.randomUUID ??
      (() =>
        globalThis.crypto?.randomUUID?.() ??
        `req-${Math.random().toString(16).slice(2)}`);
    this.now = deps.now ?? (() => Date.now());
    this.setTimeoutFn = deps.setTimeoutFn ?? ((handler, timeout) => globalThis.setTimeout(handler, timeout));
    this.clearTimeoutFn = deps.clearTimeoutFn ?? ((id) => globalThis.clearTimeout(id));
    this.wsUrl =
      deps.wsUrl ??
      process.env.NEXT_PUBLIC_WS_URL ??
      "ws://localhost:8000/ws/browser/";
  }

  setHandlers(handlers: WsClientHandlers): void {
    this.handlers = handlers;
  }

  async connect(): Promise<void> {
    this.closedByUser = false;
    this.setStatus(this.everOpened ? "reconnecting" : "connecting");
    await this.openSocket();
  }

  disconnect(): void {
    this.closedByUser = true;
    this.clearReconnectTimer();
    this.socket?.close(1000, "client disconnect");
    this.socket = null;
    this.setStatus("closed");
  }

  send(type: ClientMessageType, payload: Record<string, unknown>): ClientEnvelope {
    const envelope: ClientEnvelope = {
      type,
      request_id: this.randomUUID(),
      payload,
    };
    if (this.socket && this.socket.readyState === WebSocket.OPEN) {
      this.socket.send(JSON.stringify(envelope));
    }
    return envelope;
  }

  getSocket(): WebSocket | null {
    return this.socket;
  }

  private async openSocket(): Promise<void> {
    try {
      const ticket = await this.fetchTicket();
      const separator = this.wsUrl.includes("?") ? "&" : "?";
      const url = `${this.wsUrl}${separator}ticket=${encodeURIComponent(ticket)}`;
      const socket = new this.WebSocketCtor(url);
      this.socket = socket;

      socket.onopen = () => {
        const disconnectedForMs =
          this.disconnectStartedAt === null ? 0 : this.now() - this.disconnectStartedAt;
        const reconnect = this.everOpened;
        this.everOpened = true;
        this.reconnectAttempt = 0;
        this.disconnectStartedAt = null;
        this.setStatus("open");
        this.handlers.onOpen?.({ reconnect, disconnectedForMs });
      };

      socket.onmessage = (event: MessageEvent<string>) => {
        try {
          const data = JSON.parse(event.data);
          this.handlers.onFrame?.(data);
        } catch {
          console.warn("Ignored malformed WebSocket frame");
        }
      };

      socket.onclose = (event: CloseEvent) => {
        this.socket = null;
        if (this.closedByUser) {
          this.setStatus("closed");
          return;
        }
        if (event.code === AUTH_CLOSE_CODE) {
          this.setStatus("closed");
          this.handlers.onAuthLost?.();
          return;
        }
        this.scheduleReconnect();
      };

      socket.onerror = () => {
        // onclose follows and drives reconnect/auth handling.
      };
    } catch {
      if (this.closedByUser) {
        return;
      }
      this.scheduleReconnect();
    }
  }

  private scheduleReconnect(): void {
    if (this.closedByUser) {
      return;
    }
    if (this.disconnectStartedAt === null) {
      this.disconnectStartedAt = this.now();
    }
    this.setStatus("reconnecting");
    this.clearReconnectTimer();
    const wait = BACKOFF_MS[Math.min(this.reconnectAttempt, BACKOFF_MS.length - 1)];
    this.reconnectAttempt += 1;
    this.reconnectTimer = this.setTimeoutFn(() => {
      void this.openSocket();
    }, wait);
  }

  private clearReconnectTimer(): void {
    if (this.reconnectTimer !== null) {
      this.clearTimeoutFn(this.reconnectTimer);
      this.reconnectTimer = null;
    }
  }

  private setStatus(status: ConnectionStatus): void {
    this.handlers.onStatus?.(status);
  }
}
