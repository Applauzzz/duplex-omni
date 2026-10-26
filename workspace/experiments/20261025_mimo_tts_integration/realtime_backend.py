"""Bind external MiMo/TTS to the existing duplex runner and playback ledger."""

import asyncio
import base64
import io
import json
import logging
import os
from pathlib import Path
import wave

import numpy as np

from vllm_omni.engine.duplex.config import DuplexCapabilities
from vllm_omni.engine.duplex.contracts import (
    DuplexAppendPlan, DuplexOutputContext, DuplexRequestIdentity,
    DuplexStagePort, DuplexStageSubmissionResult,
)
from vllm_omni.engine.duplex.plugin import DuplexDataPlane, DuplexModelPlugin
from vllm_omni.model_executor.models.qwen3_omni.duplex.plugin import Qwen3OmniDuplexPlugin
from vllm_omni.model_executor.models.qwen3_omni.duplex.session import QwenDuplexSessionState
from vllm_omni.outputs import OmniRequestOutput

from backend import SYSTEM, MAX_AUDIO_BYTES, MAX_TEXT

LOG = logging.getLogger("mimo_tts.realtime")
AUDIO_TURN_HINT = (
    "[The audio above is the user's spoken message. Reply to it according to the "
    "system instructions; do not transcribe it.]"
)


def format_mimo_history(messages):
    """Merge consecutive user inputs without Qwen's final media-first sort."""
    formatted = []
    pending = []
    for message in messages:
        content = message.get("content")
        if content in (None, "", []):
            continue
        if message["role"] == "user":
            pending.extend([{"type": "text", "text": content}]
                           if isinstance(content, str) else content)
            continue
        if pending:
            formatted.append({"role": "user", "content": pending})
            pending = []
        formatted.append(message)
    if pending:
        formatted.append({"role": "user", "content": pending})
    return formatted


