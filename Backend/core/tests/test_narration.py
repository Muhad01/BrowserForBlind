"""Unit tests for narration and accessible-name computation (FR-19..22, FR-60, FR-61, NFR-ACC-02)."""
from core.agent.narration import (
    compute_accessible_name,
    compute_role,
    format_click,
    format_describe,
    format_navigate,
    format_page_change,
    format_scroll,
    format_select,
    format_spoken_action,
    format_stop,
    format_task_cancelled,
    format_task_started,
    format_type,
    format_wait,
)
from core.agent.schema import ElementMeta, NormalizedAction, PageObservation
from core.enums import ActionType


def test_navigate_narration_strips_prefixes():
    assert format_navigate("https://en.wikipedia.org/wiki/Artificial_intelligence") == "Opening wikipedia.org"
    assert format_navigate("http://www.google.com") == "Opening google.com"
    assert format_navigate("https://m.youtube.com/watch?v=123") == "Opening youtube.com"
    assert format_navigate("about:blank") == "Opening about:blank"


def test_click_narration():
    # Button with name
    meta_btn = ElementMeta(role="button", accessible_name="Search")
    assert format_click(meta_btn) == "Clicking the Search button"

    # Button ending with button
    meta_btn2 = ElementMeta(role="button", accessible_name="Search button")
    assert format_click(meta_btn2) == "Clicking the Search button"

    # Link with name
    meta_link = ElementMeta(role="link", accessible_name="Artificial intelligence")
    assert format_click(meta_link) == "Opening the link Artificial intelligence"

    # Link without name
    meta_link_unnamed = ElementMeta(role="link", accessible_name="")
    assert format_click(meta_link_unnamed) == "Opening a link"

    # Unknown / no meta
    assert format_click(None) == "Clicking a button"


def test_type_narration_and_password_shielding():
    # Normal search box
    meta_search = ElementMeta(role="search box", accessible_name="")
    assert format_type(meta_search, "artificial intelligence") == "Typing artificial intelligence into the search box"

    # Password input field - must NEVER speak value
    meta_pwd = ElementMeta(input_type="password", name="pwd", accessible_name="Password")
    res_pwd = format_type(meta_pwd, "SecretPassword123")
    assert res_pwd == "Filling in your password"
    assert "SecretPassword123" not in res_pwd

    # Password detected by name
    meta_pwd2 = ElementMeta(input_type="text", name="user_password", accessible_name="Password")
    res_pwd2 = format_type(meta_pwd2, "MyP@ssw0rd")
    assert res_pwd2 == "Filling in your password"
    assert "MyP@ssw0rd" not in res_pwd2


def test_select_scroll_wait_describe_narration():
    meta_sel = ElementMeta(role="dropdown", accessible_name="Size")
    assert format_select(meta_sel, "Medium") == "Choosing Medium from the Size dropdown"

    assert format_scroll("down") == "Scrolling down"
    assert format_scroll("up") == "Scrolling up"
    assert format_wait(5) == "Waiting a moment"
    assert format_describe() == "Looking at the page"


def test_page_change_narration():
    assert format_page_change("Artificial intelligence - Wikipedia") == "Now on: Artificial intelligence, Wikipedia"
    assert format_page_change("Home | CNN News") == "Now on: Home, CNN News"
    assert format_page_change("Python — Welcome") == "Now on: Python, Welcome"


def test_terminal_and_lifecycle_narration():
    assert format_task_started("Find the nearest library") == "Starting: Find the nearest library"
    assert format_stop("Found 3 results.") == "Done. Found 3 results."
    assert format_task_cancelled() == "Stopped. Nothing else will be done."


def test_every_sentence_under_20_words():
    very_long_goal = " ".join(["word"] * 40)
    spoken = format_task_started(very_long_goal)
    assert len(spoken.split()) <= 20

    very_long_result = " ".join(["result"] * 50)
    spoken_result = format_stop(very_long_result)
    assert len(spoken_result.split()) <= 20


def test_accessible_name_priority():
    # 1. ax_name wins over everything
    name1 = compute_accessible_name(
        ax_name="Accessible Name",
        aria_label="Aria Label",
        children_text="Child Text",
        placeholder="Placeholder",
    )
    assert name1 == "Accessible Name"

    # 2. aria-label wins over children_text, placeholder, title, alt, value
    name2 = compute_accessible_name(
        ax_name="",
        aria_label="Aria Label",
        children_text="Child Text",
        placeholder="Placeholder",
    )
    assert name2 == "Aria Label"

    # 3. children_text wins over placeholder
    name3 = compute_accessible_name(
        children_text="  Submit\nForm  ",
        placeholder="Placeholder",
    )
    assert name3 == "Submit Form"

    # 4. placeholder wins over title
    name4 = compute_accessible_name(
        placeholder="Search here",
        title="Hover title",
    )
    assert name4 == "Search here"

    # 5. title wins over alt
    name5 = compute_accessible_name(title="Logo Title", alt="Logo Alt")
    assert name5 == "Logo Title"

    # 6. alt wins over value
    name6 = compute_accessible_name(alt="Company Logo", value="logo.png")
    assert name6 == "Company Logo"

    # 7. value used if not password
    name7 = compute_accessible_name(value="Click Me", is_password=False)
    assert name7 == "Click Me"

    # 8. password value is NEVER used
    name8 = compute_accessible_name(value="secret123", is_password=True)
    assert name8 == ""


def test_compute_role():
    assert compute_role(ax_role="button") == "button"
    assert compute_role(tag="a") == "link"
    assert compute_role(tag="button") == "button"
    assert compute_role(tag="input", input_type="submit") == "button"
    assert compute_role(tag="input", input_type="search") == "search box"
    assert compute_role(tag="input", input_type="text") == "text field"
    assert compute_role(tag="textarea") == "text box"
    assert compute_role(tag="select") == "dropdown"
    assert compute_role(tag="input", input_type="checkbox") == "checkbox"
    assert compute_role(tag="input", input_type="radio") == "option"


def test_format_spoken_action_full_dispatch():
    obs = PageObservation(
        url="https://en.wikipedia.org",
        title="Wikipedia",
        element_meta={
            1: ElementMeta(index=1, role="search box", accessible_name="Search Wikipedia"),
            2: ElementMeta(index=2, role="button", accessible_name="Search"),
        },
    )

    act_nav = NormalizedAction(action=ActionType.NAVIGATE, target="https://en.wikipedia.org")
    assert format_spoken_action(act_nav, obs) == "Opening wikipedia.org"

    act_type = NormalizedAction(action=ActionType.TYPE, target="1", element_index=1, value="AI")
    assert format_spoken_action(act_type, obs) == "Typing AI into the Search Wikipedia search box"

    act_click = NormalizedAction(action=ActionType.CLICK, target="2", element_index=2)
    assert format_spoken_action(act_click, obs) == "Clicking the Search button"

    act_stop = NormalizedAction(action=ActionType.STOP, value="Finished research")
    assert format_spoken_action(act_stop, obs) == "Done. Finished research"
