"""Spoken narration for blind and low-vision users (FR-19..22, FR-60, FR-61, NFR-ACC-02).

All speech text is generated here through pure, deterministic functions.
Rules:
- Keep every sentence under 20 words.
- Never read internal IDs, class names, or generated element keys.
- Never speak credentials or sensitive field values.
- Never speak a raw URL path on page changes.
"""
import re
from urllib.parse import urlparse

from core.agent.messages import error_message, t
from core.agent.schema import ElementMeta, NormalizedAction, PageObservation
from core.enums import ActionType
from core.errors import ErrorCode


def ensure_under_n_words(text: str, limit: int, ellipsis: bool = False) -> str:
    """Clamp sentence length to at most `limit` words (NFR-ACC-02)."""
    words = text.strip().split()
    if len(words) <= limit:
        return text.strip()
    cut = " ".join(words[:limit])
    return f"{cut}…" if ellipsis else cut


def ensure_under_20_words(text: str) -> str:
    """Clamp sentence length to at most 20 words (NFR-ACC-02)."""
    return ensure_under_n_words(text, 20)


def trim_accessible_name(text: str) -> str:
    """Trim accessible names at the first sentence break or 40 characters."""
    if not text:
        return ""

    # Split at paragraph or sentence boundaries
    s = text
    for sep in ["\n\n", "\r\n\r\n", ". ", " - ", " | ", " – ", " — "]:
        if sep in s:
            s = s.split(sep, 1)[0]
            break

    s = " ".join(s.strip().split())

    # Detect repeated word transition across concatenated elements (e.g. "Artificial intelligence Intelligence in machines")
    dup_match = re.search(r"\b([A-Za-z0-9]+)\s+(?=\1\b)", s, re.IGNORECASE)
    if dup_match:
        s = s[: dup_match.end(1)].strip()

    # Prefer the first label when a capitalised word starts a description.
    desc_match = re.search(r"(?<=[a-z])\s+([A-Z][a-z]+)(?:\s+[a-z])", s)
    if desc_match:
        s = s[: desc_match.start()].strip()

    if len(s) > 40:
        cut = s[:40]
        if len(s) > 40 and s[40] not in " \t\n" and " " in cut:
            cut = cut.rsplit(" ", 1)[0]
        s = cut.strip()

    return s


def compute_accessible_name(
    ax_name: str = "",
    aria_label: str = "",
    children_text: str = "",
    placeholder: str = "",
    title: str = "",
    alt: str = "",
    value: str = "",
    is_password: bool = False,
) -> str:
    """Compute element accessible name with strict priority order, max 60 chars.

    Priority:
    ax_node.name -> aria-label -> children_text -> placeholder -> title -> alt -> value
    Never use id, class, or generated names.
    """
    candidates = [
        ax_name,
        aria_label,
        children_text,
        placeholder,
        title,
        alt,
        "" if is_password else value,
    ]
    for cand in candidates:
        if cand and cand.strip():
            trimmed = trim_accessible_name(cand)
            if trimmed:
                return trimmed[:60]
    return ""


def compute_role(
    ax_role: str = "",
    tag: str = "",
    input_type: str = "",
    has_href: bool = False,
    is_option: bool = False,
) -> str:
    """Compute human-friendly role from accessibility tree or HTML tag/type."""
    if is_option or ax_role == "option":
        return "suggestion"

    tag_lower = tag.strip().lower()
    type_lower = input_type.strip().lower()
    ax_lower = ax_role.strip().lower() if ax_role else ""

    if tag_lower == "a" and has_href:
        return "link"

    if ax_lower and ax_lower not in {"generic", "group", "none"}:
        if ax_lower == "option":
            return "suggestion"
        return ax_lower

    if tag_lower == "a":
        return "link"
    if tag_lower == "button" or (tag_lower == "input" and type_lower in {"submit", "button"}):
        return "button"
    if tag_lower == "input" and type_lower == "search":
        return "search box"
    if tag_lower == "input" and type_lower in {"text", "email", "tel", "url", "password", "number"}:
        return "text field"
    if tag_lower == "textarea":
        return "text box"
    if tag_lower == "select":
        return "dropdown"
    if tag_lower == "input" and type_lower == "checkbox":
        return "checkbox"
    if tag_lower == "input" and type_lower == "radio":
        return "option"
    if tag_lower == "option":
        return "suggestion"
    if tag_lower == "input":
        return "input field"
    return tag_lower or "element"


