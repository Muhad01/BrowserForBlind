"use client";

import { useCallback, useEffect, useRef } from "react";

import { playErrorEarcon, playListenStart, playListenStop } from "@/lib/earcons";
import { handleTranscript, type TranscriptHandlers } from "@/lib/handleTranscript";
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
  cancelSpeech: () => void;
  speakAssertive: (text: string) => void;
}

export function useSpeechRecognition({
  handlers,
  cancelSpeech,
  speakAssertive,
}: UseSpeechRecognitionOptions) {
  const recognitionRef = useRef<SpeechRecognition | null>(null);
  const handlersRef = useRef(handlers);
  const speakAssertiveRef = useRef(speakAssertive);

  useEffect(() => {
    handlersRef.current = handlers;
    speakAssertiveRef.current = speakAssertive;
  }, [handlers, speakAssertive]);

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
      let finalText = "";
      for (let i = event.resultIndex; i < event.results.length; i += 1) {
        const result = event.results[i];
        const transcript = result[0]?.transcript ?? "";
        if (result.isFinal) {
          finalText += transcript;
        } else {
          interim += transcript;
        }
      }
      if (interim) {
        useVoiceStore.getState().setInterim(interim);
      }
      if (finalText.trim()) {
        handleTranscript(finalText, handlersRef.current);
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
      useVoiceStore.getState().setListening(false);
    };

    recognitionRef.current = recognition;
    return () => {
      recognition.onresult = null;
      recognition.onerror = null;
      recognition.onend = null;
      recognition.abort();
      recognitionRef.current = null;
    };
  }, []);

  const startListening = useCallback(() => {
    const recognition = recognitionRef.current;
    if (!recognition) {
      speakAssertiveRef.current(VOICE_UNSUPPORTED_SPEAK);
      return;
    }
    cancelSpeech();
    playListenStart();
    useVoiceStore.getState().setListening(true);
    useVoiceStore.getState().setError(null);
    useVoiceStore.getState().setInterim("");
    useSpeechStore.getState().setLive("Listening", "polite");
    try {
      recognition.start();
    } catch {
      useVoiceStore.getState().setListening(false);
    }
  }, [cancelSpeech]);

  const stopListening = useCallback(() => {
    const recognition = recognitionRef.current;
    if (!recognition) {
      return;
    }
    try {
      recognition.stop();
    } catch {
      useVoiceStore.getState().setListening(false);
    }
  }, []);

  const toggleListening = useCallback(() => {
    if (useVoiceStore.getState().listening) {
      stopListening();
      return;
    }
    startListening();
  }, [startListening, stopListening]);

  return { startListening, stopListening, toggleListening };
}
