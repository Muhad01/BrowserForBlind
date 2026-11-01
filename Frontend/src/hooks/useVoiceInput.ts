"use client";

import { useCallback, useEffect, useRef } from "react";

import { playErrorEarcon, playListenStart, playListenStop } from "@/lib/earcons";
import { AudioCapture, type CaptureEndReason } from "@/lib/audioCapture";
import { EARCON_MS } from "@/lib/speechGate";
import { handleTranscript, type TranscriptHandlers } from "@/lib/handleTranscript";
import { MIC_ERROR_MESSAGES, VOICE_UNSUPPORTED_SPEAK } from "@/lib/phrases";
import { useSpeechRecognition } from "@/hooks/useSpeechRecognition";
import { useSpeechStore } from "@/stores/speechStore";
import { useVoiceStore } from "@/stores/voiceStore";

export interface VoiceInputExtra {
  spoken_text?: string;
  language?: "en" | "ur" | "mixed";
}

export type TranscribeFn = (
  wav: ArrayBuffer,
  language: "en" | "ur" | "auto",
) => Promise<{
  spoken_text: string;
  language: "en" | "ur" | "mixed";
  english_command: string;
  confidence: "high" | "low";
  complete: boolean;
}>;

interface UseVoiceInputOptions {
  handlers: TranscriptHandlers;
  bargeIn: () => void;
  speakAssertive: (text: string) => void;
  transcribe?: TranscribeFn;
}

export function useVoiceInput({
  handlers,
  bargeIn,
  speakAssertive,
  transcribe,
}: UseVoiceInputOptions) {
  const captureRef = useRef<AudioCapture | null>(null);
  const handlersRef = useRef(handlers);
  const speakRef = useRef(speakAssertive);
  const bargeInRef = useRef(bargeIn);
  const transcribeRef = useRef(transcribe);
  const engine = useSpeechRecognition({ handlers, bargeIn, speakAssertive });

  useEffect(() => {
    handlersRef.current = handlers;
    speakRef.current = speakAssertive;
    bargeInRef.current = bargeIn;
    transcribeRef.current = transcribe;
  }, [handlers, speakAssertive, bargeIn, transcribe]);

  const onCaptureEnded = useCallback(async (wav: ArrayBuffer, reason: CaptureEndReason) => {
    playListenStop();
    useVoiceStore.getState().setListening(false);
    useVoiceStore.getState().setLevel(0);
    if (reason === "no_speech") {
      const message = MIC_ERROR_MESSAGES["no-speech"];
      useVoiceStore.getState().setError(message);
      speakRef.current(message);
      return;
    }
    if (reason === "abort") {
      return;
    }
    const transcribeWav = transcribeRef.current;
    if (!transcribeWav) {
      return;
    }
    try {
      useVoiceStore.getState().setStatusWord("Understanding");
      const language = (useSpeechStore.getState().settings as { language?: "en" | "ur" | "auto" }).language ?? "auto";
      const result = await transcribeWav(wav, language === "ur" || language === "en" ? language : "auto");
      if (!result.complete || result.confidence === "low" || !result.english_command.trim()) {
        return;
      }
      handleTranscript(result.english_command, handlersRef.current);
    } catch {
      // Step 2 wires fallback speech and retry copy.
    }
  }, []);

  useEffect(() => {
    const capture = new AudioCapture({
      onLevel: (level) => useVoiceStore.getState().setLevel(level),
      onEnded: (wav, reason) => {
        void onCaptureEnded(wav, reason);
      },
      onError: (code) => {
        const message = MIC_ERROR_MESSAGES[code] ?? MIC_ERROR_MESSAGES["audio-capture"];
        playErrorEarcon();
        useVoiceStore.getState().setListening(false);
        useVoiceStore.getState().setError(message);
        speakRef.current(message);
      },
    });
    captureRef.current = capture;
    return () => {
      capture.release();
      captureRef.current = null;
    };
  }, [onCaptureEnded]);

  const usingGemini = useCallback(() => {
    const settings = useSpeechStore.getState().settings as { sttEngine?: string };
    return settings.sttEngine !== "browser";
  }, []);

  const startListening = useCallback(async () => {
    if (!usingGemini()) {
      await engine.startListening();
      return;
    }
    useVoiceStore.getState().setListening(true);
    useVoiceStore.getState().setError(null);
    useVoiceStore.getState().setInterim("");
    useSpeechStore.getState().setLive("Listening", "polite");
    bargeInRef.current();
    void playListenStart(EARCON_MS);
    const capture = captureRef.current;
    if (!capture) {
      speakRef.current(VOICE_UNSUPPORTED_SPEAK);
      useVoiceStore.getState().setListening(false);
      return;
    }
    const talkMode = useSpeechStore.getState().settings.talkMode;
    capture.start(talkMode);
  }, [engine, usingGemini]);

  const stopListening = useCallback(() => {
    if (!usingGemini()) {
      engine.stopListening();
      return;
    }
    captureRef.current?.stop();
  }, [engine, usingGemini]);

  const closeMic = useCallback(() => {
    engine.closeMic();
    captureRef.current?.abort();
    useVoiceStore.getState().setListening(false);
    useVoiceStore.getState().setLevel(0);
  }, [engine]);

  const toggleListening = useCallback(() => {
    if (useVoiceStore.getState().listening) {
      stopListening();
      return;
    }
    void startListening();
  }, [startListening, stopListening]);

  const warmMic = useCallback(async () => {
    await captureRef.current?.warm();
  }, []);

  return { startListening, stopListening, closeMic, toggleListening, warmMic };
}
