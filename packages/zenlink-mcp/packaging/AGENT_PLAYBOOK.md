# zenlink-mcp OpenClaw bundle — autonomous agent playbook

This tarball is designed so an **LLM agent** can install and verify **without a human at the keyboard**, assuming **credentials and a runnable host** (Node, optional `openclaw` CLI) are already available to the agent.

**Start here:** read `zenlink-bundle.manifest.json` in this directory. It lists expected files, report line prefixes, and schemas.

## Preconditions (L0)

The agent must have, or obtain from its operator/session:

1. **Node.js** ≥ 18 (`node -v`).
2. **Secrets** (no default in the bundle): `ZENLINK_AGENT_ID`, `ZENLINK_TOKEN` from the registration email. Write them into `zenlink-deploy.env` (copy from `zenlink-deploy.env.example`) **or** export in the shell before running `install-openclaw.sh`.
3. **OS match:** use the macOS tarball on macOS and the Linux tarball on Linux (see manifest `bundle_id` / `platform_target`).
4. **OpenClaw CLI** `openclaw` on `PATH` is required for **automatic** `mcp.servers` registration. If it is missing, `install-openclaw.sh` still prints **paste JSON** on stdout and exits non-zero; read stderr for `ZENLINK_INSTALL_REPORT_JSON=`.

Optional but common for unattended inbound handling: `ZENLINK_MCP_OPENCLAW_HOOK_BASE` and `ZENLINK_MCP_OPENCLAW_HOOK_TOKEN` in `zenlink-deploy.env`. The base is the hooks directory, for example `http://127.0.0.1:18789/hooks`; zenlink-mcp posts to `/hooks/agent`.

## Golden path — one-command installer

If the operator gives you `install-zenlink-mcp-openclaw-<os>-v*.sh`, run that single file first:

```bash
bash install-zenlink-mcp-openclaw-<os>-v*.sh
```

The self-extracting installer writes the embedded tarball to a temp directory, extracts it, then runs `upgrade-offline-install.sh`. That upgrade script installs into `~/.openclaw/zenlink-mcp/current`, runs `install-openclaw.sh`, starts/restarts the daemon, restarts OpenClaw Gateway, and runs doctor checks by default. Do not manually `tar xzf` unless the one-command installer is unavailable or you are debugging.

## Fallback — tarball only

1. `tar xzf zenlink-mcp-openclaw-<macos|linux>-v*.tar.gz`
2. `cd` into the extracted top directory (single child folder named `zenlink-mcp-openclaw-...-v*`).
3. Ensure `zenlink-deploy.env` exists with valid credentials (or rely on injected env vars).
4. Prefer stable activation: `bash upgrade-offline-install.sh ../zenlink-mcp-openclaw-<macos|linux>-v*.tar.gz`. Use `bash install-openclaw.sh` only as a manual/debug fallback.
5. **Parse stderr** for a line starting with `ZENLINK_UPGRADE_REPORT_JSON=` or `ZENLINK_INSTALL_REPORT_JSON=`. Parse the JSON substring; **must** match process exit code to `exit_code`.
6. If `checks` contain any `ok: false`, treat install as failed or **degraded** if `exit_code === 0` but `degraded === true` (e.g. hook smoke failed).
7. By default the installer performs post-register activation: restarts the daemon when `ZENLINK_MCP_USE_DAEMON=1`, runs **`openclaw gateway restart`**, then calls **`zenlink_doctor`** through the daemon. Treat any `daemon_started`, `gateway_restarted`, or `zenlink_doctor` check with `ok: false` as install failure. Custom orchestrators may opt out with `ZENLINK_MCP_INSTALL_AUTO_ACTIVATE=0`.
8. If hooks are enabled, `zenlink_doctor` must not report `session_key_missing`; rerun the installer after fixing hook env if it does.
9. Verify **`zenlink_doctor`** and **`zenlink_status`** in the MCP host after reload; only that proves the new Gateway worker can reach the daemon.
10. Open `zenlink-openclaw-integration-summary.md` (beside `zenlink-mcp/`) and merge the **AGENTS.md** block into the primary agent instructions (if your host supports that).

## Golden path — stable directory + upgrades

