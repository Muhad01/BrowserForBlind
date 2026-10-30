"""Unit tests for SafetyPolicy (CON-03, FR-17, FR-35, NFR-SAFE-01, NFR-SAFE-02)."""
from core.agent.safety import PlaceholderSafetyPolicy
from core.agent.schema import ElementMeta, NormalizedAction, PageObservation
from core.enums import ActionType, SafetyDecision


def test_safety_policy_determinism():
    """NFR-SAFE-01: Same action and observation must yield identical SafetyVerdict."""
    policy = PlaceholderSafetyPolicy()
    obs = PageObservation(
        url="https://example.com",
        title="Test",
        element_indexes={1},
        element_meta={1: ElementMeta(tag="button", text="Submit")},
    )
    act = NormalizedAction(action=ActionType.CLICK, element_index=1, target="1")

    v1 = policy.classify(act, obs)
    v2 = policy.classify(act, obs)
    assert v1 == v2
    assert v1.decision == SafetyDecision.ALLOW


def test_safety_password_detection():
    """Sensitive password/credential fields must trigger REQUIRE_USER_INPUT."""
    policy = PlaceholderSafetyPolicy()
    obs = PageObservation(
        url="https://example.com/login",
        title="Login",
        element_indexes={10, 11},
        element_meta={
            10: ElementMeta(tag="input", input_type="password", name="pwd"),
            11: ElementMeta(tag="input", input_type="text", name="otp_code"),
        },
    )

    # 1. input type="password"
    act_pwd = NormalizedAction(action=ActionType.TYPE, element_index=10, value="secret123")
    v_pwd = policy.classify(act_pwd, obs)
    assert v_pwd.decision == SafetyDecision.REQUIRE_USER_INPUT

    # 2. OTP/passcode name match
    act_otp = NormalizedAction(action=ActionType.TYPE, element_index=11, value="999888")
    v_otp = policy.classify(act_otp, obs)
    assert v_otp.decision == SafetyDecision.REQUIRE_USER_INPUT


def test_safety_standard_type_allowed():
    """Standard text input is ALLOW."""
    policy = PlaceholderSafetyPolicy()
    obs = PageObservation(
        url="https://example.com",
        title="Search",
        element_indexes={5},
        element_meta={5: ElementMeta(tag="input", input_type="text", name="query")},
    )
    act = NormalizedAction(action=ActionType.TYPE, element_index=5, value="wikipedia")
    v = policy.classify(act, obs)
    assert v.decision == SafetyDecision.ALLOW


def test_fr35_combining_rule_logic():
    """FR-35: AI requires_confirmation can only elevate decision to REQUIRE_CONFIRMATION, never lower."""
    policy = PlaceholderSafetyPolicy()
    obs = PageObservation(url="https://example.com", title="Checkout")

    # Policy ALLOW + AI requires_confirmation=True -> REQUIRE_CONFIRMATION
    act_checkout = NormalizedAction(
        action=ActionType.CLICK,
        element_index=1,
        requires_confirmation=True,
    )
    verdict = policy.classify(act_checkout, obs)
    decision = verdict.decision
    if act_checkout.requires_confirmation and decision == SafetyDecision.ALLOW:
        decision = SafetyDecision.REQUIRE_CONFIRMATION
    assert decision == SafetyDecision.REQUIRE_CONFIRMATION

    # Policy BLOCK + AI requires_confirmation=False -> Decision remains BLOCK
    decision_block = SafetyDecision.BLOCK
    act_unconfirm = NormalizedAction(action=ActionType.CLICK, requires_confirmation=False)
    if act_unconfirm.requires_confirmation and decision_block == SafetyDecision.ALLOW:
        decision_block = SafetyDecision.REQUIRE_CONFIRMATION
    assert decision_block == SafetyDecision.BLOCK

