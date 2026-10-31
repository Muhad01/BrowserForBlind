"use client";

import { useCallback, useEffect, useRef } from "react";

import { playErrorEarcon, playListenStart, playListenStop } from "@/lib/earcons";
import { handleTranscript, type TranscriptHandlers } from "@/lib/handleTranscript";
import { EARCON_MS, LISTEN_TIMEOUT_MS } from "@/lib/speechGate";
import { MIC_ERROR_MESSAGES, SPEECH_LANG, VOICE_UNSUPPORTED_SPEAK } from "@/lib/phrases";
import { useSpeechStore } from "@/stores/speechStore";
import { useVoiceStore } from "@/stores/voiceStore";

export function getSpeechRecognitionCtor(): SpeechRecognitionConstructor | null {
  if (typeof window === "undefined") {
    return null;
  }
  return window.SpeechRecognition ?? window.webkitSpeechRecognition ?? null;
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

  useEffect(() => {
    const Ctor = getSpeechRecognitionCtor();
    if (!Ctor) {
      useVoiceStore.getState().setSupported(false);
      useSpeechStore.getState().setLive(VOICE_UNSUPPORTED_SPEAK, "assertive");
      return;
    }
    useVoiceStore.getState().setSupported(true);
    const recognition = new Ctor();
    recognition.lang = SPEECH_LANG;
    recognition.interimResults = true;
    recognition.continuous = false;
    recognition.maxAlternatives = 1;

    recognition.onresult = (event) => {
      let interim = "";
      const holdMode = useSpeechStore.getState().settings.talkMode === "hold";
      for (let i = event.resultIndex; i < event.results.length; i += 1) {
        const result = event.results[i];
        const transcript = result[0]?.transcript ?? "";
        if (result.isFinal) {
          finalsRef.current.push(transcript);
          if (!holdMode) {
            handleTranscript(transcript, handlersRef.current);
          }
        } else {
          interim += transcript;
        }
      }
      if (interim) {
        useVoiceStore.getState().setInterim(interim);
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
      const holdMode = useSpeechStore.getState().settings.talkMode === "hold";
      if (holdMode && finalsRef.current.length) {
        handleTranscript(finalsRef.current.join(" ").trim(), handlersRef.current);
      }
      finalsRef.current = [];
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
    };
  }, [clearListenTimer]);

  const startListening = useCallback(async () => {
    const recognition = recognitionRef.current;
    if (!recognition) {
      speakAssertiveRef.current(VOICE_UNSUPPORTED_SPEAK);
      return;
    }
    // Close the gate first so arriving frames cannot speak.
    useVoiceStore.getState().setListening(true);
    bargeInRef.current();
    useVoiceStore.getState().setError(null);
    useVoiceStore.getState().setInterim("");
    useSpeechStore.getState().setLive("Listening", "polite");
    finalsRef.current = [];
    recognition.continuous = useSpeechStore.getState().settings.talkMode === "hold";
    await playListenStart(EARCON_MS);
    if (!useVoiceStore.getState().listening) {
      return;
    }
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
    try {
      recognition.stop();
    } catch {
      useVoiceStore.getState().setListening(false);
    }
  }, [clearListenTimer]);

  const closeMic = useCallback(() => {
    const recognition = recognitionRef.current;
    clearListenTimer();
    if (recognition) {
      try {
        recognition.stop();
      } catch {
        // already stopped
      }
    }
    useVoiceStore.getState().setListening(false);
  }, [clearListenTimer]);

  const toggleListening = useCallback(() => {
    if (useVoiceStore.getState().listening) {
      stopListening();
      return;
    }
    void startListening();
  }, [startListening, stopListening]);

  return { startListening, stopListening, closeMic, toggleListening };
}
