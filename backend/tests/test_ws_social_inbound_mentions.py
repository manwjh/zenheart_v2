from app.services.ws_social_inbound import _extract_agent_id_mentions_from_text
from app.social_registry import parse_mentions


def test_extract_agent_id_mentions_from_text_keeps_unique_order() -> None:
    text = "hi @agt_alpha and @agt_beta then again @agt_alpha"
    assert _extract_agent_id_mentions_from_text(text) == ["agt_alpha", "agt_beta"]


def test_extract_agent_id_mentions_from_text_ignores_non_agent_tokens() -> None:
    text = "hello @all @Rockman test@example.com @agt_valid"
    assert _extract_agent_id_mentions_from_text(text) == ["agt_valid"]


def test_extract_agent_id_mentions_from_text_supports_agn_legacy_ids() -> None:
    text = "hello @AGN-aa8aa27b4fc703373419e99fd9d7eed9 and @agn-legacy_001"
    assert _extract_agent_id_mentions_from_text(text) == [
        "AGN-aa8aa27b4fc703373419e99fd9d7eed9",
        "agn-legacy_001",
    ]


def test_parse_mentions_supports_braced_display_names() -> None:
    name_to_id = {"王哥": "agt_wang", "rockman": "agt_rock"}
    text = "hello @{王哥} and @rockman"
    assert parse_mentions(text, name_to_id) == ["agt_rock", "agt_wang"]
