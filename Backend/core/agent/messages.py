"""Spoken message catalogue (English and Urdu). Every user-facing sentence lives here."""
from __future__ import annotations

import re

from core.errors import USER_MESSAGES, ErrorCode

URDU_RE = re.compile(r"[\u0600-\u06FF]")

CATALOGUE: dict[str, dict[str, str]] = {
    "opening": {"en": "Opening {target}", "ur": "{target} کھول رہا ہوں"},
    "clicking_named_button": {"en": "Clicking the {name} button", "ur": "{name} بٹن دبا رہا ہوں"},
    "clicking_named": {"en": "Clicking the {name}", "ur": "{name} دبا رہا ہوں"},
    "clicking_generic": {"en": "Clicking a button", "ur": "ایک بٹن دبا رہا ہوں"},
    "opening_link": {"en": "Opening the link {name}", "ur": "لنک {name} کھول رہا ہوں"},
    "opening_a_link": {"en": "Opening a link", "ur": "ایک لنک کھول رہا ہوں"},
    "choosing_suggestion": {"en": "Choosing the suggestion {name}", "ur": "تجویز {name} چن رہا ہوں"},
    "choosing_suggestion_generic": {"en": "Choosing the suggestion", "ur": "تجویز چن رہا ہوں"},
    "typing_into": {"en": "Typing {value} into {box}", "ur": "{box} میں {value} ٹائپ کر رہا ہوں"},
    "typing": {"en": "Typing {value}", "ur": "{value} ٹائپ کر رہا ہوں"},
    "filling_password": {"en": "Filling in your password", "ur": "پاس ورڈ بھر رہا ہوں"},
    "choosing_select": {"en": "Choosing {value} from {dropdown}", "ur": "{dropdown} سے {value} چن رہا ہوں"},
    "scrolling_down": {"en": "Scrolling down", "ur": "نیچے سکرول کر رہا ہوں"},
    "scrolling_up": {"en": "Scrolling up", "ur": "اوپر سکرول کر رہا ہوں"},
    "waiting": {"en": "Waiting a moment", "ur": "ایک لمحہ انتظار"},
    "going_back": {"en": "Going back", "ur": "واپس جا رہا ہوں"},
    "looking": {"en": "Looking at the page", "ur": "صفحہ دیکھ رہا ہوں"},
    "looking_brief": {"en": "Looking at the page.", "ur": "صفحہ دیکھ رہا ہوں۔"},
    "reading": {"en": "Reading.", "ur": "پڑھ رہا ہوں۔"},
    "done": {"en": "Done. {result}", "ur": "ہو گیا۔ {result}"},
    "done_on_page": {"en": "Done. {result} You're on {title}.", "ur": "ہو گیا۔ {result} آپ {title} پر ہیں۔"},
    "done_empty": {"en": "Done.", "ur": "ہو گیا۔"},
    "now_on": {"en": "Now on: {title}", "ur": "اب یہاں: {title}"},
    "now_on_new": {"en": "Now on new page", "ur": "اب نئے صفحے پر"},
    "okay": {"en": "Okay: {goal}.", "ur": "ٹھیک ہے: {goal}."},
    "stopped": {"en": "Stopped. Nothing else will be done.", "ur": "رک گیا۔ اب کچھ نہیں کیا جائے گا۔"},
    "nothing_running": {"en": "There's nothing running right now.", "ur": "اس وقت کچھ نہیں چل رہا۔"},
    "already_running": {
        "en": "I'm still working on your last request. Say stop to cancel it.",
        "ur": "میں ابھی آپ کی پچھلی درخواست پر کام کر رہا ہوں۔ روکنے کے لیے رک جاؤ کہیں۔",
    },
    "stopping": {"en": "Stopping.", "ur": "روک رہا ہوں۔"},
    "browser_closed": {"en": "Browser closed.", "ur": "براؤزر بند ہو گیا۔"},
    "user_closed_browser": {
        "en": "You closed the browser, so I stopped.",
        "ur": "آپ نے براؤزر بند کر دیا، اس لیے میں رک گیا۔",
    },
    "say_continue": {"en": "Say continue for more.", "ur": "مزید کے لیے آگے پڑھو کہیں۔"},
    "page_in_english": {"en": "This page is in English.", "ur": "یہ صفحہ انگریزی میں ہے۔"},
    "page_in_urdu": {"en": "This page is in Urdu.", "ur": "یہ صفحہ اردو میں ہے۔"},
    "reopened": {"en": "I reopened your last page.", "ur": "میں نے آپ کا پچھلا صفحہ دوبارہ کھول دیا۔"},
    "source": {"en": "Source: {host}.", "ur": "ماخذ: {host}."},
    "no_page": {
        "en": "There's no page open yet. Tell me where to go first.",
        "ur": "ابھی کوئی صفحہ نہیں کھلا۔ پہلے بتائیں کہاں جانا ہے۔",
    },
    "nothing_to_continue": {"en": "There's nothing to continue.", "ur": "آگے پڑھنے کے لیے کچھ نہیں۔"},
    "nothing_to_read": {"en": "There's nothing to read on this page.", "ur": "اس صفحے پر پڑھنے کے لیے کچھ نہیں۔"},
    "empty_page": {
        "en": "This page looks empty or didn't load.",
        "ur": "یہ صفحہ خالی لگتا ہے یا لوڈ نہیں ہوا۔",
    },
    "not_on_page": {"en": "I can't find that on this page.", "ur": "یہ اس صفحے پر نہیں ملا۔"},
    "model_failure": {
        "en": "I couldn't describe this page right now. Please try again.",
        "ur": "میں ابھی یہ صفحہ بیان نہیں کر سکا۔ دوبارہ کوشش کریں۔",
    },
    "error.invalid_action": {
        "en": USER_MESSAGES[ErrorCode.INVALID_ACTION],
        "ur": "براؤزر کی یہ کارروائی درست نہیں تھی۔ دوسرا طریقہ آزما رہا ہوں۔",
    },
    "error.unsupported_action": {
        "en": USER_MESSAGES[ErrorCode.UNSUPPORTED_ACTION],
        "ur": "اے آئی نے ایک غیر معاون کارروائی تجویز کی۔ دوسرا قدم آزماؤں گا۔",
    },
    "error.action_blocked": {
        "en": USER_MESSAGES[ErrorCode.ACTION_BLOCKED],
        "ur": "یہ کارروائی آپ کی رازداری اور حفاظت کے لیے روک دی گئی۔",
    },
    "error.action_failed": {
        "en": USER_MESSAGES[ErrorCode.ACTION_FAILED],
        "ur": "براؤزر اس صفحے پر یہ کام مکمل نہیں کر سکا۔ دوبارہ کوشش کریں۔",
    },
    "error.action_timeout": {
        "en": USER_MESSAGES[ErrorCode.ACTION_TIMEOUT],
        "ur": "صفحہ جواب کا انتظار کرتے ہوئے وقت ختم ہو گیا۔",
    },
    "error.too_many_failures": {
        "en": USER_MESSAGES[ErrorCode.TOO_MANY_FAILURES],
        "ur": "اس کام میں بہت سی غلطیاں ہوئیں۔ براہ کرم مقصد دوسری طرح کہیں۔",
    },
    "error.max_steps_reached": {
        "en": USER_MESSAGES[ErrorCode.MAX_STEPS_REACHED],
        "ur": "کام زیادہ سے زیادہ قدموں تک پہنچ گیا۔ اسے چھوٹے حصوں میں کہیں۔",
    },
    "error.llm_unavailable": {
        "en": USER_MESSAGES[ErrorCode.LLM_UNAVAILABLE],
        "ur": "اے آئی سروس تک رسائی نہیں ہوئی۔ تھوڑی دیر بعد دوبارہ کہیں۔",
    },
    "error.llm_bad_output": {
        "en": USER_MESSAGES[ErrorCode.LLM_BAD_OUTPUT],
        "ur": "اے آئی نے غیر متوقع جواب دیا۔ دوبارہ کوشش کریں۔",
    },
    "error.browser_crashed": {
        "en": USER_MESSAGES[ErrorCode.BROWSER_CRASHED],
        "ur": "براؤزر بند ہو گیا۔ سیشن دوبارہ شروع کر رہا ہوں۔",
    },
    "error.browser_start_failed": {
        "en": USER_MESSAGES[ErrorCode.BROWSER_START_FAILED],
        "ur": "براؤزر نہیں کھل سکا۔ دوبارہ کوشش کریں۔",
    },
    "error.site_unreachable": {
        "en": USER_MESSAGES[ErrorCode.SITE_UNREACHABLE],
        "ur": "ویب سائٹ تک رسائی نہیں ہوئی۔ پتہ یا انٹرنیٹ چیک کریں۔",
    },
    "error.confirmation_unavailable": {
        "en": USER_MESSAGES[ErrorCode.CONFIRMATION_UNAVAILABLE],
        "ur": "اس کارروائی کے لیے تصدیق درکار ہے، جو ابھی دستیاب نہیں۔",
    },
    "error.user_input_required": {
        "en": USER_MESSAGES[ErrorCode.USER_INPUT_REQUIRED],
        "ur": "اس خانے میں آپ کا براہ راست اندراج درکار ہے، جیسے پاس ورڈ۔",
    },
    "error.cancelled_by_user": {
        "en": USER_MESSAGES[ErrorCode.CANCELLED_BY_USER],
        "ur": "آپ کی درخواست پر کام روک دیا گیا۔",
    },
    "error.task_interrupted": {
        "en": USER_MESSAGES[ErrorCode.TASK_INTERRUPTED],
        "ur": "پچھلا کام رک گیا۔ حکم دوبارہ دیں۔",
    },
    "error.invalid_event": {
        "en": USER_MESSAGES[ErrorCode.INVALID_EVENT],
        "ur": "معاف کیجیے، میں یہ درخواست سمجھ نہیں سکا۔",
    },
    "error.task_already_running": {
        "en": USER_MESSAGES[ErrorCode.TASK_ALREADY_RUNNING],
        "ur": "میں ابھی آپ کی پچھلی درخواست پر کام کر رہا ہوں۔ روکنے کے لیے رک جاؤ کہیں۔",
    },
    "error.invalid_request": {
        "en": USER_MESSAGES[ErrorCode.INVALID_REQUEST],
        "ur": "درخواست درست نہیں تھی۔",
    },
    "error.internal_error": {
        "en": USER_MESSAGES[ErrorCode.INTERNAL_ERROR],
        "ur": "اندرونی خرابی ہوئی۔ دوبارہ کوشش کریں۔",
    },
    "error.transcription_unavailable": {
        "en": USER_MESSAGES[ErrorCode.TRANSCRIPTION_UNAVAILABLE],
        "ur": "میں وہ سمجھ نہیں سکا۔ دوبارہ کہیں۔",
    },
}

