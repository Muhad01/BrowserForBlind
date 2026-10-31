"use client";

import { useEffect, useRef } from "react";

import { fetchCurrentTask } from "@/lib/api";
import { frameSpeak, routeFrame, speechPriorityForEvent } from "@/lib/routeFrame";
import { RECONNECTED_SPEAK, SIGN_IN_AGAIN_SPEAK } from "@/lib/phrases";
import { WsClient, type ConnectionStatus } from "@/lib/wsClient";
import type { TaskSnapshot } from "@/lib/events";
import { useAuthStore } from "@/stores/authStore";
import { useConnectionStore } from "@/stores/connectionStore";
import { useTaskStore } from "@/stores/taskStore";

interface UseRealtimeOptions {
  enabled: boolean;
  speak: (text: string, options?: { priority?: "polite" | "assertive"; event?: string }) => void;
}

export function useRealtime({ enabled, speak }: UseRealtimeOptions) {
  const speakRef = useRef(speak);
  const client = useConnectionStore((state) => state.client);

  useEffect(() => {
    speakRef.current = speak;
  }, [speak]);

  useEffect(() => {
    if (!enabled) {
      useConnectionStore.getState().setClient(null);
      useConnectionStore.getState().setStatus("closed");
      return;
    }

    const nextClient = new WsClient({
      onStatus: (status: ConnectionStatus) => {
        useConnectionStore.getState().setStatus(status);
      },
      onFrame: (data) => {
        const frame = routeFrame(data);
        if (!frame) {
          return;
        }
        const text = frameSpeak(frame);
        const priority = speechPriorityForEvent(frame.event);
        if (text && priority) {
          speakRef.current(text, { priority, event: frame.event });
        }
      },
      onAuthLost: () => {
        useAuthStore.getState().clearAuth();
        speakRef.current(SIGN_IN_AGAIN_SPEAK, { priority: "assertive" });
      },
      onOpen: async ({ reconnect, disconnectedForMs }) => {
        if (!reconnect) {
          return;
        }
        try {
          const data = await fetchCurrentTask<{ task: TaskSnapshot | null }>();
          useTaskStore.getState().replaceFromServer(data.task);
        } catch {
          // Backend remains authoritative; a later frame or retry will refresh.
        }
        if (disconnectedForMs > 3000) {
          speakRef.current(RECONNECTED_SPEAK, { priority: "assertive" });
        }
      },
    });
    useConnectionStore.getState().setClient(nextClient);
    void nextClient.connect();

    return () => {
      nextClient.disconnect();
      if (useConnectionStore.getState().client === nextClient) {
        useConnectionStore.getState().setClient(null);
      }
    };
  }, [enabled]);

  return client;
}