def is_url_like(text: str, url: str = "") -> bool:
    """A title is URL-like only if it contains ://, starts with /, or equals the hostname.

    A title like "Wikipedia" that matches the site name (no dot) is a real title.
    A title like "en.wikipedia.org" that equals the full hostname including a dot is not.
    """
    t = (text or "").strip()
    if not t:
        return True
    if "://" in t or t.startswith("/"):
        return True

    hostname = ""
    if url:
        parsed = urlparse(url if "://" in url else f"https://{url}")
        hostname = parsed.netloc.lower()
        if ":" in hostname:
            hostname = hostname.split(":")[0]

    t_lower = t.lower()
    if hostname and "." in hostname and t_lower == hostname:
        return True
    # Title itself is a dotted hostname, e.g. en.wikipedia.org
    if "." in t_lower and " " not in t_lower and "/" not in t_lower:
        return True
    # Hostname + path without a scheme, e.g. en.wikipedia.org/wiki/Main_Page
    if "." in t and "/" in t:
        return True
    if t_lower == "page":
        return True
    return bool(t_lower.startswith("www."))


def format_navigate(url: str, language: str = "en") -> str:
    """Format navigate action: 'Opening wikipedia.org' (strip www, en., m. prefixes)."""
    cleaned_url = url.strip()
    if cleaned_url.startswith("about:"):
        return ensure_under_20_words(t("opening", language, target=cleaned_url))

    parsed = urlparse(cleaned_url if "://" in cleaned_url else f"https://{cleaned_url}")
    host = parsed.netloc.lower()
    if ":" in host:
        host = host.split(":")[0]

    if host.startswith("www."):
        host = host[4:]
    if host.startswith("en."):
        host = host[3:]
    elif host.startswith("m."):
        host = host[2:]

    display_target = host if host else cleaned_url
    return ensure_under_20_words(t("opening", language, target=display_target))


def format_click(meta: ElementMeta | None, language: str = "en") -> str:
    """Format click action: suggestions, links, buttons, or generic element."""
    if not meta:
        return t("clicking_generic", language)

    role = meta.role.lower() if meta.role else ""
    name = meta.accessible_name.strip() if meta.accessible_name else ""

    if role == "suggestion":
        if name:
            return ensure_under_20_words(t("choosing_suggestion", language, name=name))
        return t("choosing_suggestion_generic", language)

    if role == "link":
        if name:
            return ensure_under_20_words(t("opening_link", language, name=name))
        return t("opening_a_link", language)

    if name:
        if "button" in name.lower():
            return ensure_under_20_words(t("clicking_named", language, name=name))
        return ensure_under_20_words(t("clicking_named_button", language, name=name))

    return t("clicking_generic", language)


def format_type(meta: ElementMeta | None, value: str, language: str = "en") -> str:
    """Format typing action: 'Typing ... into the search box' or 'Filling in your password'."""
    if meta:
        is_password = (
            meta.input_type.lower() == "password"
            or "password" in f"{meta.name} {meta.id} {meta.accessible_name}".lower()
        )
        if is_password:
            return t("filling_password", language)

        name = meta.accessible_name.strip()
        role = meta.role.lower() if meta.role else ""

        if role in {"search box", "text field", "text box"}:
            box_label = f"the {name + ' ' if name else ''}{role}".strip()
        elif name:
            box_label = f"the {name} field"
        else:
            box_label = "the text box"

        return ensure_under_20_words(t("typing_into", language, value=value, box=box_label))

    return ensure_under_20_words(t("typing", language, value=value))


def format_select(meta: ElementMeta | None, value: str, language: str = "en") -> str:
    """Format dropdown selection: 'Choosing Medium from the Size dropdown'."""
    if meta and meta.accessible_name:
        dropdown_label = f"the {meta.accessible_name} dropdown"
    else:
        dropdown_label = "the dropdown"
    return ensure_under_20_words(t("choosing_select", language, value=value, dropdown=dropdown_label))


def format_scroll(direction: str = "down", language: str = "en") -> str:
    """Format scrolling action."""
    dir_clean = "up" if "up" in direction.lower() else "down"
    return t("scrolling_up" if dir_clean == "up" else "scrolling_down", language)


def format_wait(seconds: float | str | None = None, language: str = "en") -> str:
    """Format waiting action."""
    return t("waiting", language)


