"""Reuse v0 business mutations with guardrails ON, without file/log side effects.

Only service transactions construct this adapter. Its callers supply a persisted,
already authenticated principal. Approval is checked by the service, not this flag.
"""
import copy
from threading import RLock

from cartly.tools import CartlySession, public_value


class GuardedEngine(CartlySession):
    def __init__(self, world, policy, user_id=None):
        self.guarded = True
        self._state = copy.deepcopy(world)
        self._state.setdefault("coupons", [])
        self._state.setdefault("escalations", [])
        self._policy = policy
        self.verified_user_id = user_id
        self._lock = RLock()
        self._logs = []

    def _record(self, name, args, response):
        self._logs.append({"timestamp": self.timestamp, "tool_name": name,
                           "arguments": copy.deepcopy(args), **public_value(response), "mode": "guarded"})

    def reset(self):
        raise RuntimeError("Use a new sandbox world; a conversation must not reset shared orders")
