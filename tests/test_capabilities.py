import pytest

from cib.capabilities import CAPABILITIES, capability


def test_backend_capabilities_declare_same_current_surfaces() -> None:
    direct = capability("direct-codex")
    promptfoo = capability("promptfoo-codex-sdk")
    assert direct.instruction_surfaces == promptfoo.instruction_surfaces
    assert any("stderr" in field for field in promptfoo.unavailable_evidence)
    assert set(CAPABILITIES) == {"direct-codex", "promptfoo-codex-sdk"}


def test_unknown_adapter_fails_closed() -> None:
    with pytest.raises(ValueError, match="Unknown adapter"):
        capability("imaginary-agent")
