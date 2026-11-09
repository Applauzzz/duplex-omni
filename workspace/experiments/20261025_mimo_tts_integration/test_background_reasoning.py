import asyncio
import json
import unittest

from background_reasoning import BackgroundReasoning


class BackgroundTests(unittest.IsolatedAsyncioTestCase):
    async def test_pending_busy_ready_delivery_and_close(self):
        events = []
        async def send(event):
            events.append(event)
        release = asyncio.Event()
        async def execute(_call):
            await release.wait()
            return "analysis result"
        job = BackgroundReasoning(send)
        call = {"function": {"arguments": json.dumps({"task": "original question", "context": None})}}
        pending = json.loads(await job.start(call, execute))
        self.assertEqual(pending["status"], "background_pending")
        self.assertEqual(json.loads(await job.start(call, execute))["status"], "busy")
        self.assertFalse(job.ready())
        release.set()
        await job.task
        self.assertEqual(job.result()["question"], "original question")
        self.assertEqual(job.result()["result"], "analysis result")
        await job.delivered(pending["task_id"])
        self.assertFalse(job.ready())
        self.assertEqual([event["status"] for event in events], ["running", "ready", "delivered"])
        await job.close()

    async def test_cancel_disconnect_and_failed_result(self):
        async def send(_event):
            pass
        async def execute(_call):
            raise RuntimeError("private error")
        job = BackgroundReasoning(send)
        call = {"function": {"arguments": '{"task":"question","context":null}'}}
        await job.start(call, execute)
        await job.task
        self.assertTrue(job.ready())
        self.assertEqual(job.job["status"], "failed")
        self.assertNotIn("private", job.result()["result"])
        await job.close()
        release = asyncio.Event()
        async def held(_call):
            await release.wait()
        await job.start(call, held)
        task = job.task
        await job.close()
        self.assertTrue(task.cancelled())

    async def test_strict_parameters_and_sdk_error(self):
        async def send(_event):
            pass
        job = BackgroundReasoning(send)
        async def execute(_call):
            return "An error occurred while running the tool. private detail"
        for args in ([], {"task": "x"}, {"task": "x", "context": 1},
                     {"task": "x", "context": None, "async": True}):
            with self.assertRaises(RuntimeError):
                await job.start({"function": {"arguments": json.dumps(args)}}, execute)
        await job.start({"function": {"arguments": '{"task":"x","context":null}'}}, execute)
        await job.task
        self.assertEqual(job.job["status"], "failed")
        self.assertNotIn("private", job.result()["result"])
        await job.close()
