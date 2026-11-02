# Existing Mac Tools Integration

Date: 2026-11-01. Assessment plus first echo adapter implementation.

## Implementation Update

Selected extension update: thirteen independent M2 tools now have policy,
workspace/context binding, catalog validation, durable receipt archival,
SDK execution and browser group grants. Writes require explicit confirmation;
FaceTime requires a correlated actual browser capture-stop ACK. Timer events
are accepted durably and shown in UI, not spoken. Focused v2/service/SDK
verification is five cases per module; actual Mac M2 group acceptance remains
pending its confirmed workspace IDs and native endpoint/profile setup.
The v1 status descriptions below are historical and remain preserved.

The embedded aiohttp `mac_tools.py` now implements native v1 echo authentication,
one-time explicit browser pairing, discovery, manifest negotiation, durable
dispatch/receipts and generation cancellation. Browser SDK execution uses
session-local transport context; dynamic registration uses `updateAgent`.
The backend accepts only its verified Mac outputs, including honest failures.

Focused acceptance: bridge 5/5, pinned real SDK with simulated transport 4/4,
service WebSocket tests with protocol peer/mock model 3/3; TypeScript passes.
These are complementary tests, not a unified live browser/model/Mac proof.
Real Mac and browser visual acceptance remain open. No model restart, private
production credential reuse, commit or deployment activation occurred.
Current implementation is v1 echo only; the v2/M2 design below is future scope.
Startup/private configuration and pairing are maintained in `tool_use_zh.md`.

Maintained Chinese deployment chain and complete inspected tool-use inventory:
[tool_use_zh.md](tool_use_zh.md).

## Recovery

Selected plan remains `.planning/2026-10-25-mimo-single-omni-duplex/`.
The plan's October30 SVAD head was stale relative to committed Stage6 source.
Parent baseline is `57f4abf`; agent framework baseline is `86469fd`.
Both repositories now use `feature/stage6-mac-tools`. No commit/push was made.
The historical untracked `wx_tts_ref.py` is preserved.

Existing functionality includes the custom RealtimeSession transport, native
vLLM MiMo tool parsing, audio/video admission, TTS/interruption, and the SDK
registry for search, datetime and delegated reasoning. Recovery is not fresh
runtime or browser acceptance.

## Feasibility

The tools can be integrated, but their catalogs are not executable SDK tools.
The inspected source root is:

```text
/mnt/geminihzceph/user_whynotzhliu/Omni/h20_duplex_fc_dev/
  we_duplex_demo/L20_mac_demo_20260915/SSL-PVAD/webapp/
```

| Catalog | Tool Count | Added Domains |
|---------|------------|---------------|
| fc_m2_catalog.json | 9 | echo, context, notes, timers |
| fc_travel_catalog.json | 12 | weather, places, routes |
| fc_desktop_catalog.json | 26 | reminders, calendar, documents, FaceTime |
| fc_contacts_catalog.json | 28 | contacts, contact-based FaceTime |

Counts describe cumulative source catalogs, not currently enabled tools.
Deployment history also mentions disabled note tools and separate song work;
do not infer current runtime availability from the largest catalog.

`fc_m2_runtime.M2Runtime` is a coordinator, not a local tool executor.
Business operations execute in the native Mac DuplexToolHost. Its invocation
entry point is `invoke(session, current, call_id, name, arguments)`, with
persist-before-dispatch, owner/grant validation and generation fences.

`fc_m2_routes.py` contains capabilities, scope management, device discovery,
native WebSocket bridge, event reception and receipt archival. It has no
generic HTTP execute route. The receipt POST route only archives results.
Consequently a browser fetch wrapper alone cannot complete integration.

## Integration Boundary

Preserve the existing chain:

```text
MiMo native tool_calls -> RealtimeSession tool execute
  -> server-side Mac bridge adapter -> native Mac executor
  -> validated receipt -> SDK function output
  -> same-turn MiMo final answer -> TTS
```

Reuse tool names/input/output descriptors and the `duplex-mac-tools/v2`
protocol. Preserve device authentication, explicit browser consent, negotiated
scope, owner, authorization revision, invocation identity and receipt fencing.
Do not copy credentials, pairing relationships or production SQLite data.

Map SDK call/session lifecycle to bridge call/generation lifecycle explicitly.
SDK execution must retain its current history ownership. The adapter must
cancel or invalidate old calls on semantic barge-in, reset and disconnect;
late results may be archived but must not enter a newer model turn.
Cancellation is not rollback, and unknown writes must not be auto-retried
under a new invocation ID.

Do not transplant the old Qwen LLM dialogue, ASR/VAD, conversation history,
capture or playback implementation. The current MiMo parser stays unchanged.
Tool availability is the intersection of implemented descriptors, configured
policy, user grants and negotiated active Mac capabilities, not a static
28-tool manifest.

## First Slice

1. Adapt authenticated binding/discovery/manifest and the invocation boundary
   for `demo_echo` only. Add the SDK implementation through the existing
   registry; expose it only when its device is ready and authorized.
2. Verify a real RealtimeSession -> bridge -> receipt -> same-turn reply path
   using a protocol-compatible test peer, then one real Mac invocation.
3. Expand a small useful read-only subset, such as weather or document folders.
   Place/route and document IDs require observed owner-scoped receipts.
4. Accept reminder/calendar writes independently with revision/confirmation
   and idempotency behavior.
5. Handle FaceTime capture-pause ACK and timer.finished unsolicited events as
   separate workflows. Defer song integration until its executor contract is
   inspected independently.

The adapter's hosting boundary still needs implementation-level evaluation:
reuse/extract the model-independent bridge components or operate a separate
tool-only service. Neither option is selected merely by importing the old
runtime; old core dependencies must be made explicit.

## Verification Gate

At most five directly relevant test cases per modified module, prioritizing:

1. SDK invocation -> bridge result -> same-turn final reply.
2. Missing device or revoked grant prevents dispatch.
3. Barge-in cancels the pending call; late receipt cannot affect a new turn.
4. Timeout/unknown result is honest and not automatically re-executed.
5. Duplicate receipt is idempotent and owner mismatch is rejected.

Actual device acceptance follows the protocol-compatible tests. Mock echo,
historical test totals, health or a nonempty output are not real Mac evidence.

## This Session

Read-only source/JSON inspection and Git branch creation completed. No inference
code, tool implementation, external workspace, service, environment, checkpoint
or credentials changed. No tests were run because this slice changed only
planning/documentation and branches. Interpreter/import validation is required
before subsequent tests or service startup.
