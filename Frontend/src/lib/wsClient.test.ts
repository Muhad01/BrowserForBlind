import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AUTH_CLOSE_CODE, BACKOFF_MS, WsClient } from "@/lib/wsClient";

class MockSocket {
  static instances: MockSocket[] = [];
  url: string;
  readyState = 0;
  sent: string[] = [];
  onopen: ((event: Event) => void) | null = null;
  onclose: ((event: CloseEvent) => void) | null = null;
  onmessage: ((event: MessageEvent<string>) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;

  constructor(url: string) {
    this.url = url;
    MockSocket.instances.push(this);
  }

  send(data: string) {
    this.sent.push(data);
  }

  close(code = 1000) {
    this.readyState = 3;
    this.onclose?.({ code } as CloseEvent);
  }

  open() {
    this.readyState = 1;
    this.onopen?.({} as Event);
  }
}

describe("WsClient", () => {
  let tickets: string[];
  const timeouts: Array<{ delay: number; fn: () => void }> = [];

  beforeEach(() => {
    tickets = ["ticket-1", "ticket-2", "ticket-3", "ticket-4", "ticket-5", "ticket-6", "ticket-7"];
    timeouts.length = 0;
    MockSocket.instances = [];
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  function createClient(handlers: ConstructorParameters<typeof WsClient>[0] = {}) {
    return new WsClient(handlers, {
      fetchTicket: vi.fn(async () => {
        const ticket = tickets.shift();
        if (!ticket) {
          throw new Error("no ticket");
        }
        return ticket;
      }),
      webSocketCtor: MockSocket as unknown as new (url: string) => WebSocket,
      setTimeoutFn: ((fn: () => void, delay?: number) => {
        timeouts.push({ delay: delay ?? 0, fn });
        return timeouts.length as unknown as NodeJS.Timeout;
      }) as typeof setTimeout,
      clearTimeoutFn: vi.fn() as unknown as typeof clearTimeout,
      now: () => 10_000,
      randomUUID: () => "req-1",
      wsUrl: "ws://localhost:8000/ws/browser/",
    });
  }

  it("fetches a ticket on every connection attempt", async () => {
    const client = createClient();
    await client.connect();
    expect(MockSocket.instances[0].url).toContain("ticket=ticket-1");
    MockSocket.instances[0].open();
    MockSocket.instances[0].close(1006);
    expect(timeouts[0]?.delay).toBe(BACKOFF_MS[0]);
    await timeouts[0].fn();
    expect(MockSocket.instances[1].url).toContain("ticket=ticket-2");
  });

  it("does not reconnect on 4401 and reports an auth loss", async () => {
    const onAuthLost = vi.fn();
    const client = createClient({ onAuthLost });
    await client.connect();
    MockSocket.instances[0].open();
    MockSocket.instances[0].close(AUTH_CLOSE_CODE);
    expect(onAuthLost).toHaveBeenCalledOnce();
    expect(timeouts).toHaveLength(0);
  });

  it("uses the backoff sequence 1, 2, 4, 8, 15 seconds", async () => {
    const client = createClient();
    await client.connect();
    MockSocket.instances[0].open();

    for (let i = 0; i < BACKOFF_MS.length; i += 1) {
      MockSocket.instances[i].close(1006);
      expect(timeouts[i]?.delay).toBe(BACKOFF_MS[i]);
      await timeouts[i].fn();
    }
    MockSocket.instances[BACKOFF_MS.length].close(1006);
    expect(timeouts[BACKOFF_MS.length]?.delay).toBe(15000);
  });
});
