export type UiLanguage = "en" | "ur";
export type LanguageSetting = "auto" | "en" | "ur";

const URDU_RE = /[\u0600-\u06FF]/;

export const MESSAGES = {
  listening: { en: "Listening", ur: "سن رہا ہوں" },
  understanding: { en: "Understanding…", ur: "سمجھ رہا ہوں…" },
  ready: { en: "Ready", ur: "تیار" },
  working: { en: "Working", ur: "کام ہو رہا ہے" },
  done: { en: "Done", ur: "ہو گیا" },
  problem: { en: "Problem", ur: "مسئلہ" },
  waitingAnswer: { en: "Waiting for your answer", ur: "آپ کے جواب کا انتظار" },
  youSaid: { en: "You said", ur: "آپ نے کہا" },
  nothingYet: { en: "nothing yet", ur: "ابھی کچھ نہیں" },
  speak: { en: "Speak (Space)", ur: "بولیے (اسپیس)" },
  stopListening: { en: "Stop listening (Space)", ur: "سننا بند (اسپیس)" },
  stopEscape: { en: "Stop (Escape)", ur: "روکیں (اسکیپ)" },
  repeat: { en: "Repeat last message (R)", ur: "آخری بات دہرائیں (R)" },
  help: { en: "Help (H)", ur: "مدد (H)" },
  settings: { en: "Settings (S)", ur: "ترتیبات (S)" },
  signOut: { en: "Sign out", ur: "سائن آؤٹ" },
  signedInAs: { en: "Signed in as", ur: "سائن ان" },
  connection: { en: "Connection", ur: "رابطہ" },
  connected: { en: "Connected", ur: "جڑا ہوا" },
  connecting: { en: "Connecting", ur: "جڑ رہا ہے" },
  reconnecting: { en: "Reconnecting", ur: "دوبارہ جڑ رہا ہے" },
  disconnected: { en: "Disconnected", ur: "منقطع" },
  typeInstead: { en: "Type a command instead", ur: "حکم لکھیں" },
  command: { en: "Command", ur: "حکم" },
  sendCommand: { en: "Send command", ur: "حکم بھیجیں" },
  noSpoken: { en: "No spoken update yet.", ur: "ابھی کوئی آواز نہیں۔" },
  missedPart: {
    en: "I may have missed part of that. Please say it again.",
    ur: "شاید کچھ رہ گیا۔ دوبارہ کہیں۔",
  },
  transcribeFail: {
    en: "I couldn't process that. Please say it again.",
    ur: "میں وہ سمجھ نہیں سکا۔ دوبارہ کہیں۔",
  },
  noSpeech: {
    en: "I didn't hear anything. Press Space and try again.",
    ur: "میں نے کچھ نہیں سنا۔ اسپیس دبا کر دوبارہ کوشش کریں۔",
  },
  micBlocked: {
    en: "Microphone access is blocked. Allow the microphone in Chrome's address bar, then press Space to try again.",
    ur: "مائیکروفون بند ہے۔ کروم کے ایڈریس بار میں اجازت دیں، پھر اسپیس دبائیں۔",
  },
  noMic: {
    en: "No microphone was found. Check that it's connected, then press Space.",
    ur: "مائیکروفون نہیں ملا۔ کنکشن چیک کریں، پھر اسپیس دبائیں۔",
  },
  voiceNetwork: {
    en: "Voice recognition needs an internet connection. Check your connection and press Space.",
    ur: "آواز کے لیے انٹرنیٹ چاہیے۔ کنکشن چیک کریں اور اسپیس دبائیں۔",
  },
  voiceUnsupported: {
    en: "Voice input isn't supported in this browser. Please use Google Chrome, or type your command.",
    ur: "اس براؤزر میں آواز نہیں چلتی۔ گوگل کروم استعمال کریں یا حکم لکھیں۔",
  },
  languageAuto: { en: "Language: automatic.", ur: "زبان: خودکار۔" },
  languageEn: { en: "Language: English.", ur: "زبان: انگریزی۔" },
  languageUr: { en: "Language: Urdu.", ur: "زبان: اردو۔" },
  voiceNow: { en: "This is my voice now.", ur: "اب یہ میری آواز ہے۔" },
  maleMissing: {
    en: "A male voice isn't installed on this computer, so I'm using the default voice.",
    ur: "مردانہ آواز نصب نہیں، اس لیے پہلے سے طے شدہ آواز استعمال کر رہا ہوں۔",
  },
  femaleMissing: {
    en: "A female voice isn't installed on this computer, so I'm using the default voice.",
    ur: "نارانہ آواز نصب نہیں، اس لیے پہلے سے طے شدہ آواز استعمال کر رہا ہوں۔",
  },
  urduVoiceMissing: {
    en: "An Urdu voice isn't installed on this computer. Add Urdu speech in Windows Settings, Time and Language.",
    ur: "اردو آواز نصب نہیں۔ ونڈوز کی ترتیبات میں اردو تقریر شامل کریں۔",
  },
  helpSpeak: {
    en: "Press Space to speak. Press Escape to stop. Say close the browser, or press Shift Escape to close. Press L for language, G for voice, V for detail, T for talk mode. Press H for help and S for settings.",
    ur: "بولنے کے لیے اسپیس دبائیں۔ روکنے کے لیے اسکیپ۔ براؤزر بند کرنے کے لیے بند کرو کہیں یا شفٹ اسکیپ دبائیں۔ زبان کے لیے L، آواز کے لیے G، تفصیل کے لیے V، بات کے انداز کے لیے T۔ مدد H، ترتیبات S۔",
  },
  outputMode: { en: "Output mode", ur: "آؤٹ پٹ" },
  speechRate: { en: "Speech rate", ur: "بولنے کی رفتار" },
  narrationDetail: { en: "Narration detail", ur: "تفصیل" },
  brief: { en: "Brief", ur: "مختصر" },
  detailed: { en: "Detailed", ur: "تفصیلی" },
  talkMode: { en: "Talk mode", ur: "بات کا انداز" },
  pressTalk: { en: "Press Space to talk", ur: "بات کے لیے اسپیس دبائیں" },
  holdTalk: { en: "Hold Space to talk", ur: "بات کے لیے اسپیس دبائے رکھیں" },
  voice: { en: "Voice", ur: "آواز" },
  female: { en: "Female", ur: "عورت" },
  male: { en: "Male", ur: "مرد" },
  specificVoice: { en: "Specific voice…", ur: "خاص آواز…" },
  language: { en: "Language", ur: "زبان" },
  automatic: { en: "Automatic", ur: "خودکار" },
  english: { en: "English", ur: "انگریزی" },
  urdu: { en: "Urdu", ur: "اردو" },
  sttEngine: { en: "Speech engine", ur: "آواز کا انجن" },
  engineGemini: { en: "CIGHT (Gemini)", ur: "CIGHT (جیمینی)" },
  engineBrowser: { en: "Browser", ur: "براؤزر" },
  closeSettings: { en: "Close settings", ur: "ترتیبات بند کریں" },
  closeHelp: { en: "Close help", ur: "مدد بند کریں" },
  welcome: {
    en: "Ready. Press Space and say what you want to do. Press H for help.",
    ur: "تیار۔ اسپیس دبا کر بتائیں کیا کرنا ہے۔ مدد کے لیے H دبائیں۔",
  },
} as const;

export type MessageKey = keyof typeof MESSAGES;

export function containsUrdu(text: string): boolean {
  return URDU_RE.test(text || "");
}

export function resolveUiLanguage(setting: LanguageSetting, spoken?: string | null): UiLanguage {
  if (setting === "ur") {
    return "ur";
  }
  if (setting === "en") {
    return "en";
  }
  if (spoken === "ur" || (spoken === "mixed" && containsUrdu(spoken))) {
    return "ur";
  }
  return "en";
}

export function msg(key: MessageKey, language: UiLanguage | LanguageSetting | string): string {
  const lang: UiLanguage = language === "ur" ? "ur" : "en";
  return MESSAGES[key][lang];
}

export function browserSpeechLang(setting: LanguageSetting): string {
  return setting === "ur" ? "ur-PK" : "en-IN";
}

export function everyKeyBilingual(): boolean {
  return (Object.keys(MESSAGES) as MessageKey[]).every((key) => MESSAGES[key].en && MESSAGES[key].ur);
}