def format_back(language: str = "en") -> str:
    """Format back navigation action."""
    return t("going_back", language)


def format_describe(language: str = "en") -> str:
    """Format visual perception action."""
    return t("looking", language)


def format_stop(result: str, title: str = "", language: str = "en") -> str:
    """Format task completion, optionally naming the final page (up to 30 words)."""
    result_text = (result or "").strip()
    page_title = (title or "").strip()
    if page_title and not is_url_like(page_title):
        spoken = t("done_on_page", language, result=result_text, title=page_title)
    else:
        spoken = t("done", language, result=result_text)
    return ensure_under_n_words(spoken, 30)


def source_host(url: str) -> str:
    """Hostname for spoken source attribution (strip www)."""
    from urllib.parse import urlparse

    host = (urlparse(url or "").hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    return host


def with_source_attribution(text: str, url: str, language: str = "en") -> str:
    """Append 'Source: host.' in at most six extra words (FR-25)."""
    body = (text or "").strip()
    host = source_host(url)
    credit = t("source", language, host=host) if host else ""
    if not body:
        return credit
    if "source:" in body.lower() or "ماخذ:" in body or not host:
        return body
    trimmed = body.rstrip(" .")
    return f"{trimmed}. {credit}"


def format_grounded_stop(result: str, language: str = "en") -> str:
    """Speak a page-grounded result without truncating the source host."""
    body = (result or "").strip()
    if not body:
        return t("done_empty", language)
    if body.lower().startswith("done.") or body.startswith("ہو گیا"):
        return body
    return t("done", language, result=body)


def page_changed(new_title: str, url: str = "", language: str = "en") -> str:
    """Format page transition without ever speaking a URL path (NFR-ACC-02)."""
    title = (new_title or "").strip()
    if is_url_like(title):
        if url:
            parsed = urlparse(url if "://" in url else f"https://{url}")
            host = parsed.netloc.lower()
            if ":" in host:
                host = host.split(":")[0]
            if host.startswith("www."):
                host = host[4:]
            if host.startswith("en."):
                host = host[3:]
            elif host.startswith("m."):
                host = host[2:]
            friendly = host if host else url
            return ensure_under_20_words(t("now_on", language, title=friendly))
        return t("now_on_new", language)

    # Clean title
    for sep in [" - ", " | ", " – ", " — "]:
        if sep in title:
            parts = title.rsplit(sep, 1)
            title = f"{parts[0].strip()}, {parts[1].strip()}"
            break

    return ensure_under_20_words(t("now_on", language, title=title))


def format_page_change(new_title: str, url: str = "", language: str = "en") -> str:
    return page_changed(new_title, url=url, language=language)


def format_task_started(goal: str, language: str = "en") -> str:
    """Echo the understood command so the user can cancel immediately (FR-19)."""
    spoken = t("okay", language, goal=(goal or "").strip())
    return ensure_under_n_words(spoken, 20, ellipsis=True)


def format_task_failed(error_code: ErrorCode | str, language: str = "en") -> str:
    """Format task failure announcement."""
    return ensure_under_20_words(error_message(error_code, language))


def format_task_cancelled(language: str = "en") -> str:
    """Format cooperative cancellation announcement."""
    return t("stopped", language)


def format_spoken_action(
    action: NormalizedAction,
    obs: PageObservation | None = None,
    language: str = "en",
) -> str:
    """Main dispatch function translating a normalized action into spoken text."""
    meta = None
    if obs and action.element_index is not None and action.element_index in obs.element_meta:
        meta = obs.element_meta[action.element_index]

    if action.action == ActionType.NAVIGATE:
        return format_navigate(action.target, language=language)
    if action.action == ActionType.CLICK:
        return format_click(meta, language=language)
    if action.action == ActionType.TYPE:
        return format_type(meta, action.value, language=language)
    if action.action == ActionType.SELECT:
        return format_select(meta, action.value, language=language)
    if action.action == ActionType.SCROLL:
        return format_scroll(action.scroll_direction or action.target or "down", language=language)
    if action.action == ActionType.WAIT:
        return format_wait(action.value, language=language)
    if action.action == ActionType.BACK:
        return format_back(language=language)
    if action.action == ActionType.DESCRIBE:
        return format_describe(language=language)
    if action.action == ActionType.STOP:
        return format_stop(action.value, language=language)

    return ensure_under_20_words(f"Performing {action.action.value}")
