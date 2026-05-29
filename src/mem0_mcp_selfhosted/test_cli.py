"""CLI test harness for mem0-mcp-selfhosted — bypass MCP/Claude Code for fast debug.

Usage (after installing as a script via pyproject.toml):
    mem0-test-cli init                    # chỉ init, đo thời gian
    mem0-test-cli list                    # list_entities (count users/agents/runs)
    mem0-test-cli get                     # get_all memories cho user_id mặc định
    mem0-test-cli add "Toi ten Thanh"     # add memory
    mem0-test-cli search "VPS"            # search memories

Env vars cần (như cấu hình MCP):
    MEM0_USER_ID, MEM0_QDRANT_URL, MEM0_QDRANT_API_KEY,
    MEM0_EMBED_PROVIDER, MEM0_EMBED_MODEL, MEM0_EMBED_DIMS,
    MEM0_LLM_MODEL, OPENAI_API_KEY,
    HTTP_PROXY, HTTPS_PROXY (nếu qua proxy công ty).
"""

from __future__ import annotations

import logging
import os
import sys
import time


def _setup_logging() -> None:
    """Log mọi thứ ra stdout cho terminal đọc trực tiếp."""
    log_level = os.environ.get("MEM0_LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s | %(message)s",
        stream=sys.stdout,
    )


def _check_env() -> None:
    required = ["MEM0_QDRANT_URL", "MEM0_QDRANT_API_KEY", "OPENAI_API_KEY"]
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        print(f"[ERROR] Missing env vars: {missing}")
        print("Set them in PowerShell first, ví dụ:")
        for k in missing:
            print(f'  $env:{k}="<value>"')
        sys.exit(2)


def _init() -> object:
    from mem0_mcp_selfhosted.server import _ensure_memory
    print("\n=== Init mem0 (lazy + prewarm not used in CLI mode) ===")
    t0 = time.perf_counter()
    mem = _ensure_memory()
    dt = time.perf_counter() - t0
    if mem is None:
        print(f"[FATAL] _ensure_memory returned None in {dt:.2f}s — init failed (xem log error ở trên)")
        sys.exit(3)
    print(f"=== Init OK in {dt:.2f}s ===\n")
    return mem


def cmd_init() -> None:
    _init()


def cmd_list() -> None:
    from mem0_mcp_selfhosted.helpers import list_entities_facet
    mem = _init()
    print("=== Calling list_entities_facet() ===")
    t0 = time.perf_counter()
    r = list_entities_facet(mem)
    print(f"\n=== list_entities took {time.perf_counter() - t0:.2f}s ===")
    print(r)


def cmd_get() -> None:
    mem = _init()
    user_id = os.environ.get("MEM0_USER_ID", "thanh")
    print(f"=== Calling mem.get_all(user_id={user_id!r}) ===")
    t0 = time.perf_counter()
    r = mem.get_all(user_id=user_id)
    print(f"\n=== get_all took {time.perf_counter() - t0:.2f}s ===")
    print(r)


def cmd_add(text: str) -> None:
    mem = _init()
    user_id = os.environ.get("MEM0_USER_ID", "thanh")
    print(f"=== Calling mem.add(text={text!r}, user_id={user_id!r}) ===")
    t0 = time.perf_counter()
    r = mem.add([{"role": "user", "content": text}], user_id=user_id)
    print(f"\n=== add took {time.perf_counter() - t0:.2f}s ===")
    print(r)


def cmd_search(query: str) -> None:
    mem = _init()
    user_id = os.environ.get("MEM0_USER_ID", "thanh")
    print(f"=== Calling mem.search(query={query!r}, user_id={user_id!r}) ===")
    t0 = time.perf_counter()
    r = mem.search(query=query, user_id=user_id)
    print(f"\n=== search took {time.perf_counter() - t0:.2f}s ===")
    print(r)


COMMANDS = {
    "init": (cmd_init, False),
    "list": (cmd_list, False),
    "get": (cmd_get, False),
    "add": (cmd_add, True),
    "search": (cmd_search, True),
}


def main() -> None:
    _setup_logging()
    _check_env()
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(f"Usage: mem0-test-cli <{'|'.join(COMMANDS.keys())}> [arg]")
        print("Examples:")
        print('  mem0-test-cli init')
        print('  mem0-test-cli list')
        print('  mem0-test-cli get')
        print('  mem0-test-cli add "Toi ten Thanh, lam o Ha Noi"')
        print('  mem0-test-cli search "VPS"')
        sys.exit(1)
    cmd_name = sys.argv[1]
    fn, needs_arg = COMMANDS[cmd_name]
    if needs_arg:
        if len(sys.argv) < 3:
            print(f"[ERROR] Command '{cmd_name}' cần 1 argument (vd: mem0-test-cli {cmd_name} \"...\")")
            sys.exit(1)
        fn(sys.argv[2])
    else:
        fn()


if __name__ == "__main__":
    main()
