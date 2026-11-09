"""One connection-scoped reasoning job, independent of response cancellation."""

import asyncio
import json
import uuid


class BackgroundReasoning:
    def __init__(self, send):
        self.send = send
        self.job = None
        self.task = None

    async def notify(self):
        try:
            await self.send({
                "type": "agent.background.status",
                **{key: self.job[key] for key in ("task_id", "label", "status")},
            })
        except (OSError, RuntimeError):
            pass

    async def start(self, call, execute):
        args = json.loads(call["function"]["arguments"])
        question = args.get("task") if isinstance(args, dict) else None
        if (not isinstance(args, dict) or set(args) != {"task", "context"}
                or not isinstance(question, str) or not question.strip() or len(question) > 8000
                or not (args["context"] is None or
                        isinstance(args["context"], str) and len(args["context"]) <= 16000)):
            raise RuntimeError("Background reasoning requires a complete task")
        if self.job and self.job["status"] != "delivered":
            return json.dumps({"status": "busy", "task_id": self.job["task_id"]})
        self.job = {
            "task_id": uuid.uuid4().hex, "label": question[:80],
            "question": question, "status": "running", "result": None,
        }
        job = self.job
        await self.notify()

        async def run():
            try:
                job["result"] = await execute(call)
                if (isinstance(job["result"], str) and
                        job["result"].startswith("An error occurred while running the tool.")):
                    raise RuntimeError("SDK tool failed")
                job["status"] = "ready"
            except asyncio.CancelledError:
                raise
            except Exception:
                job["result"] = json.dumps({"status": "failed", "error": "reasoning_failed"})
                job["status"] = "failed"
            await self.notify()

        self.task = asyncio.create_task(run())
        return json.dumps({"status": "background_pending", "task_id": job["task_id"],
                           "question": question}, ensure_ascii=False)

    def ready(self):
        return bool(self.job and self.job["status"] in {"ready", "failed"})

    def result(self):
        if not self.ready():
            return None
        return {key: self.job[key] for key in ("task_id", "question", "result")}

    async def delivered(self, task_id):
        if self.ready() and self.job["task_id"] == task_id:
            self.job["status"] = "delivered"
            await self.notify()

    async def close(self):
        if self.task and not self.task.done():
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
        self.job = None
