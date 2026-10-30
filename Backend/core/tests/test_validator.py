"""Unit tests for ActionValidator (FR-14..16)."""
from core.agent.schema import ElementMeta, PageObservation, ProposedAction
from core.agent.validator import ActionValidator, ValidationFailure
from core.enums import ActionType
from core.errors import ErrorCode


def create_mock_obs() -> PageObservation:
    return PageObservation(
        url="https://example.com",
        title="Example Page",
        elements_text="[1] Search button\n[2] Search input",
        element_indexes={1, 2, 5},
        element_meta={
            1: ElementMeta(tag="button", text="Search"),
            2: ElementMeta(tag="input", input_type="text", name="q"),
        },
    )


def test_validator_supported_action_types():
    """FR-13: Validate all 9 actions pass when formatted properly."""
    obs = create_mock_obs()

    # 1. navigate
    nav = ActionValidator.validate(ProposedAction(action="navigate", target="https://example.com"), obs)
    assert not isinstance(nav, ValidationFailure)
    assert nav.action == ActionType.NAVIGATE
    assert nav.target == "https://example.com"

    # 2. click
    clk = ActionValidator.validate(ProposedAction(action="click", target="1"), obs)
    assert not isinstance(clk, ValidationFailure)
    assert clk.action == ActionType.CLICK
    assert clk.element_index == 1

    # 3. type
    typ = ActionValidator.validate(ProposedAction(action="type", target="2", value="hello"), obs)
    assert not isinstance(typ, ValidationFailure)
    assert typ.action == ActionType.TYPE
    assert typ.element_index == 2
    assert typ.value == "hello"

    # 4. select
    sel = ActionValidator.validate(ProposedAction(action="select", target="1", value="Option A"), obs)
    assert not isinstance(sel, ValidationFailure)
    assert sel.action == ActionType.SELECT
    assert sel.value == "Option A"

    # 5. scroll
    scr = ActionValidator.validate(ProposedAction(action="scroll", target="down"), obs)
    assert not isinstance(scr, ValidationFailure)
    assert scr.action == ActionType.SCROLL
    assert scr.scroll_direction == "down"

    # 6. wait
    wt = ActionValidator.validate(ProposedAction(action="wait", value="5"), obs)
    assert not isinstance(wt, ValidationFailure)
    assert wt.action == ActionType.WAIT
    assert wt.value == "5"

    # 7. describe
    dsc = ActionValidator.validate(ProposedAction(action="describe"), obs)
    assert not isinstance(dsc, ValidationFailure)
    assert dsc.action == ActionType.DESCRIBE

    # 8. back
    bck = ActionValidator.validate(ProposedAction(action="back"), obs)
    assert not isinstance(bck, ValidationFailure)
    assert bck.action == ActionType.BACK

    # 9. stop
    stp = ActionValidator.validate(ProposedAction(action="stop", value="Done!"), obs)
    assert not isinstance(stp, ValidationFailure)
    assert stp.action == ActionType.STOP
    assert stp.value == "Done!"


def test_validator_unsupported_action():
    """FR-15: Unsupported actions (e.g. evaluate_js, open_tab) must be rejected."""
    obs = create_mock_obs()
    res = ActionValidator.validate(ProposedAction(action="open_tab", target="https://example.com"), obs)
    assert isinstance(res, ValidationFailure)
    assert res.error_code == ErrorCode.UNSUPPORTED_ACTION


def test_validator_bad_url_schemes():
    """FR-16: Reject non-http(s) URL schemes in navigate."""
    obs = create_mock_obs()
    for bad_url in ["javascript:alert(1)", "file:///etc/passwd", "data:text/html,test", "chrome://settings"]:
        res = ActionValidator.validate(ProposedAction(action="navigate", target=bad_url), obs)
        assert isinstance(res, ValidationFailure)
        assert res.error_code == ErrorCode.INVALID_ACTION


def test_validator_element_index_not_on_page():
    """FR-16: Reject actions targeting element indexes not in observation."""
    obs = create_mock_obs()
    # 99 is not in obs.element_indexes {1, 2, 5}
    res = ActionValidator.validate(ProposedAction(action="click", target="99"), obs)
    assert isinstance(res, ValidationFailure)
    assert res.error_code == ErrorCode.INVALID_ACTION

    # Non-integer target
    res_str = ActionValidator.validate(ProposedAction(action="click", target="search_btn"), obs)
    assert isinstance(res_str, ValidationFailure)
    assert res_str.error_code == ErrorCode.INVALID_ACTION


def test_validator_wait_clamping():
    """Wait duration must be clamped between 1 and 10 seconds."""
    obs = create_mock_obs()
    # > 10 clamped to 10
    res_high = ActionValidator.validate(ProposedAction(action="wait", value="60"), obs)
    assert not isinstance(res_high, ValidationFailure)
    assert res_high.value == "10"

    # < 1 clamped to 1
    res_low = ActionValidator.validate(ProposedAction(action="wait", value="0"), obs)
    assert not isinstance(res_low, ValidationFailure)
    assert res_low.value == "1"


def test_validator_stop_empty_value_rejected():
    """FR-12: Stop action must provide a non-empty spoken result."""
    obs = create_mock_obs()
    res = ActionValidator.validate(ProposedAction(action="stop", value=""), obs)
    assert isinstance(res, ValidationFailure)
    assert res.error_code == ErrorCode.INVALID_ACTION

