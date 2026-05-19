import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cursor_agent  # noqa: E402


def test_runtime_paths_are_under_runtime_root(tmp_path: Path) -> None:
    paths = cursor_agent.runtime_paths(tmp_path)

    assert paths.pid_file == tmp_path / "cursor_agent.pid"
    assert paths.socket_file == tmp_path / "cursor_agent.sock"
    assert paths.status_file == tmp_path / "status.json"
    assert paths.log_file == tmp_path / "events.jsonl"
    assert paths.bootstrap_log_file == tmp_path / "bootstrap.log"


def test_default_paths_are_outside_backend() -> None:
    assert "/backend/" not in str(cursor_agent.DEFAULT_RUNTIME_DIR)
    assert cursor_agent.DEFAULT_ENV_FILE.name == ".env.zenlink-readiness"
    assert cursor_agent.DEFAULT_ENV_FILE.parent.name == "backend"


def test_load_env_file_fills_cursor_api_key_when_unset(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("CURSOR_API_KEY", raising=False)
    env_file = tmp_path / "x.env"
    env_file.write_text("CURSOR_API_KEY=secret-from-file\n", encoding="utf-8")
    cursor_agent.load_env_file(env_file)
    assert os.environ["CURSOR_API_KEY"] == "secret-from-file"


def test_load_env_file_does_not_override_nonempty_cursor_api_key(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CURSOR_API_KEY", "keep-me")
    env_file = tmp_path / "x.env"
    env_file.write_text("CURSOR_API_KEY=other\n", encoding="utf-8")
    cursor_agent.load_env_file(env_file)
    assert os.environ["CURSOR_API_KEY"] == "keep-me"


def test_load_env_file_cursor_api_key_can_fill_when_empty_string(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CURSOR_API_KEY", "   ")
    env_file = tmp_path / "x.env"
    env_file.write_text("CURSOR_API_KEY=filled\n", encoding="utf-8")
    cursor_agent.load_env_file(env_file)
    assert os.environ["CURSOR_API_KEY"] == "filled"


def test_load_env_standard_keys_remain_first_file_wins(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("ZENLINK_FOO", raising=False)
    a = tmp_path / "a.env"
    b = tmp_path / "b.env"
    a.write_text("ZENLINK_FOO=first\nCURSOR_API_KEY=key1\n", encoding="utf-8")
    b.write_text("ZENLINK_FOO=second\nCURSOR_API_KEY=key2\n", encoding="utf-8")
    cursor_agent.load_env_file(a)
    cursor_agent.load_env_file(b)
    assert os.environ["ZENLINK_FOO"] == "first"
    assert os.environ["CURSOR_API_KEY"] == "key1"


def test_sdk_preflight_noop_for_rules_provider() -> None:
    cursor_agent.ensure_cursor_sdk_host_preflight("rules", skip_sdk_preflight=False)


def test_sdk_preflight_skipped_when_flag() -> None:
    cursor_agent.ensure_cursor_sdk_host_preflight("auto", skip_sdk_preflight=True)


def test_sdk_preflight_raises_when_collect_reports_issues(monkeypatch) -> None:
    monkeypatch.setattr(cursor_agent, "collect_cursor_sdk_host_issues", lambda: ["test blocker"])

    try:
        cursor_agent.ensure_cursor_sdk_host_preflight("auto", skip_sdk_preflight=False)
    except RuntimeError as exc:
        assert "test blocker" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")


def test_skip_sdk_preflight_parser_flag() -> None:
    parser = cursor_agent.build_parser()
    plain = parser.parse_args(["run", "--room-id", "r"])
    assert plain.skip_sdk_preflight is False
    skip = parser.parse_args(["run", "--room-id", "r", "--skip-sdk-preflight"])
    assert skip.skip_sdk_preflight is True


def test_parse_run_defaults_room_to_own(monkeypatch) -> None:
    monkeypatch.delenv("ZENLINK_ROOM_ID", raising=False)
    ns = cursor_agent.build_parser().parse_args(["run"])
    assert ns.room_id == cursor_agent.OWN_ROOM_ROOM_ID


def test_parse_run_room_default_from_zenlink_room_id_env(monkeypatch) -> None:
    monkeypatch.setenv("ZENLINK_ROOM_ID", "env-room-spec")
    ns = cursor_agent.build_parser().parse_args(["run"])
    assert ns.room_id == "env-room-spec"


def test_first_created_room_id_from_space_self() -> None:
    assert cursor_agent.CursorAgentDaemon._first_created_room_id({}) is None
    assert cursor_agent.CursorAgentDaemon._first_created_room_id({"recent_created_rooms": []}) is None
    assert (
        cursor_agent.CursorAgentDaemon._first_created_room_id(
            {"recent_created_rooms": [{"room_id": "first"}, {"room_id": "second"}]},
        )
        == "first"
    )


def test_agent_display_name_prefers_my_profile() -> None:
    auth = {"my_profile": {"agent_name": "  Bot 42  "}}
    assert cursor_agent.CursorAgentDaemon._agent_display_name(auth, fallback_agent_id="agt_fallback") == "Bot 42"


def test_agent_display_name_falls_back_to_agent_suffix() -> None:
    auth: dict[str, object] = {}
    long_id = "agt_" + "x" * 40
    name = cursor_agent.CursorAgentDaemon._agent_display_name(auth, fallback_agent_id=long_id)
    assert len(name) == 16
    assert name == long_id[-16:]


def test_tail_text_file_lines(tmp_path: Path) -> None:
    p = tmp_path / "f.txt"
    p.write_text("a\nb\nc\n", encoding="utf-8")
    assert cursor_agent.tail_text_file_lines(p, 10) == ["a", "b", "c"]
    assert cursor_agent.tail_text_file_lines(p, 2) == ["b", "c"]


def test_interpret_cursor_sdk_subprocess_success() -> None:
    raw = json.dumps({"ok": True, "text": " hello "}, ensure_ascii=False) + "\n"
    reply = cursor_agent.interpret_cursor_sdk_subprocess(raw.encode("utf-8"), b"", 0)
    assert reply == "hello"


def test_interpret_cursor_sdk_subprocess_reads_last_json_line() -> None:
    tail = {"ok": True, "text": "last"}
    raw = "noise\n" + json.dumps(tail, ensure_ascii=False)
    reply = cursor_agent.interpret_cursor_sdk_subprocess(raw.encode("utf-8"), b"", 0)
    assert reply == "last"


def test_interpret_cursor_sdk_subprocess_raises_on_sdk_error_payload() -> None:
    payload = {"ok": False, "code": "unauthenticated", "error": "short reason"}
    try:
        cursor_agent.interpret_cursor_sdk_subprocess(
            json.dumps(payload, ensure_ascii=False).encode(),
            b"",
            1,
        )
    except RuntimeError as exc:
        assert "short reason" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")


def test_merge_pending_topics_deduplicates_by_id() -> None:
    topics = cursor_agent.merge_pending_topics([
        {"id": "topic_1", "text": "first"},
        {"id": "topic_1", "text": "duplicate"},
        {"id": "topic_2", "text": "second"},
    ])

    assert topics == [
        {"id": "topic_1", "text": "first"},
        {"id": "topic_2", "text": "second"},
    ]


def test_build_reply_frames_uses_pending_count_as_pull_limit() -> None:
    frames = cursor_agent.build_reply_frames(
        "  hello from supervised agent  ",
        room_id="room_1",
        pending_count=2,
    )

    assert frames == [
        {"type": "send_message", "text": "hello from supervised agent"},
        {"type": "pull_room_topics", "room_id": "room_1", "limit": 2},
    ]


def test_build_reply_frames_rejects_empty_text() -> None:
    try:
        cursor_agent.build_reply_frames("   ", room_id="room_1", pending_count=1)
    except ValueError as exc:
        assert "must not be empty" in str(exc)
    else:
        raise AssertionError("empty reply text should be rejected")


def test_rules_reply_answers_identity_topic() -> None:
    state = cursor_agent.AgentState(room_id="room_1", room_name="Cursor")
    reply = cursor_agent.build_rules_reply(
        [{"id": "topic_1", "text": "你是谁？"}],
        state,
    )

    assert reply == "我是 Cursor Agent。"


def test_cursor_sdk_prompt_contains_room_topics_and_zenlink_hints() -> None:
    state = cursor_agent.AgentState(room_id="room_1", room_name="Cursor")
    state.recent_messages = [{"agent_name": "Human", "text": "前面的问题背景", "sent_at": "now"}]
    state.site_anchor_id = "https://x"
    state.connection_id = "c1"
    state.msgbox_hint_unread = 2
    prompt = cursor_agent.build_cursor_sdk_prompt(
        [{"id": "topic_1", "text": "在吗"}],
        state,
    )

    assert "zenheart.net" in prompt
    assert "Cursor" in prompt
    assert "在吗" in prompt
    assert "前面的问题背景" in prompt
    assert "Return only the message text" in prompt
    assert "zenlink_context" in prompt
    assert "refreshable" in prompt or "refresh" in prompt


def test_should_pull_durable_refresh_excludes_auth_ok() -> None:
    assert not cursor_agent.should_pull_durable_refresh({
        "type": "auth_ok",
        "refresh": {"path": "/v2/agent/space-self", "surface": "space_self"},
        "durability": "refreshable",
        "suggested_action": "pull",
    })


def test_should_pull_on_refreshable_even_if_suggested_none() -> None:
    assert cursor_agent.should_pull_durable_refresh({
        "type": "publish_news_ok",
        "refresh": {"path": "/v2/agent/space-self", "surface": "space_self"},
        "durability": "refreshable",
        "suggested_action": "none",
    })


def test_route_zenlink_updates_auth_and_msgbox_hints() -> None:
    st = cursor_agent.AgentState()
    cursor_agent.route_zenlink_perception_into_state(
        st,
        {"type": "auth_ok", "connection_id": "cid-1", "anchor": {"scope": "site", "id": "https://ex"}},
    )
    assert st.site_anchor_id == "https://ex"
    assert st.connection_id == "cid-1"
    cursor_agent.route_zenlink_perception_into_state(
        st,
        {
            "type": "msgbox_notify",
            "unread_count": 3,
            "anchor": {"scope": "cross_space", "id": "agent-inbox"},
        },
    )
    assert st.msgbox_hint_unread == 3


def test_surface_from_refresh_path_maps_known_surfaces() -> None:
    assert cursor_agent.surface_from_refresh_path("/v2/agent/msgbox?limit=5") == "msgbox"
    assert cursor_agent.surface_from_refresh_path("/v2/agent/space-self?limit=5") == "space_self"
    assert cursor_agent.surface_from_refresh_path("/v2/openapi.json") == "openapi"


def test_summarize_durable_payload_keeps_machine_summary_only() -> None:
    summary = cursor_agent.summarize_durable_payload(
        surface="msgbox",
        path="/v2/agent/msgbox?limit=5",
        status=200,
        content_type="application/json",
        payload={
            "messages": [
                {"id": "m1", "type": "direct_message", "payload": {"body": "large private body"}},
                {"id": "m2", "type": "system"},
            ],
            "count": 2,
        },
    )

    assert summary["ok"] is True
    assert summary["message_count"] == 2
    assert summary["message_types"] == ["direct_message", "system"]
    assert "messages" not in summary


def test_auto_provider_uses_cursor_sdk_without_template_fallback(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("CURSOR_API_KEY", raising=False)
    daemon = cursor_agent.CursorAgentDaemon(
        paths=cursor_agent.runtime_paths(tmp_path),
        base_url="https://zenheart.net",
        agent_id="agent_1",
        token="token",
        room_id="room_1",
        reconnect=False,
        cognition_provider="auto",
        auto_reply=True,
        cursor_sdk_model="composer-2",
        cognition_timeout=1,
        debug_host="127.0.0.1",
        debug_port=None,
    )

    async def fake_cursor_sdk_reply(prompt: str) -> str:
        assert "在吗" in prompt
        return "在，我在。"

    monkeypatch.setattr(daemon, "_generate_cursor_sdk_reply", fake_cursor_sdk_reply)

    reply = asyncio.run(daemon._generate_reply([{"id": "topic_1", "text": "在吗"}]))

    assert reply == "在，我在。"
    assert daemon.state.effective_cognition_provider == "cursor-sdk"


def test_connection_closed_code_parts_normalizes_int() -> None:
    exc = SimpleNamespace(code=1006)
    assert cursor_agent._connection_closed_code_parts(exc) == (1006, None)


def test_connection_closed_code_parts_normalizes_enum_like() -> None:
    code_obj = SimpleNamespace(value=1006, name="ABNORMAL_CLOSURE")
    exc = SimpleNamespace(code=code_obj)
    assert cursor_agent._connection_closed_code_parts(exc) == (1006, "ABNORMAL_CLOSURE")


def test_debug_dashboard_contains_status_events_and_frames() -> None:
    status = {"phase": "joined", "pending_topic_count": 0, "room_name": "Cursor"}
    events = [{"event": "joined"}]
    frames = [{"event": "topics_perceived", "topic_count": 0}]

    page = cursor_agent.render_debug_dashboard(status, events, frames)

    assert "Cursor Agent Debug" in page
    assert "Status" in page
    assert "Events" in page
    assert "Frames" in page
    assert "scrollTop = node.scrollHeight" in page
    assert 'http-equiv="refresh"' not in page
    assert "每约 2 秒自动刷新本页" in page
    assert "术语说明" in page
    assert "ZenLink WS" in page
    assert "data-debug-box" in page


def test_filter_frame_events_keeps_agent_relevant_events() -> None:
    frames = cursor_agent.filter_frame_events([
        {"event": "daemon_started"},
        {"event": "topics_perceived"},
        {"event": "reply_dispatched"},
    ])

    assert frames == [
        {"event": "topics_perceived"},
        {"event": "reply_dispatched"},
    ]


def test_rules_reply_explains_high_fidelity_simulation() -> None:
    state = cursor_agent.AgentState(room_id="room_1", room_name="Cursor")
    reply = cursor_agent.build_rules_reply(
        [{"id": "topic_1", "text": "请说明你如何高度模拟一个 ZenLink agent"}],
        state,
    )

    assert "/v2/agent/ws" in reply
    assert "topic_suggestions_pending" in reply
    assert "pull_room_topics" in reply
    assert "anchor" in reply or "refresh" in reply


def test_read_pid_handles_missing_and_invalid_file(tmp_path: Path) -> None:
    pid_file = tmp_path / "cursor_agent.pid"

    assert cursor_agent.read_pid(pid_file) is None

    pid_file.write_text("not-a-pid", encoding="utf-8")
    assert cursor_agent.read_pid(pid_file) is None

    pid_file.write_text("12345", encoding="utf-8")
    assert cursor_agent.read_pid(pid_file) == 12345


def test_is_pid_alive_reports_current_process() -> None:
    assert cursor_agent.is_pid_alive(os.getpid()) is True
    assert cursor_agent.is_pid_alive(-1) is False


def test_stale_pid_status_reports_dead_pid(tmp_path: Path) -> None:
    paths = cursor_agent.runtime_paths(tmp_path)
    paths.root.mkdir(parents=True, exist_ok=True)
    paths.pid_file.write_text("99999999", encoding="utf-8")

    status = cursor_agent.stale_pid_status(paths)

    assert status["ok"] is False
    assert status["running"] is False
    assert status["pid"] == 99999999


def test_parser_accepts_start_and_reply_commands() -> None:
    parser = cursor_agent.build_parser()

    start = parser.parse_args(["start", "--room-id", "room_1", "--provider", "rules", "--debug-port", "8765"])
    assert start.command == "start"
    assert start.room_id == "room_1"
    assert start.provider == "rules"
    assert start.debug_port == 8765
    assert start.auto_reply is True
    assert start.reconnect is True
    assert callable(start.func)

    reply = parser.parse_args(["reply", "--text", "answer"])
    assert reply.command == "reply"
    assert reply.text == "answer"
    assert callable(reply.func)

    refresh = parser.parse_args(["refresh", "--timeout", "3"])
    assert refresh.command == "refresh"
    assert refresh.timeout == 3.0
    assert callable(refresh.func)


def test_default_provider_is_auto(monkeypatch) -> None:
    monkeypatch.delenv("CURSOR_AGENT_PROVIDER", raising=False)
    parser = cursor_agent.build_parser()

    args = parser.parse_args(["run", "--room-id", "room_1"])

    assert args.provider == "auto"


def test_runtime_dir_global_option_must_precede_subcommand() -> None:
    parser = cursor_agent.build_parser()

    args = parser.parse_args(["--runtime-dir", "/tmp/cursor-agent", "status"])

    assert args.command == "status"
    assert args.runtime_dir == "/tmp/cursor-agent"


def test_no_auto_reply_flag_switches_to_perception_only() -> None:
    parser = cursor_agent.build_parser()

    args = parser.parse_args(["run", "--room-id", "room_1", "--no-auto-reply"])

    assert args.auto_reply is False


def test_reconnect_defaults_on_and_can_disable(monkeypatch) -> None:
    monkeypatch.delenv("CURSOR_AGENT_PROVIDER", raising=False)
    parser = cursor_agent.build_parser()
    assert parser.parse_args(["run", "--room-id", "r1"]).reconnect is True
    assert parser.parse_args(["run", "--room-id", "r1", "--no-reconnect"]).reconnect is False
    assert parser.parse_args(["run", "--room-id", "r1", "--reconnect"]).reconnect is True


def test_stop_defaults_do_not_escalate_to_kill() -> None:
    parser = cursor_agent.build_parser()
    args = parser.parse_args(["stop"])

    assert isinstance(args, argparse.Namespace)
    assert args.kill is False
    assert args.timeout == 10


def test_sdk_probe_skips_when_provider_rules(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("CURSOR_API_KEY", raising=False)
    env = tmp_path / "probe.env"
    env.write_text("\n", encoding="utf-8")
    parser = cursor_agent.build_parser()
    ns = parser.parse_args(["sdk-probe", "--env-file", str(env), "--provider", "rules"])
    assert cursor_agent.cmd_sdk_probe(ns) == 0


def test_sdk_probe_returns_missing_key_without_calling_node(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("CURSOR_API_KEY", raising=False)
    monkeypatch.setattr(cursor_agent, "optional_cursor_agent_env_paths", lambda: [])

    ran: list[Any] = []

    def boom(*_a: Any, **_k: Any) -> Any:
        ran.append(True)
        raise AssertionError("subprocess.run should not be called without api key")

    monkeypatch.setattr(cursor_agent.subprocess, "run", boom)
    monkeypatch.setattr(cursor_agent, "collect_cursor_sdk_host_issues", lambda: [])
    env = tmp_path / "probe.env"
    env.write_text("\n", encoding="utf-8")
    parser = cursor_agent.build_parser()
    ns = parser.parse_args(
        ["sdk-probe", "--env-file", str(env), "--provider", "cursor-sdk", "--probe-timeout", "9"]
    )
    assert cursor_agent.cmd_sdk_probe(ns) == 5
    assert not ran


def test_parser_accepts_sdk_probe_command() -> None:
    parser = cursor_agent.build_parser()
    ns = parser.parse_args(
        [
            "sdk-probe",
            "--env-file",
            "/tmp/z.env",
            "--provider",
            "auto",
            "--probe-timeout",
            "12",
            "--cursor-sdk-model",
            "gpt-x",
        ]
    )
    assert ns.command == "sdk-probe"
    assert ns.env_file == "/tmp/z.env"
    assert ns.probe_timeout == 12.0
    assert ns.cursor_sdk_model == "gpt-x"


def test_merge_message_id_args_dedupes() -> None:
    assert cursor_agent._merge_message_id_args(["a", "a"], "b,a") == ["a", "b"]


def test_cmd_msgbox_ack_ok(monkeypatch, tmp_path: Path, capsys: Any) -> None:
    monkeypatch.setenv("ZENLINK_AGENT_ID", "agent_a")
    monkeypatch.setenv("ZENLINK_TOKEN", "tok_a")
    env = tmp_path / "r.env"
    env.write_text("\n", encoding="utf-8")

    def fake_post(**kwargs: Any) -> tuple[int, dict[str, Any], str]:
        assert kwargs["path"] == "/v2/agent/msgbox/ack"
        assert kwargs["body"] == {"message_ids": ["m1", "m2"]}
        return 200, {"acked": 2}, "application/json"

    monkeypatch.setattr(cursor_agent, "_json_http_post_json", fake_post)
    ns = cursor_agent.build_parser().parse_args(
        [
            "msgbox-ack",
            "--env-file",
            str(env),
            "--base-url",
            "https://example.test",
            "--message-id",
            "m1",
            "--ids",
            "m2",
        ]
    )
    assert cursor_agent.cmd_msgbox_ack(ns) == 0
    out = capsys.readouterr().out.strip()
    line = json.loads(out)
    assert line["ok"] is True
    assert line["response"]["acked"] == 2


def test_cmd_msgbox_ack_requires_ids(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ZENLINK_AGENT_ID", "agent_a")
    monkeypatch.setenv("ZENLINK_TOKEN", "tok_a")
    env = tmp_path / "r.env"
    env.write_text("\n", encoding="utf-8")
    ns = cursor_agent.build_parser().parse_args(["msgbox-ack", "--env-file", str(env)])
    assert cursor_agent.cmd_msgbox_ack(ns) == 2


def test_cmd_send_dm_201(monkeypatch, tmp_path: Path, capsys: Any) -> None:
    monkeypatch.setenv("ZENLINK_AGENT_ID", "agent_a")
    monkeypatch.setenv("ZENLINK_TOKEN", "tok_a")
    env = tmp_path / "r.env"
    env.write_text("\n", encoding="utf-8")

    def fake_post(**kwargs: Any) -> tuple[int, dict[str, Any], str]:
        assert kwargs["path"] == "/v2/agent/messages/send"
        assert kwargs["body"]["to_agent_id"] == "other"
        assert kwargs["body"]["body"] == "hi"
        assert "subject" not in kwargs["body"]
        return 201, {"message_id": "mid1", "to_agent_id": "other"}, "application/json"

    monkeypatch.setattr(cursor_agent, "_json_http_post_json", fake_post)
    ns = cursor_agent.build_parser().parse_args(
        [
            "send-dm",
            "--env-file",
            str(env),
            "--to-agent-id",
            "other",
            "--body",
            "hi",
        ]
    )
    assert cursor_agent.cmd_send_dm(ns) == 0
    line = json.loads(capsys.readouterr().out.strip())
    assert line["ok"] is True
    assert line["response"]["message_id"] == "mid1"


def test_cmd_send_dm_includes_optional_subject(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ZENLINK_AGENT_ID", "agent_a")
    monkeypatch.setenv("ZENLINK_TOKEN", "tok_a")
    env = tmp_path / "e.env"
    env.write_text("\n", encoding="utf-8")

    seen: dict[str, Any] = {}

    def fake_post(**kwargs: Any) -> tuple[int, dict[str, Any], str]:
        seen["body"] = kwargs["body"]
        return 201, {"message_id": "x", "to_agent_id": "o"}, "application/json"

    monkeypatch.setattr(cursor_agent, "_json_http_post_json", fake_post)
    ns = cursor_agent.build_parser().parse_args(
        [
            "send-dm",
            "--env-file",
            str(env),
            "--to-agent-id",
            "o",
            "--body",
            "b",
            "--subject",
            "Subj",
        ]
    )
    assert cursor_agent.cmd_send_dm(ns) == 0
    assert seen["body"]["subject"] == "Subj"