1. Obtain the new tarball path.
2. Run: `bash upgrade-offline-install.sh /path/to/zenlink-mcp-openclaw-<os>-vNEW.tar.gz` (watch stderr for **`ZENLINK_UPGRADE_PHASE_JSON=`** progress lines, then the final **`ZENLINK_UPGRADE_REPORT_JSON=`**). Before swapping **`current/`**, this runs **`openclaw-zenlink-daemon.mjs stop --require-dead`** with **`ZENLINK_MCP_DAEMON_ADDR_FILE`** defaulted like **`install-openclaw.sh`** when unset — failure exits non-zero (**TCP still listening or PID did not exit**). Escape hatch: **`ZENLINK_MCP_UPGRADE_SKIP_DAEMON_STOP=1`** (unsafe).
3. Parse stderr for `ZENLINK_UPGRADE_REPORT_JSON=`.
4. If `ok` and exit code `0`, `post_upgrade_activation` should be `completed` unless `ZENLINK_MCP_UPGRADE_AUTO_ACTIVATE=0` was set. Then verify daemon status and **`zenlink_status`** in OpenClaw. If activation was skipped, run the reported `recommended_next_commands`.
5. On failure: see `message`; prior tree may live at `previous_current_path` (`*.prev`) — recovery is manual unless your operator scripted rollback.

Disable final summary lines with `ZENLINK_MCP_UPGRADE_REPORT=0`. Disable phase stream with `ZENLINK_MCP_UPGRADE_PHASE_EVENTS=0`.

## Parsing rules (deterministic)

- **Install:** last / only line prefixed with `ZENLINK_INSTALL_REPORT_JSON=` on **stderr**.
- **Upgrade:** same for `ZENLINK_UPGRADE_REPORT_JSON=`.
- **Disable:** `ZENLINK_MCP_INSTALL_REPORT=0` / `ZENLINK_MCP_UPGRADE_REPORT=0` removes those lines — then rely on exit codes and stderr text (not preferred for agents).
- **Bash failures before Node** inside `install-openclaw.sh` (e.g. missing `dist/cli.js`): the script emits the same **`ZENLINK_INSTALL_REPORT_JSON=`** prefix when Node is available; if Node is missing, only exit status + human stderr apply.

## Streaming phases (recommended for unattended agents)

`install-openclaw.sh` and `register-openclaw.mjs` emit **many** **`ZENLINK_INSTALL_PHASE_JSON=`** lines on **stderr**. Each parses as JSON (`schema`: **`zenlink_pipeline_phase/v1`**): `pipeline: "install"`, **`epoch_ms`**, **`component`** (`shell` = bash wrapper; `register` = Node registrar), **`phase`**, optional **`detail`**, optional **`zenlink_mcp_version`**. Prefer tailing stderr and advancing an internal **`last_seen_phase`** for timeout / stalled-run detection rather than guessing from silence.

Upgrade script emits **`ZENLINK_UPGRADE_PHASE_JSON=`** with `pipeline: "upgrade"` (same schema; includes optional **`bundle_id`** / **`zenlink_mcp_version`** from embedded pack metadata).

Opt out install phases: **`ZENLINK_MCP_INSTALL_PHASE_EVENTS=0`**. Opt out upgrade phases: **`ZENLINK_MCP_UPGRADE_PHASE_EVENTS=0`**.

## Layered verdict (“perfect install”)

| Layer | Check |
| ----- | ----- |
| L0 | Artifact layout matches `manifest.artifacts_relative`; `node zenlink-mcp/dist/cli.js --version` matches `zenlink_mcp_version`. |
| L1 | `install-openclaw.sh` exit code; JSON `exit_code`; all `checks[].ok` unless you accept intentional **degraded**. |
| L2 | Daemon supervisor up if daemon forwarding enabled: `node zenlink-mcp/scripts/openclaw-zenlink-daemon.mjs status`. |
| L3 | Install report includes `zenlink_doctor` with `ok: true` for the default OpenClaw daemon path. |
| L4 | If allowed: `openclaw mcp list` contains `mcp_server_name` from install report JSON. |
| L5 | In the MCP host: `tools/list` includes `zenlink_*` tools and `zenlink_doctor` returns no error findings. |

Only **L5** proves end-to-end tool availability to the conversation; L1–L4 are installer-side assurance.

## Idempotency

Re-running `install-openclaw.sh` after editing `zenlink-deploy.env` is expected; it refreshes `mcp.servers.*.env` in `openclaw.json`.

---

Full operator narrative (ingress/egress, room vs DM) remains in the upstream **`INTEGRATION.md`** in source control; use **`zenlink-openclaw-integration-summary.md`** produced after register when the full doc is absent.
