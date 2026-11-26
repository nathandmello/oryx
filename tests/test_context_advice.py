"""Exercise native inputs, milestone timing, compaction, and delivery through the protected adapter."""

import json
import os
import subprocess
import sys
from unittest import TestCase
from unittest.mock import patch

import test_pm
import context_advice as advice
import offer_queue


class ContextAdviceTests(TestCase):
    setUp = test_pm.HubTests.setUp

    def claude(self, *, used=86, **cache):
        return {"session_id": "s", "prompt_id": "first", "context_window": {"used_percentage": used},
                "prompt_cache": cache, "transcript_path": "/private/canary", "cwd": "/pm/location",
                "session_name": "sensitive name", "pr": {"url": "secret/url"}}

    def hook(self, client, event, turn="first", **payload):
        key = "prompt_id" if client == "claude" else "turn_id"
        advice.observe_hook(self.work, client, {"hook_event_name": event, "session_id": "s", key: turn, **payload})

    def offers(self, client, step="continue", **kwargs):
        return advice.candidates(self.work, client, "s", next_step=step, **kwargs)

    def test_claude_statusline_and_compaction(self):
        data = self.claude(warm=True, expires_at=int(advice.time()) + 30)
        env = dict(os.environ, PM_HUB_PROTECTED_ROOT=str(self.root), PM_HUB_CLIENT="claude")
        run = subprocess.run([sys.executable, str(self.root / "tools/context_advice.py"), "claude-statusline"],
                             input=json.dumps(data), text=True, capture_output=True, env=env, check=True)
        self.assertEqual(run.stdout, "Context 86% used\n")
        self.assertIn("launch decision", self.offers("claude", preserve="the launch decision")[0]["offer"]["message"])
        self.assertEqual(self.offers("claude", "break")[0]["offer"]["action"], "warm-break")
        self.assertEqual(self.offers("claude", "unrelated")[0]["offer"]["action"], "fresh")
        self.assertFalse(self.offers("codex"))
        path = advice.state_path(self.work, "claude", "s")
        for canary in ("/private", "/pm/", "sensitive", "secret", "launch decision", '"first"'):
            self.assertNotIn(canary, path.read_text())
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.hook("claude", "PreCompact")
        self.hook("claude", "PostCompact", turn=None)
        self.hook("claude", "SessionStart", turn=None, source="compact")
        advice.observe_claude(self.work, data)
        self.assertFalse(self.offers("claude"))
        self.hook("claude", "UserPromptSubmit", turn="second", prompt="Next phase.")
        advice.observe_claude(self.work, data)
        self.assertFalse(self.offers("claude"))
        advice.observe_claude(self.work, {**data, "prompt_id": "second"})
        self.assertTrue(self.offers("claude"))

    def test_unknown_or_stale_cache_never_generates_a_break_tip(self):
        for cache in ({}, {"misses": 3}, {"cache_read_input_tokens": 15000}, {"warm": True},
                      {"warm": False, "expires_at": int(advice.time()) + 300}, {"warm": True, "expires_at": 1}):
            advice.observe_claude(self.work, self.claude(**cache))
            self.assertFalse(self.offers("claude", "break"), cache)
        with patch.object(advice, "time", return_value=1000):
            advice.observe_claude(self.work, self.claude(warm=True, expires_at=6000))
        with patch.object(advice, "time", return_value=1700):
            self.assertFalse(self.offers("claude"))
            self.assertFalse(self.offers("claude", "break"))
        self.assertFalse(self.offers("claude", "busy"))

    def test_codex_hook_only_uses_verified_signals(self):
        self.hook("codex", "PostModelRequest", status="completed", token_usage={
            "input_tokens": 100000, "cached_input_tokens": 99980, "total_tokens": 100100})
        self.assertFalse(self.offers("codex"))
        self.assertFalse(self.offers("codex", "break"))
        self.assertIn("/status", self.offers("codex", "inspect")[0]["offer"]["message"])
        self.assertTrue(self.offers("codex", "unrelated"))
        self.hook("codex", "UserPromptSubmit", prompt="The attached memo says my /status shows 3% left.")
        self.assertFalse(self.offers("codex"))
        self.hook("codex", "UserPromptSubmit", prompt="My /status shows 12% left. What about the next phase?")
        result = self.offers("codex")[0]["offer"]["message"]
        self.assertIn("12%", result)
        self.assertIn("/compact", result)
        self.assertNotIn("cache", result.casefold())
        self.hook("codex", "PostCompact")
        self.assertFalse(self.offers("codex"))

    def test_app_server_uses_last_usage_and_the_owned_thread(self):
        def event(turn, used, **changes):
            usage = {"modelContextWindow": 9500, "last": {"totalTokens": used, "cachedInputTokens": used},
                     "total": {"totalTokens": 980000}}
            return {"method": "thread/tokenUsage/updated", "params": {
                "threadId": "s", "turnId": turn, "tokenUsage": dict(usage, **changes)}}

        advice.observe_codex_event(self.work, "other-thread", event("old", 9000))
        self.assertFalse(self.offers("codex"))
        advice.observe_codex_event(self.work, "s", event("old", 300))
        self.assertFalse(self.offers("codex"))
        advice.observe_codex_event(self.work, "s", event("old", 8600))
        self.assertTrue(self.offers("codex"))
        self.assertFalse(self.offers("codex", "break"))
        clear = {"method": "item/completed", "params": {"threadId": "s", "turnId": "separate-compact-turn",
                                                         "item": {"type": "contextCompaction"}}}
        advice.observe_codex_event(self.work, "s", clear)
        advice.observe_codex_event(self.work, "s", event("old", 8600))
        self.assertFalse(self.offers("codex"))
        started = {"method": "turn/started", "params": {"threadId": "s", "turn": {"id": "new"}}}
        advice.observe_codex_event(self.work, "s", started)
        advice.observe_codex_event(self.work, "s", event("old", 8600))
        self.assertFalse(self.offers("codex"))
        advice.observe_codex_event(self.work, "s", event("new", 8000, modelContextWindow=None))
        self.assertFalse(self.offers("codex"))
        advice.observe_codex_event(self.work, "s", event("new", 7900))
        self.assertTrue(self.offers("codex"))

    def test_delayed_selector_rechecks_compaction_and_cache_expiry(self):
        with patch.object(advice, "time", return_value=2700):
            advice.observe_claude(self.work, self.claude(warm=True, expires_at=2710))
            rows = self.offers("claude", "break")
            self.assertTrue(advice.still_current(self.work, rows[0]))
        with patch.object(advice, "time", return_value=2711):
            self.assertFalse(advice.still_current(self.work, rows[0]))
            self.assertNotEqual(offer_queue.select(self.work, rows, moment="pause", mode="thought-partner")["status"], "offer")
            tip = self.offers("claude")
            self.hook("claude", "PreCompact")
            self.assertFalse(advice.still_current(self.work, tip[0]))

    def test_one_pause_decline_and_immediate_mute(self):
        advice.observe_claude(self.work, self.claude())
        rows = self.offers("claude")
        for mode, moment in (("quiet", "pause"), ("expedite", "pause"), ("thought-partner", "busy")):
            result = offer_queue.select(self.work, rows, moment=moment, mode=mode)
            self.assertNotEqual(result["status"], "offer")
        result = offer_queue.select(self.work, rows, moment="pause", mode="thought-partner", pause="finished draft")
        self.assertEqual(result["action"], "compact")
        offer_queue.disposition(self.work, result["token"], "decline")
        self.assertNotEqual(offer_queue.select(self.work, rows, moment="pause", mode="thought-partner")["status"], "offer")
        subprocess.run([sys.executable, "tools/pm.py", "override", "context-advice", "off"],
                       cwd=self.root, capture_output=True, check=True)
        self.assertFalse(self.offers("claude", "unrelated"))