def audio_part(payload):
    raw = base64.b64decode(payload["audio"], validate=True)
    if len(raw) % 4:
        raise ValueError("Incomplete normalized PCM.")
    samples = np.frombuffer(raw, dtype="<f4")
    if not 0 < samples.size <= 16000 * 30 or not np.isfinite(samples).all():
        raise ValueError("Audio must be finite and at most 30 seconds.")
    pcm = (np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes()
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as recording:
        recording.setnchannels(1)
        recording.setsampwidth(2)
        recording.setframerate(16000)
        recording.writeframes(pcm)
    return {"type": "input_audio", "input_audio": {
        "data": base64.b64encode(buffer.getvalue()).decode("ascii"), "format": "wav",
    }}, len(pcm)


class MiMoDataPlane(DuplexDataPlane):
    def __init__(self):
        self.terminal = set()
        self.failed = set()

    def begin_request(self, request_id):
        self.terminal.discard(request_id)
        self.failed.discard(request_id)

    def is_terminal(self, request_id):
        return request_id in self.terminal

    def mark_terminal(self, request_id):
        self.terminal.add(request_id)

    def close_stream(self, request_id):
        pass

    def close_session(self, session_id, *, active_request_id=None):
        from vllm_omni.engine.duplex.contracts import duplex_resource_request_belongs_to_session
        self.terminal = {rid for rid in self.terminal
                         if not duplex_resource_request_belongs_to_session(rid, session_id)}
        self.failed = {rid for rid in self.failed
                       if not duplex_resource_request_belongs_to_session(rid, session_id)}

    def project(self, result, *, context=None):
        if not isinstance(result, dict):
            return
        for output in result.get("data_plane_outputs", []):
            if self.is_terminal(output.request_id):
                continue
            if output.request_id in self.failed and output.finished:
                # Error handling already cleared active_request_id. Complete
                # that failed model turn without rebinding a protocol response.
                yield dict(output.custom_output)
                self.failed.discard(output.request_id)
                self.mark_terminal(output.request_id)
                continue
            if output.custom_output.get("error_code"):
                self.failed.add(output.request_id)
            yield {"data_plane_request_id": output.request_id, **output.custom_output}


class MiMoTTSPlugin(DuplexModelPlugin):
    plugin_id = "mimo-qwen3-tts"

    def __init__(self):
        self.data_plane = MiMoDataPlane()

    def capabilities(self, *, max_sessions):
        return DuplexCapabilities(
            supports_model_native_turn_policy=False,
            supports_input_append=True, supports_barge_in=True,
            supports_reencode_context=True, supports_turn_commit_only=True,
            supports_core_resumable_request=False,
            supports_independent_io_streams=True, supports_realtime_endpoint=True,
            supports_multi_session=max_sessions > 1,
            supports_multi_session_same_replica=max_sessions > 1,
            supports_session_lease=True, supports_session_resume=False,
            session_admission_mode="engine_managed",
            supports_audio_truncate=True, supports_chat_completions=True,
            supports_image_input=True, supports_text_only_turn=True,
            adapter_patterns=["turn_commit"], signal_sources=["client_event", "server_policy"],
            stage_handoff_transport="external_http",
        )

    def create_session_state(self):
        return QwenDuplexSessionState()

    async def prepare_runtime_config(self, config, *, model_config):
        return self.runtime_config_for_update(config, {})

    def runtime_config_for_update(self, config, current):
        self.validate_client_extra_body(config.extra_body)
        if config.ref_audio or config.extra_body.get("realtime_tools"):
            raise ValueError("Reference audio and tool calls are not supported.")
        instructions = config.instructions or SYSTEM
        if len(instructions) > MAX_TEXT:
            raise ValueError("Instructions exceed 4096 characters.")
        max_tokens = config.max_tokens if config.max_tokens is not None else 512
        if type(max_tokens) is not int or not 16 <= max_tokens <= 1024:
            raise ValueError("max_tokens must be from 16 to 1024.")
        return {"instructions": instructions, "max_tokens": max_tokens}

    def configure_sampling_params(self, *, runtime_config, defaults):
        return defaults

    def prepare_prompt_config(self, config, *, state, payload):
        # Reuse whole-turn audio retention and empty-assistant handling.
        return Qwen3OmniDuplexPlugin.prepare_prompt_config(self, config, state=state, payload=payload)

    def plan_append(self, *, request_id, fence, session_config, runtime_config,
                    seq, turn_seq, payload, final, sampling_params):
        if not final:
            raise ValueError("MiMo inference requires a committed turn.")
        messages = [{"role": "system", "content": runtime_config["instructions"]}]
        history = session_config.get("qwen_messages", [])
        audio_bytes = 0
        text_chars = 0
        for message in history:
            if "audio_payload" in message:
                part, size = audio_part(message["audio_payload"])
                audio_bytes += size
                messages.append({"role": "user", "content": [
                    part, {"type": "text", "text": AUDIO_TURN_HINT},
                ]})
                continue
            content = message.get("content")
            if isinstance(content, str):
                text_chars += len(content)
                messages.append({"role": message["role"], "content": content})
            elif isinstance(content, list):
                parts = [part for part in content if part.get("type") in ("text", "image_url")]
                text_chars += sum(len(part.get("text", "")) for part in parts)
                messages.append({"role": message["role"], "content": parts})
        if audio_bytes > MAX_AUDIO_BYTES or text_chars > 16000:
            raise ValueError("Conversation exceeds the bounded input budget.")
        messages = format_mimo_history(messages)
        if len(messages) <= 1:
            raise ValueError("No committed user input.")
        debug_root = os.environ.get("MIMO_TTS_DEBUG_DIR")
        if debug_root:
            directory = Path(debug_root) / request_id
            directory.mkdir(parents=True, exist_ok=False)
            with (directory / "messages.json").open("x") as file:
                json.dump(messages, file, ensure_ascii=True, indent=2)
        return DuplexAppendPlan(prompt={
            "messages": messages, "max_tokens": runtime_config["max_tokens"],
        })

    def decide_output(self, **kwargs):
        return None


class ExternalStagePort(DuplexStagePort):
    """One virtual lifecycle owns the MiMo and TTS HTTP contexts together."""

    def __init__(self, backend):
        self.backend = backend
        self.manager = None
        self.tasks = {}
        self.contexts = {}

    @property
    def stage_count(self):
        return 1

    def sampling_defaults(self):
        return (None,)

    def ensure_request(self, context):
        self.contexts[context.request_id] = context

    async def submit(self, submission):
        rid = submission.context.request_id
        if rid in self.tasks:
            raise ValueError("Duplicate external stage request.")
        task = asyncio.create_task(self._run(submission), name=f"mimo-tts-{rid}")
        self.tasks[rid] = task
        return DuplexStageSubmissionResult(request_id=rid, stage_id=0, replica_id=0)

    def _output(self, submission, payload, *, finished=False):
        context = submission.context
        runner = self.manager.runners.get(context.session_id)
        if (runner is None or runner.closing or runner.session.epoch != context.fence.epoch
                or context.request_id not in self.contexts):
            return
        output = OmniRequestOutput(
            request_id=context.request_id, stage_id=0, finished=finished,
            _custom_output={"model_turn_id": context.fence.turn_id,
                            "end_of_turn": finished, **payload},
        )
        runner.on_stage_output(
            0, output, None, request_id=context.request_id,
            context=DuplexOutputContext(
                identity=DuplexRequestIdentity(context.session_id, context.fence),
                final_stage_id=0, segment_finished=finished,
            ),
        )

    async def _run(self, submission):
        rid = submission.context.request_id
        pending_audio = None
        total_samples = 0

        def send_audio(event, marks=None):
            nonlocal total_samples
            total_samples += event["samples"]
            payload = {
                "audio_data": event["pcm"], "audio_format": "pcm16",
                "sample_rate_hz": 24000,
                "audio_duration_ms": total_samples * 1000 / 24000,
                "audio_duration_is_cumulative": True, "audio_text_mark": False,
            }
            if marks:
                payload["audio_text_marks"] = marks
                payload["audio_text_marks_are_cumulative"] = True
            self._output(submission, payload)

        async def emit(event):
            nonlocal pending_audio
            kind = event["type"]
            if kind == "text":
                self._output(submission, {"text": event["delta"], "audio_text_mark": False})
            elif kind == "audio":
                if pending_audio is not None:
                    send_audio(pending_audio)
                pending_audio = event
            elif kind == "segment_done":
                if pending_audio is None:
                    raise RuntimeError("Segment ended without PCM.")
                send_audio(pending_audio, [{
                    "text_chars": event["end"],
                    "audio_end_ms": event["sample_end"] * 1000 / 24000,
                }])
                pending_audio = None
            elif kind == "done":
                if pending_audio is not None:
                    raise RuntimeError("Unfinalized PCM segment.")
                self._output(submission, {
                    "audio_complete": True, "audio_text_mark": False,
                }, finished=True)

        try:
            # submit must return before outputs enter the runner's mailbox.
            await asyncio.sleep(0)
            await self.backend.run(
                rid, submission.prompt["messages"], "vivian", "Auto",
                submission.prompt["max_tokens"], emit,
            )
        except asyncio.CancelledError:
            LOG.info("%s external stages cancelled", rid)
            raise
        except Exception as error:
            LOG.exception("%s external pipeline failed", rid)
            self._output(submission, {
                "error_code": "external_pipeline_failed", "error": str(error)[:300],
            })
            # The error closes the response; a separate terminal completes the
            # model turn and releases its request through the runner lifecycle.
            self._output(submission, {"audio_text_mark": False}, finished=True)
            runner = self.manager.runners.get(submission.context.session_id)
            if runner is not None:
                runner.spawn(self._cleanup_failed(rid, runner), name=f"cleanup-{rid}")
        finally:
            if self.tasks.get(rid) is asyncio.current_task():
                self.tasks.pop(rid, None)
            LOG.info("%s external stages finished", rid)

    async def _cleanup_failed(self, rid, runner):
        await asyncio.sleep(0)
        # A no-output terminal cannot clear the runner's streaming binding;
        # its response has already failed. Release only this request's binding.
        if runner.run.stream_request_id == rid:
            runner.model.cancel_data_plane_stream()
        runner.session.release_resources_for_request_ids([rid])
        await self.cleanup([rid])

    async def cleanup(self, request_ids, *, abort=False):
        tasks = []
        for rid in request_ids:
            self.contexts.pop(rid, None)
            task = self.tasks.pop(rid, None)
            if task is not None and task is not asyncio.current_task():
                if not task.done():
                    task.cancel()
                tasks.append(task)
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def abort_requests(self, request_ids):
        await self.cleanup(request_ids, abort=True)

    async def shutdown(self):
        await self.cleanup(list(self.contexts), abort=True)
