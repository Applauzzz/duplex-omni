"""Bounded PCM16 output paced by a monotonic, sample-duration clock."""

import asyncio
import math

from streaming_tts import PCMChunk


class PacedPCMOutput:
    def __init__(self, send, *, chunk_ms=100, lead_ms=200, buffer_ms=400):
        if (not isinstance(chunk_ms, int) or isinstance(chunk_ms, bool)
                or not 20 <= chunk_ms <= 500):
            raise ValueError("downlink_chunk_ms must be an integer within [20, 500]")
        if (not isinstance(buffer_ms, int) or isinstance(buffer_ms, bool)
                or not chunk_ms <= buffer_ms <= 60000):
            raise ValueError("downlink_buffer_ms must be within [chunk_ms, 60000]")
        if (not isinstance(lead_ms, int) or isinstance(lead_ms, bool)
                or not chunk_ms <= lead_ms <= 2000):
            raise ValueError("downlink_lead_ms must be within [chunk_ms, 2000]")
        self.send = send
        self.chunk_ms = chunk_ms
        self.lead_seconds = lead_ms / 1000
        self.queue = asyncio.Queue(maxsize=max(1, buffer_ms // chunk_ms))
        self.sample_rate = None
        self.closed = False
        self.deadline = None

    async def put(self, chunk):
        if self.closed:
            raise RuntimeError("PCM output is closed")
        rate = chunk.sample_rate_hz
        if not isinstance(rate, int) or isinstance(rate, bool) or rate <= 0:
            raise ValueError("PCM sample rate must be a positive integer")
        if len(chunk.pcm) % 2:
            raise ValueError("PCM16 data must contain complete samples")
        if self.sample_rate is not None and self.sample_rate != rate:
            raise ValueError("PCM sample rate cannot change within a response")
        self.sample_rate = rate
        size = max(1, math.floor(rate * self.chunk_ms / 1000)) * 2
        for offset in range(0, len(chunk.pcm), size):
            await self.queue.put(PCMChunk(
                chunk.pcm[offset:offset + size], rate, chunk.request_id))

    async def finish(self):
        await self.queue.put(None)

    async def _wait(self):
        if self.deadline is not None:
            await asyncio.sleep(max(0, self.deadline - asyncio.get_running_loop().time()))

    async def run(self):
        try:
            while True:
                chunk = await self.queue.get()
                if chunk is None:
                    # Sending the last slice is not the end of its audio duration.
                    await self._wait()
                    return
                duration = len(chunk.pcm) / (2 * chunk.sample_rate_hz)
                now = asyncio.get_running_loop().time()
                end = max(now, self.deadline or now) + duration
                await asyncio.sleep(max(0, end - self.lead_seconds - now))
                await self.send(chunk)
                # Re-anchor after starvation or a slow transport, not old elapsed credit.
                self.deadline = max(asyncio.get_running_loop().time(), end - duration) + duration
        finally:
            self.closed = True
            while not self.queue.empty():
                self.queue.get_nowait()
