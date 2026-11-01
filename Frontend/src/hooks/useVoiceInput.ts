"use client";

import { useCallback, useEffect, useRef } from "react";

import { playErrorEarcon, playListenStart, playListenStop } from "@/lib/earcons";
import { AudioCapture, type CaptureEndReason } from "@/lib/audioCapture";
import { EARCON_MS } from "@/lib/speechGate";
import { handleTranscript, type TranscriptHandlers, type VoiceCommandExtra } from "@/lib/handleTranscript";
import { MIC_ERROR_MESSAGES, VOICE_UNSUPPORTED_SPEAK } from "@/lib/phrases";
import { msg, type UiLanguage } from "@/lib/i18n";
import { shouldRunCommand, transcribeWav } from "@/lib/transcribe";
import { ApiError } from "@/lib/api";
import { useSpeechRecognition } from "@/hooks/useSpeechRecognition";
import { useSpeechStore } from "@/stores/speechStore";
import { useVoiceStore } from "@/stores/voiceStore";

interface UseVoiceInputOptions {
  handlers: TranscriptHandlers;
  bargeIn: () => void;
  speakAssertive: (text: string, lang?: UiLanguage) => void;
}

function uiLang(): UiLanguage {
  return useSpeechStore.getState().settings.language === "ur" ? "ur" : "en";
}

export function useVoiceInput({
  handlers,
  bargeIn,
  speakAssertive,
}: UseVoiceInputOptions) {
  const captureRef = useRef<AudioCapture | null>(null);
  const handlersRef = useRef(handlers);
  const speakRef = useRef(speakAssertive);
  const bargeInRef = useRef(bargeIn);

  const browserHandlers: TranscriptHandlers = {
    sendVoiceCommand: (text, extra) => handlersRef.current.sendVoiceCommand(text, extra),
    repeatLast: () => handlersRef.current.repeatLast(),
    openHelp: () => handlersRef.current.openHelp(),
  };

  const engine = useSpeechRecognition({
    handlers: browserHandlers,
    bargeIn,
    speakAssertive: (text) => speakAssertive(text, uiLang()),
  });

  useEffect(() => {
    handlersRef.current = handlers;
    speakRef.current = speakAssertive;
    bargeInRef.current = bargeIn;
  }, [handlers, speakAssertive, bargeIn]);

  const usingGemini = useCallback(() => {
    if (useVoiceStore.getState().forceBrowserOnce) {
      return false;
    }
    return useSpeechStore.getState().settings.sttEngine !== "browser";
  }, []);

  const onCaptureEnded = useCallback(async (wav: ArrayBuffer, reason: CaptureEndReason) => {
    playListenStop();
    useVoiceStore.getState().setListening(false);
    useVoiceStore.getState().setLevel(0);
    const language = uiLang();
    if (reason === "no_speech") {
      const message = msg("noSpeech", language);
      useVoiceStore.getState().setError(message);
      speakRef.current(message, language);
      return;
    }
    if (reason === "abort") {
      return;
    }
    try {
      useVoiceStore.getState().setStatusWord(msg("understanding", language));
      useSpeechStore.getState().setLive(msg("understanding", language), "polite");
      const setting = useSpeechStore.getState().settings.language;
      const result = await transcribeWav(wav, setting === "auto" ? "auto" : setting);
      useVoiceStore.getState().setSpokenText(result.spoken_text, result.language);
      useVoiceStore.getState().setTranscript(result.spoken_text || result.english_command);
      if (!shouldRunCommand(result)) {
        const repeat = msg("missedPart", language === "ur" || result.language === "ur" ? "ur" : "en");
        useVoiceStore.getState().setError(repeat);
        speakRef.current(repeat, result.language === "ur" ? "ur" : language);
        return;
      }
      const extra: VoiceCommandExtra = {
        spoken_text: result.spoken_text,
        language: result.language,
      };
      handleTranscript(result.english_command, {
        ...handlersRef.current,
        sendVoiceCommand: (text) => handlersRef.current.sendVoiceCommand(text, extra),
      });
    } catch (error) {
      useVoiceStore.getState().setForceBrowserOnce(true);
      const fail = msg("transcribeFail", language);
      useVoiceStore.getState().setError(fail);
      speakRef.current(fail, language);
      if (error instanceof ApiError && error.status !== 503 && error.status !== 408) {
        return;
      }
    } finally {
      useVoiceStore.getState().setStatusWord("");
    }
  }, []);

  useEffect(() => {
    const capture = new AudioCapture({
      onLevel: (level) => useVoiceStore.getState().setLevel(level),
      onEnded: (wav, reason) => {
        void onCaptureEnded(wav, reason);
      },
      onError: (code) => {
        const language = uiLang();
        const mapped =
          code === "not-allowed" || code === "service-not-allowed"
            ? msg("micBlocked", language)
            : code === "audio-capture"
              ? msg("noMic", language)
              : MIC_ERROR_MESSAGES[code] ?? msg("noMic", language);
        playErrorEarcon();
        useVoiceStore.getState().setListening(false);
        useVoiceStore.getState().setError(mapped);
        speakRef.current(mapped, language);
      },
    });
    captureRef.current = capture;
    return () => {
      capture.release();
      captureRef.current = null;
    };
  }, [onCaptureEnded]);

  const startListening = useCallback(async () => {
    if (!usingGemini()) {
      useVoiceStore.getState().setForceBrowserOnce(false);
      await engine.startListening();
      return;
    }
    useVoiceStore.getState().setListening(true);
    useVoiceStore.getState().setError(null);
    useVoiceStore.getState().setInterim("");
    useSpeechStore.getState().setLive(msg("listening", uiLang()), "polite");
    bargeInRef.current();
    void playListenStart(EARCON_MS);
    const capture = captureRef.current;
    if (!capture) {
      speakRef.current(VOICE_UNSUPPORTED_SPEAK, uiLang());
      useVoiceStore.getState().setListening(false);
      return;
    }
    capture.start(useSpeechStore.getState().settings.talkMode);
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
