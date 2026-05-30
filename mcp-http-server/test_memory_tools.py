#!/usr/bin/env python3
"""Tests cho add_memory / search_memories tools trong MCP HTTP server.
Khong goi mang that: monkeypatch call_memory. Chay: python mcp-http-server/test_memory_tools.py
"""
import asyncio
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("ARCHIVE_URL", "http://x")
os.environ.setdefault("ARCHIVE_AUTH_TOKEN", "t")
os.environ.setdefault("MCP_BEARER_TOKEN", "t")
import app  # noqa: E402


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class TestToolsListed(unittest.TestCase):
    def test_new_tools_present(self):
        names = {t["name"] for t in app.TOOLS}
        self.assertIn("add_memory", names)
        self.assertIn("search_memories", names)

    def test_add_memory_schema(self):
        t = next(t for t in app.TOOLS if t["name"] == "add_memory")
        self.assertIn("text", t["inputSchema"]["properties"])
        self.assertEqual(t["inputSchema"]["required"], ["text"])

    def test_search_memories_schema(self):
        t = next(t for t in app.TOOLS if t["name"] == "search_memories")
        self.assertEqual(t["inputSchema"]["required"], ["query"])


class TestExecMemoryTools(unittest.TestCase):
    def setUp(self):
        self.calls = []

        async def fake_memory(method, path, **kwargs):
            self.calls.append((method, path, kwargs))
            return {"ok": True}
        self._orig = app.call_memory
        app.call_memory = fake_memory

    def tearDown(self):
        app.call_memory = self._orig

    def test_add_memory_posts_text_and_user(self):
        run(app.exec_tool("add_memory", {"text": "Thanh thich Haiku"}))
        method, path, kwargs = self.calls[0]
        self.assertEqual((method, path), ("POST", "/memories"))
        self.assertEqual(kwargs["json"]["text"], "Thanh thich Haiku")
        self.assertEqual(kwargs["json"]["user_id"], app.USER_ID)

    def test_add_memory_passes_metadata(self):
        run(app.exec_tool("add_memory", {"text": "x", "metadata": {"project": "mem0"}}))
        self.assertEqual(self.calls[0][2]["json"]["metadata"], {"project": "mem0"})

    def test_add_memory_no_metadata_when_absent(self):
        run(app.exec_tool("add_memory", {"text": "x"}))
        self.assertNotIn("metadata", self.calls[0][2]["json"])

    def test_search_memories_posts_query(self):
        run(app.exec_tool("search_memories", {"query": "haiku", "limit": 5}))
        method, path, kwargs = self.calls[0]
        self.assertEqual((method, path), ("POST", "/memories/search"))
        self.assertEqual(kwargs["json"]["query"], "haiku")
        self.assertEqual(kwargs["json"]["limit"], 5)
        self.assertEqual(kwargs["json"]["user_id"], app.USER_ID)

    def test_search_memories_default_limit(self):
        run(app.exec_tool("search_memories", {"query": "x"}))
        self.assertEqual(self.calls[0][2]["json"]["limit"], 10)


if __name__ == "__main__":
    unittest.main(verbosity=2)
