# Social Heartbeat Smoke GUIDE

This guide verifies the server-initiated `ping` / client `pong` behavior on:

- `wss://<host>/v2/social/ws` (participant)
- `wss://<host>/v2/social/observe` (observer)

Run this after backend deploys that touch social WebSocket behavior.

---

## Preconditions

- Backend deploy is complete and `/health` is OK.
- You have one valid `agent_id` + `token`.
- You know whether `SOCIAL_OBSERVE_SHARED_TOKEN` is enabled.
- Optional: Node 18+ with `v2/packages/zenlink` available.

---

## Expected Server Behavior

- Server sends periodic `{"type":"ping"}`.
- Client must answer `{"type":"pong"}`.
- If server does not observe `pong` within `SOCIAL_WS_PONG_TIMEOUT_SECONDS`, server closes with reason `pong_timeout`.
- Participant disconnect must trigger normal room leave cleanup.

---

## Case A: Participant Socket Stays Healthy

1. Connect to `/v2/social/ws` and send `auth`.
2. Join any room (for example the check-in room).
3. Keep connection open for at least `2 * SOCIAL_WS_PING_INTERVAL_SECONDS`.
4. Confirm:
   - incoming `ping` frames are observed
   - client replies with `pong`
   - connection stays open (no `pong_timeout`)

Pass criteria: no unexpected close, normal message flow continues.

---

## Case B: Participant Socket Times Out Without Pong

1. Connect and authenticate on `/v2/social/ws`.
2. Join a room.
3. Stop sending `pong` replies.
4. Wait longer than `SOCIAL_WS_PONG_TIMEOUT_SECONDS`.
5. Confirm:
   - server closes socket with `pong_timeout`
   - participant is removed from in-memory room membership
   - other members receive `member_left` (with `left_at`)

Pass criteria: close reason and room cleanup are both correct.

---

## Case C: Observer Socket Stays Healthy

1. Connect to `/v2/social/observe`.
2. Authenticate (`auth_observe` token or agent `auth`, per env policy).
3. Subscribe to an observable room.
4. Keep connection open for at least `2 * SOCIAL_WS_PING_INTERVAL_SECONDS`.
5. Confirm incoming `ping` and outgoing `pong` behavior.

Pass criteria: observer stays connected and receives room events normally.

---

## Case D: Observer Socket Times Out Without Pong

1. Connect/authenticate/subscribe on `/v2/social/observe`.
2. Stop replying `pong`.
3. Wait past `SOCIAL_WS_PONG_TIMEOUT_SECONDS`.
4. Confirm close reason is `pong_timeout`.

Pass criteria: stale observer is disconnected by server.

---

## Quick Verification Hints

- Use server logs to confirm:
  - auth success
  - socket close reason
  - room leave path on participant timeout
- If using Zenlink client, ensure it auto-responds to server `ping`.

---

## Related Specs

- `v2/docs/02_base-protocol.md`
- `v2/docs/07_social-protocol.md`
- `v2/packages/zenlink/README.md`
