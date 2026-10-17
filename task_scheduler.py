"""One execution lane with stable priorities and replaceable waiting jobs."""
from dataclasses import dataclass, field
import heapq
import itertools
import threading


@dataclass(order=True)
class Task:
    priority: int
    sequence: int
    name: str = field(compare=False)
    function: object = field(compare=False)
    key: object = field(default=None, compare=False)
    generation: int = field(default=0, compare=False)
    cancelled: bool = field(default=False, compare=False)


class Scheduler:
    def __init__(self):
        self.condition = threading.Condition()
        self.heap = []
        self.counter = itertools.count()
        self.waiting = {}
        self.stopped = False
        self.active = None

    def put(self, job, priority=None, key=None, generation=0):
        with self.condition:
            if job is None:
                self.stopped = True
                for task in self.heap:
                    task.cancelled = True
                self.condition.notify_all()
                return
            name, function = job
            if self.stopped:
                return
            priority = priority if priority is not None else (30 if name == 'scan' else 0)
            if key is not None and key in self.waiting:
                self.waiting[key].cancelled = True
            task = Task(priority, next(self.counter), name, function, key, generation)
            if key is not None:
                self.waiting[key] = task
            heapq.heappush(self.heap, task)
            self.condition.notify()
            return task

    def cancel(self, key):
        with self.condition:
            task = self.waiting.pop(key, None)
            if task:
                task.cancelled = True

    def get(self):
        with self.condition:
            self.active = None
            while True:
                if self.stopped:
                    return None
                if self.heap:
                    task = heapq.heappop(self.heap)
                    if task.cancelled:
                        continue
                    if task.key is not None:
                        self.waiting.pop(task.key, None)
                    self.active = task
                    return task.name, task.function
                self.condition.wait()
