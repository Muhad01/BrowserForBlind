"""Spoken narration for blind and low-vision users (FR-19..22, FR-60, FR-61, NFR-ACC-02).

All speech text is generated here through pure, deterministic functions.
Rules:
- Keep every sentence under 20 words.
- Never read internal IDs, class names, or generated element keys.
- Never speak credentials or sensitive field values.
"""
from urllib.parse import urlparse

from core.agent.schema import ElementMeta, NormalizedAction, PageObservation
from core.enums import ActionType
from core.errors import USER_MESSAGES, ErrorCode


def ensure_under_20_words(text: str) -> str:
    """Clamp sentence length to at most 20 words (NFR-ACC-02)."""
    words = text.strip().split()
    if len(words) <= 20:
        return text.strip()
    return " ".join(words[:20])


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
        cleaned = " ".join(cand.strip().split())
        if cleaned:
            return cleaned[:60]
    return ""


def compute_role(ax_role: str = "", tag: str = "", input_type: str = "") -> str:
    """Compute human-friendly role from accessibility tree or HTML tag/type."""
    if ax_role and ax_role.strip():
        return ax_role.strip().lower()

    tag_lower = tag.strip().lower()
    type_lower = input_type.strip().lower()

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
    if tag_lower == "input":
        return "input field"
    return tag_lower or "element"


def format_navigate(url: str) -> str:
    """Format navigate action: 'Opening wikipedia.org' (strip www, en., m. prefixes)."""
    cleaned_url = url.strip()
    if cleaned_url.startswith("about:"):
        return ensure_under_20_words(f"Opening {cleaned_url}")

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
    return ensure_under_20_words(f"Opening {display_target}")


def format_click(meta: ElementMeta | None) -> str:
    """Format click action: 'Opening the link ...', 'Clicking the ... button', or 'Clicking a button'."""
    if not meta:
        return "Clicking a button"

    role = meta.role.lower() if meta.role else ""
    name = meta.accessible_name.strip() if meta.accessible_name else ""

    if role == "link":
        if name:
            return ensure_under_20_words(f"Opening the link {name}")
        return "Opening a link"

    if name:
        if "button" in name.lower():
            return ensure_under_20_words(f"Clicking the {name}")
        return ensure_under_20_words(f"Clicking the {name} button")

    return "Clicking a button"


def format_type(meta: ElementMeta | None, value: str) -> str:
    """Format typing action: 'Typing ... into the search box' or 'Filling in your password'."""
    if meta:
        is_password = (
            meta.input_type.lower() == "password"
            or "password" in f"{meta.name} {meta.id} {meta.accessible_name}".lower()
        )
        if is_password:
            return "Filling in your password"

        name = meta.accessible_name.strip()
        role = meta.role.lower() if meta.role else ""

        if role in {"search box", "text field", "text box"}:
            box_label = f"the {name + ' ' if name else ''}{role}".strip()
        elif name:
            box_label = f"the {name} field"
        else:
            box_label = "the text box"

        return ensure_under_20_words(f"Typing {value} into {box_label}")

    return ensure_under_20_words(f"Typing {value}")


def format_select(meta: ElementMeta | None, value: str) -> str:
    """Format dropdown selection: 'Choosing Medium from the Size dropdown'."""
    if meta and meta.accessible_name:
        dropdown_label = f"the {meta.accessible_name} dropdown"
    else:
        dropdown_label = "the dropdown"
    return ensure_under_20_words(f"Choosing {value} from {dropdown_label}")


def format_scroll(direction: str = "down") -> str:
    """Format scrolling action."""
    dir_clean = "up" if "up" in direction.lower() else "down"
    return f"Scrolling {dir_clean}"


def format_wait(seconds: float | str | None = None) -> str:
    """Format waiting action."""
    return "Waiting a moment"


def format_back() -> str:
    """Format back navigation action."""
    return "Going back"


def format_describe() -> str:
    """Format visual perception action."""
    return "Looking at the page"


def format_stop(result: str) -> str:
    """Format task completion."""
    return ensure_under_20_words(f"Done. {result}")


def format_page_change(new_title: str) -> str:
    """Format page transition: 'Now on: Artificial intelligence, Wikipedia'."""
    title = new_title.strip()
    if not title:
        return "Now on new page"

    for sep in [" - ", " | ", " – ", " — "]:
        if sep in title:
            parts = title.rsplit(sep, 1)
            title = f"{parts[0].strip()}, {parts[1].strip()}"
            break

    return ensure_under_20_words(f"Now on: {title}")


def format_task_started(goal: str) -> str:
    """Format task startup announcement."""
    return ensure_under_20_words(f"Starting: {goal}")


def format_task_failed(error_code: ErrorCode | str) -> str:
    """Format task failure announcement."""
    try:
        code_enum = ErrorCode(error_code)
        return ensure_under_20_words(USER_MESSAGES.get(code_enum, "Task execution failed."))
    except ValueError:
        return "Task execution failed."


def format_task_cancelled() -> str:
    """Format cooperative cancellation announcement."""
    return "Stopped. Nothing else will be done."


def format_spoken_action(action: NormalizedAction, obs: PageObservation | None = None) -> str:
    """Main dispatch function translating a normalized action into spoken text."""
    meta = None
    if obs and action.element_index is not None and action.element_index in obs.element_meta:
        meta = obs.element_meta[action.element_index]

    if action.action == ActionType.NAVIGATE:
        return format_navigate(action.target)
    if action.action == ActionType.CLICK:
        return format_click(meta)
    if action.action == ActionType.TYPE:
        return format_type(meta, action.value)
    if action.action == ActionType.SELECT:
        return format_select(meta, action.value)
    if action.action == ActionType.SCROLL:
        return format_scroll(action.scroll_direction or action.target or "down")
    if action.action == ActionType.WAIT:
        return format_wait(action.value)
    if action.action == ActionType.BACK:
        return format_back()
    if action.action == ActionType.DESCRIBE:
        return format_describe()
    if action.action == ActionType.STOP:
        return format_stop(action.value)

    return ensure_under_20_words(f"Performing {action.action.value}")
