"use client";

import { useCallback, useEffect, useRef } from "react";

import { playErrorEarcon, playListenStart, playListenStop } from "@/lib/earcons";
import { handleTranscript, type TranscriptHandlers } from "@/lib/handleTranscript";
import { EARCON_MS, LISTEN_TIMEOUT_MS, PRESS_SILENCE_MS } from "@/lib/speechGate";
import { MIC_ERROR_MESSAGES, VOICE_UNSUPPORTED_SPEAK } from "@/lib/phrases";
import { useSpeechStore } from "@/stores/speechStore";
import { useVoiceStore } from "@/stores/voiceStore";

export function getSpeechRecognitionCtor(): SpeechRecognitionConstructor | null {
  if (typeof window === "undefined") {
    return null;
  }
  return window.SpeechRecognition ?? window.webkitSpeechRecognition ?? null;
}

export function accumulateFinals(finals: string[], event: SpeechRecognitionEvent): string[] {
  const next = finals.slice();
  for (let i = 0; i < event.results.length; i += 1) {
    const result = event.results[i];
    if (result.isFinal) {
      next[i] = result[0]?.transcript ?? "";
    }
  }
  return next;
}

export function joinFinals(finals: string[]): string {
  return finals.filter((part) => part.trim()).join(" ").replace(/\s+/g, " ").trim();
}

interface UseSpeechRecognitionOptions {
  handlers: TranscriptHandlers;
  bargeIn: () => void;
  speakAssertive: (text: string) => void;
}

export function useSpeechRecognition({
  handlers,
  bargeIn,
  speakAssertive,
}: UseSpeechRecognitionOptions) {
  const recognitionRef = useRef<SpeechRecognition | null>(null);
  const handlersRef = useRef(handlers);
  const speakAssertiveRef = useRef(speakAssertive);
  const bargeInRef = useRef(bargeIn);
  const finalsRef = useRef<string[]>([]);
  const listenTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const silenceTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const deliveredRef = useRef(false);

  useEffect(() => {
    handlersRef.current = handlers;
    speakAssertiveRef.current = speakAssertive;
    bargeInRef.current = bargeIn;
  }, [handlers, speakAssertive, bargeIn]);

  const clearListenTimer = useCallback(() => {
    if (listenTimerRef.current) {
      clearTimeout(listenTimerRef.current);
      listenTimerRef.current = null;
    }
  }, []);

  const clearSilenceTimer = useCallback(() => {
    if (silenceTimerRef.current) {
      clearTimeout(silenceTimerRef.current);
      silenceTimerRef.current = null;
    }
  }, []);

  const deliverOnce = useCallback(() => {
    if (deliveredRef.current) {
      return;
    }
    deliveredRef.current = true;
    const text = joinFinals(finalsRef.current);
    finalsRef.current = [];
    if (text) {
      handleTranscript(text, handlersRef.current);
    }
  }, []);

  useEffect(() => {
    const Ctor = getSpeechRecognitionCtor();
    if (!Ctor) {
      useVoiceStore.getState().setSupported(false);
      useSpeechStore.getState().setLive(VOICE_UNSUPPORTED_SPEAK, "assertive");
      return;
    }
    useVoiceStore.getState().setSupported(true);
    const recognition = new Ctor();
    recognition.interimResults = true;
    recognition.continuous = true;
    recognition.maxAlternatives = 1;

    recognition.onresult = (event) => {
      finalsRef.current = accumulateFinals(finalsRef.current, event);
      let interim = "";
      for (let i = 0; i < event.results.length; i += 1) {
        const result = event.results[i];
        if (!result.isFinal) {
          interim += result[0]?.transcript ?? "";
        }
      }
      if (interim) {
        useVoiceStore.getState().setInterim(interim);
      }
      if (useSpeechStore.getState().settings.talkMode === "press") {
        clearSilenceTimer();
        silenceTimerRef.current = setTimeout(() => {
          try {
            recognition.stop();
          } catch {
            useVoiceStore.getState().setListening(false);
          }
        }, PRESS_SILENCE_MS);
      }
    };

    recognition.onerror = (event) => {
      if (event.error === "aborted") {
        return;
      }
      const message = MIC_ERROR_MESSAGES[event.error];
      if (!message) {
        return;
      }
      playErrorEarcon();
      useVoiceStore.getState().setError(message);
      useSpeechStore.getState().setLive(message, "assertive");
      speakAssertiveRef.current(message);
    };

    recognition.onend = () => {
      playListenStop();
      clearListenTimer();
      clearSilenceTimer();
      deliverOnce();
      useVoiceStore.getState().setListening(false);
    };

    recognitionRef.current = recognition;
    return () => {
      recognition.onresult = null;
      recognition.onerror = null;
      recognition.onend = null;
      recognition.abort();
      recognitionRef.current = null;
      clearListenTimer();
      clearSilenceTimer();
    };
  }, [clearListenTimer, clearSilenceTimer, deliverOnce]);

  const startListening = useCallback(async () => {
    const recognition = recognitionRef.current;
    if (!recognition) {
      speakAssertiveRef.current(VOICE_UNSUPPORTED_SPEAK);
      return;
    }
    useVoiceStore.getState().setListening(true);
    bargeInRef.current();
    useVoiceStore.getState().setError(null);
    useVoiceStore.getState().setInterim("");
    useSpeechStore.getState().setLive("Listening", "polite");
    finalsRef.current = [];
    deliveredRef.current = false;
    recognition.continuous = true;
    const language = (useSpeechStore.getState().settings as { language?: string }).language;
    recognition.lang = language === "ur" ? "ur-PK" : "en-IN";
    void playListenStart(EARCON_MS);
    try {
      recognition.start();
    } catch {
      useVoiceStore.getState().setListening(false);
      return;
    }
    clearListenTimer();
    listenTimerRef.current = setTimeout(() => {
      try {
        recognition.stop();
      } catch {
        useVoiceStore.getState().setListening(false);
      }
    }, LISTEN_TIMEOUT_MS);
  }, [clearListenTimer]);

  const stopListening = useCallback(() => {
    const recognition = recognitionRef.current;
    if (!recognition) {
      useVoiceStore.getState().setListening(false);
      return;
    }
    clearListenTimer();
    clearSilenceTimer();
    try {
      recognition.stop();
    } catch {
      useVoiceStore.getState().setListening(false);
    }
  }, [clearListenTimer, clearSilenceTimer]);

  const closeMic = useCallback(() => {
    const recognition = recognitionRef.current;
    clearListenTimer();
    clearSilenceTimer();
    if (recognition) {
      try {
        recognition.stop();
      } catch {
        // already stopped
      }
    }
    useVoiceStore.getState().setListening(false);
  }, [clearListenTimer, clearSilenceTimer]);

  const toggleListening = useCallback(() => {
    if (useVoiceStore.getState().listening) {
      stopListening();
      return;
    }
    void startListening();
  }, [startListening, stopListening]);

  return { startListening, stopListening, closeMic, toggleListening };
}
