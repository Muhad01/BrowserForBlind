"use client";

import { useEffect } from "react";

import { useSpeechStore } from "@/stores/speechStore";

export function HtmlLang() {
  const language = useSpeechStore((state) => state.settings.language);

  useEffect(() => {
    const lang = language === "ur" ? "ur" : "en";
    document.documentElement.lang = lang;
    document.documentElement.dir = lang === "ur" ? "rtl" : "ltr";
    document.body.style.fontFamily =
      lang === "ur"
        ? "var(--font-urdu), var(--font-geist-sans), serif"
        : "var(--font-geist-sans), sans-serif";
    document.body.style.lineHeight = lang === "ur" ? "2" : "";
  }, [language]);

  return null;
}