ERROR_KEYS = {code: f"error.{code.value}" for code in ErrorCode}


def normalize_lang(language: str | None) -> str:
    if (language or "").lower().startswith("ur"):
        return "ur"
    return "en"


def contains_urdu(text: str) -> bool:
    return bool(URDU_RE.search(text or ""))


def resolve_reply_language(setting: str | None, spoken_language: str | None, spoken_text: str = "") -> str:
    setting = (setting or "auto").lower()
    if setting == "ur":
        return "ur"
    if setting == "en":
        return "en"
    spoken = (spoken_language or "").lower()
    if spoken == "ur":
        return "ur"
    if spoken == "mixed":
        return "ur" if contains_urdu(spoken_text) else "en"
    return "ur" if contains_urdu(spoken_text) else "en"


def t(key: str, language: str | None = "en", **kwargs: object) -> str:
    lang = normalize_lang(language)
    entry = CATALOGUE.get(key) or {}
    template = entry.get(lang) or entry.get("en") or key
    return str(template).format(**kwargs) if kwargs else str(template)


def error_message(code: ErrorCode | str, language: str | None = "en") -> str:
    try:
        enum_code = code if isinstance(code, ErrorCode) else ErrorCode(code)
    except ValueError:
        return t("error.internal_error", language)
    return t(ERROR_KEYS[enum_code], language)


def catalogue_complete() -> bool:
    return all("en" in entry and "ur" in entry for entry in CATALOGUE.values())
