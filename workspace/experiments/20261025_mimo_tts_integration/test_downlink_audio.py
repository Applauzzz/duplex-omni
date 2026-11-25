import asyncio
import unittest

from downlink_audio import PacedPCMOutput
from streaming_tts import PCMChunk


class DownlinkTests(unittest.IsolatedAsyncioTestCase):
    async def test_duration_and_lossless_slices(self):
        sent = []
        async def send(chunk):
            sent.append((asyncio.get_running_loop().time(), chunk))
        output = PacedPCMOutput(send, chunk_ms=20, lead_ms=40, buffer_ms=100)
        pcm = bytes(range(120))
        await output.put(PCMChunk(pcm, 1000, "r1"))
        await output.finish()
        await output.run()
        self.assertEqual(b"".join(c.pcm for _, c in sent), pcm)
        self.assertEqual([len(c.pcm) for _, c in sent], [40, 40, 40])
        self.assertTrue(all(c.request_id == "r1" for _, c in sent))
        self.assertLess(sent[1][0] - sent[0][0], .015)
        self.assertGreaterEqual(sent[-1][0] - sent[0][0], .018)
        self.assertGreaterEqual(asyncio.get_running_loop().time() - sent[-1][0], .035)

    async def test_backpressure_and_cancel_clears_queue(self):
        sent = asyncio.Event()
        async def send(_):
            sent.set()
        output = PacedPCMOutput(send, chunk_ms=100, buffer_ms=100)
        task = asyncio.create_task(output.run())
        producer = asyncio.create_task(output.put(PCMChunk(b"\1\0" * 1000, 1000, "r")))
        await sent.wait()
        await asyncio.sleep(.01)
        self.assertFalse(producer.done())
        task.cancel()
        producer.cancel()
        await asyncio.gather(task, producer, return_exceptions=True)
        self.assertTrue(output.closed)
        self.assertTrue(output.queue.empty())

    async def test_starvation_does_not_burst(self):
        times = []
        async def send(_):
            times.append(asyncio.get_running_loop().time())
        output = PacedPCMOutput(send, chunk_ms=20, lead_ms=20, buffer_ms=100)
        task = asyncio.create_task(output.run())
        await output.put(PCMChunk(b"\1\0" * 20, 1000, "r"))
        await asyncio.sleep(.07)
        await output.put(PCMChunk(b"\1\0" * 40, 1000, "r"))
        await output.finish()
        await task
        self.assertGreaterEqual(times[2] - times[1], .018)

    async def test_validation_and_empty_audio(self):
        with self.assertRaises(ValueError):
            PacedPCMOutput(None, chunk_ms=True)
        with self.assertRaises(ValueError):
            PacedPCMOutput(None, buffer_ms=50)
        with self.assertRaises(ValueError):
            PacedPCMOutput(None, lead_ms=50)
        output = PacedPCMOutput(None)
        with self.assertRaises(ValueError):
            await output.put(PCMChunk(b"\1", 24000, "r"))
        await output.put(PCMChunk(b"", 24000, "r"))
        with self.assertRaises(ValueError):
            await output.put(PCMChunk(b"\0\0", 16000, "r"))
        await output.finish()
        await output.run()


if __name__ == "__main__":
    unittest.main()
