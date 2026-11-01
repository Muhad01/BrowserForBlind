import { ApiError, getCookie } from "@/lib/api";

export interface TranscriptResult {
  spoken_text: string;
  language: "en" | "ur" | "mixed";
  english_command: string;
  confidence: "high" | "low";
  complete: boolean;
  model?: string;
}

export function shouldRunCommand(result: TranscriptResult): boolean {
  return Boolean(result.complete && result.confidence === "high" && result.english_command.trim());
}

export async function transcribeWav(
  wav: ArrayBuffer,
  language: "en" | "ur" | "auto",
): Promise<TranscriptResult> {
  const form = new FormData();
  form.append("audio", new Blob([wav], { type: "audio/wav" }), "utterance.wav");
  form.append("language", language);
  const headers = new Headers();
  const csrf = getCookie("csrftoken");
  if (csrf) {
    headers.set("X-CSRFToken", csrf);
  }
  const response = await fetch("/api/voice/transcribe/", {
    method: "POST",
    credentials: "include",
    headers,
    body: form,
  });
  const data = (await response.json().catch(() => ({}))) as Record<string, unknown>;
  if (!response.ok) {
    throw new ApiError(
      response.status,
      String(data.error_code ?? "HTTP_ERROR"),
      String(data.message ?? data.speak ?? response.statusText),
      data,
    );
  }
  return {
    spoken_text: String(data.spoken_text ?? ""),
    language: data.language === "ur" || data.language === "mixed" ? data.language : "en",
    english_command: String(data.english_command ?? ""),
    confidence: data.confidence === "low" ? "low" : "high",
    complete: Boolean(data.complete),
    model: typeof data.model === "string" ? data.model : "",
  };
}
