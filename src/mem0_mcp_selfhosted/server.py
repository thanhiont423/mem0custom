"""FastMCP server for mem0-mcp-selfhosted — full action logging build.

[CUSTOM-DEBUG] Edition: log mọi tool call (vị trí, args, kết quả, thời gian),
mọi step trong _init_memory, mọi lần gọi mem0ai, kèm cấu hình stderr-WARNING
để stderr pipe không bao giờ làm nghẽn server.
"""

from __future__ import annotations

import functools
import json
import logging
import os
import sys
import threading
import time
from typing import Annotated, Any

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from pydantic import Field

from mem0_mcp_selfhosted.config import ProviderInfo, build_config
from mem0_mcp_selfhosted.env import bool_env, env
# v0.3.9: graph_tools imported lazily in mcp_search_graph/mcp_get_entity
# (saves loading neo4j-related code when MEM0_ENABLE_GRAPH=false)
from mem0_mcp_selfhosted.helpers import (
    _mem0_call,
    call_with_graph,
    get_default_user_id,
    list_entities_facet,
    patch_gemini_parse_response,
    patch_graph_sanitizer,
    safe_bulk_delete,
)

logger = logging.getLogger(__name__)

memory = None
mcp: FastMCP | None = None
_enable_graph_default = False

_memory_init_lock = threading.Lock()
_last_init_failure: float = 0.0
_INIT_RETRY_COOLDOWN = 30.0


def _summarize(value: Any, max_len: int = 200) -> str:
    """[CUSTOM-DEBUG] Compact repr of any payload for logs — truncates long text."""
    try:
        s = repr(value) if not isinstance(value, str) else value
    except Exception:
        return f"<unreprable {type(value).__name__}>"
    if len(s) > max_len:
        return s[:max_len] + f"...(len={len(s)})"
    return s


def _log_call(label: str, **fields: Any) -> float:
    """[CUSTOM-DEBUG] Log entry of a function. Returns t0 for caller to time end."""
    parts = " ".join(f"{k}={_summarize(v, 100)}" for k, v in fields.items())
    logger.info("[TOOL] >>> %s %s", label, parts)
    return time.perf_counter()


def _log_done(label: str, t0: float, **fields: Any) -> None:
    """[CUSTOM-DEBUG] Log successful completion + duration."""
    parts = " ".join(f"{k}={_summarize(v, 200)}" for k, v in fields.items())
    logger.info("[TOOL] <<< %s OK in %.2fs %s", label, time.perf_counter() - t0, parts)


def _log_fail(label: str, t0: float, exc: BaseException) -> None:
    """[CUSTOM-DEBUG] Log failed completion."""
    logger.error(
        "[TOOL] <<< %s FAIL in %.2fs exc=%s msg=%s",
        label, time.perf_counter() - t0, type(exc).__name__, _summarize(str(exc), 300),
    )


def register_providers(providers_info: list[ProviderInfo]) -> None:
    """Register custom LLM providers with mem0ai's LlmFactory."""
    if not providers_info:
        return

    logger.info("[ACTION] register_providers: import LlmFactory START")
    _t = time.perf_counter()
    from mem0.utils.factory import LlmFactory
    logger.info(
        "[ACTION] register_providers: import LlmFactory DONE in %.2fs",
        time.perf_counter() - _t,
    )

    for pi in providers_info:
        logger.info("[ACTION] register_providers: resolve %r START", pi["name"])
        _t = time.perf_counter()
        config_class = _resolve_config_class(pi["name"])
        logger.info(
            "[ACTION] register_providers: resolve %r DONE in %.2fs class_path=%s",
            pi["name"], time.perf_counter() - _t, pi.get("class_path"),
        )
        if config_class is None:
            logger.warning("No config class for provider %r, skipping", pi["name"])
            continue
        LlmFactory.register_provider(
            name=pi["name"],
            class_path=pi["class_path"],
            config_class=config_class,
        )


def _resolve_config_class(provider_name: str) -> type | None:
    if provider_name == "ollama":
        from mem0.configs.llms.ollama import OllamaConfig
        return OllamaConfig
    if provider_name in ("anthropic", "anthropic_oat"):
        from mem0_mcp_selfhosted.llm_anthropic import AnthropicOATConfig
        return AnthropicOATConfig
    return None


def _init_memory() -> Any:
    """Initialize mem0ai Memory with config and registered providers."""
    global memory, _enable_graph_default

    logger.info("[ACTION] _init_memory: build_config() START")
    _t = time.perf_counter()
    config_dict, providers_info, split_config = build_config()
    logger.info(
        "[ACTION] _init_memory: build_config() DONE in %.2fs llm=%s/%s embed=%s/%s qdrant=%s graph=%s",
        time.perf_counter() - _t,
        config_dict.get("llm", {}).get("provider"),
        config_dict.get("llm", {}).get("config", {}).get("model"),
        config_dict.get("embedder", {}).get("provider"),
        config_dict.get("embedder", {}).get("config", {}).get("model"),
        config_dict.get("vector_store", {}).get("config", {}).get("url"),
        "yes" if config_dict.get("graph_store") else "no",
    )

    logger.info("[ACTION] _init_memory: register_providers() START")
    _t = time.perf_counter()
    register_providers(providers_info)
    logger.info(
        "[ACTION] _init_memory: register_providers() DONE in %.2fs",
        time.perf_counter() - _t,
    )

    # v0.3.9: Conditional patches - skip when not needed
    # patch_graph_sanitizer only needed if graph enabled (Neo4j Cypher compliance)
    # patch_gemini_parse_response only needed if graph LLM is gemini
    logger.info("[ACTION] _init_memory: patches START")
    _t = time.perf_counter()
    _enable_graph = bool_env("MEM0_ENABLE_GRAPH")
    if _enable_graph:
        patch_graph_sanitizer()
        graph_llm_provider = env("MEM0_GRAPH_LLM_PROVIDER", env("MEM0_PROVIDER", "anthropic"))
        if graph_llm_provider in ("gemini", "gemini_split"):
            patch_gemini_parse_response()
    logger.info(
        "[ACTION] _init_memory: patches DONE in %.2fs (graph=%s)",
        time.perf_counter() - _t, _enable_graph,
    )

    logger.info("[ACTION] _init_memory: import mem0.Memory START")
    _t = time.perf_counter()
    from mem0 import Memory
    logger.info(
        "[ACTION] _init_memory: import mem0.Memory DONE in %.2fs",
        time.perf_counter() - _t,
    )

    logger.info("[ACTION] _init_memory: Memory.from_config() START")
    _t = time.perf_counter()
    memory = Memory.from_config(config_dict)
    logger.info(
        "[ACTION] _init_memory: Memory.from_config() DONE in %.2fs",
        time.perf_counter() - _t,
    )

    if split_config and memory.graph is not None:
        from mem0_mcp_selfhosted.llm_router import SplitModelGraphLLM, SplitModelGraphLLMConfig
        router_config = SplitModelGraphLLMConfig(**split_config)
        memory.graph.llm = SplitModelGraphLLM(router_config)

    _enable_graph_default = bool_env("MEM0_ENABLE_GRAPH")
    _instrument_memory(memory)
    return memory


def _instrument_memory(mem: Any) -> None:
    """[CUSTOM-DEBUG] Wrap embedder + vector store methods with timing logs."""

    def _wrap(obj: Any, method_name: str, label: str) -> None:
        if obj is None or not hasattr(obj, method_name):
            return
        orig = getattr(obj, method_name)
        if getattr(orig, "_custom_timed", False):
            return

        @functools.wraps(orig)
        def timed(*args: Any, **kwargs: Any) -> Any:
            _t0 = time.perf_counter()
            logger.info("[CALL] %s START args=%s kwargs=%s",
                        label, _summarize(args, 100), _summarize(list(kwargs.keys()), 100))
            try:
                result = orig(*args, **kwargs)
                logger.info("[CALL] %s OK in %.2fs", label, time.perf_counter() - _t0)
                return result
            except Exception as exc:
                logger.error("[CALL] %s FAIL in %.2fs exc=%s: %s",
                             label, time.perf_counter() - _t0, type(exc).__name__, exc)
                raise

        timed._custom_timed = True
        setattr(obj, method_name, timed)
        logger.info("[CUSTOM-DEBUG] Instrumented %s", label)

    _wrap(getattr(mem, "embedding_model", None), "embed", "embedder.embed")
    vs = getattr(mem, "vector_store", None)
    _wrap(vs, "search", "qdrant.search")
    _wrap(vs, "insert", "qdrant.insert")
    _wrap(vs, "list", "qdrant.list")
    _wrap(vs, "get", "qdrant.get")
    _wrap(vs, "delete", "qdrant.delete")
    _wrap(vs, "update", "qdrant.update")


def _ensure_memory() -> Any:
    """Lazy-initialize Memory on first tool call."""
    global memory, _last_init_failure

    if memory is not None:
        logger.info("[ACTION] _ensure_memory: cached (returning existing)")
        return memory

    now = time.monotonic()
    if _last_init_failure and (now - _last_init_failure < _INIT_RETRY_COOLDOWN):
        logger.warning(
            "[ACTION] _ensure_memory: skipping retry, cooldown %.0fs since last failure",
            now - _last_init_failure,
        )
        return None

    logger.info("[ACTION] _ensure_memory: acquiring _memory_init_lock")
    with _memory_init_lock:
        logger.info("[ACTION] _ensure_memory: lock acquired")
        if memory is not None:
            return memory
        try:
            _init_memory()
            logger.info("[ACTION] _ensure_memory: mem0ai Memory initialized successfully (lazy)")
        except Exception as exc:
            _last_init_failure = time.monotonic()
            logger.error("[ACTION] _ensure_memory: Lazy Memory init FAILED: %s", exc, exc_info=True)
            return None

    return memory


def _create_server() -> FastMCP:
    global mcp
    host = env("MEM0_HOST", "0.0.0.0")
    port = int(env("MEM0_PORT", "8081"))
    mcp = FastMCP(
        "mem0",
        host=host,
        port=port,
        instructions=(
            "Memory tools for persistent cross-session memory. "
            "Use search_memories to find relevant context before starting work. "
            "Use add_memory to store important facts, preferences, and decisions."
        ),
    )
    _register_tools(mcp)
    _register_prompts(mcp)

    # Optional: register archive tools if ARCHIVE_URL env var is set.
    # Lazy import so this module has no hard dependency on archive_tools
    # (older builds without archive_tools.py still work).
    try:
        from mem0_mcp_selfhosted.archive_tools import register_archive_tools
        register_archive_tools(mcp)
    except ImportError as _exc:
        logger.info("[ACTION] archive_tools module not found - skipping archive tools (%s)", _exc)
    except Exception as _exc:
        logger.warning("[ACTION] register_archive_tools FAILED: %s - continuing without archive", _exc)

    return mcp


def _register_tools(mcp: FastMCP) -> None:
    """Register all MCP tools — inline START/END logs to bypass FastMCP wrapping."""

    @mcp.tool()
    def add_memory(
        text: Annotated[str, Field(description="Text to store as a memory.")],
        messages: Annotated[list[dict] | None, Field(description="Conversation history.")] = None,
        user_id: Annotated[str | None, Field(description="User scope.")] = None,
        agent_id: Annotated[str | None, Field(description="Agent scope.")] = None,
        run_id: Annotated[str | None, Field(description="Run scope.")] = None,
        metadata: Annotated[dict | None, Field(description="Metadata JSON.")] = None,
        infer: Annotated[bool | None, Field(description="LLM extract facts.")] = None,
        enable_graph: Annotated[bool | None, Field(description="Graph toggle.")] = None,
    ) -> str:
        """Store a new memory."""
        uid = user_id or get_default_user_id()
        _t0 = _log_call(
            "add_memory",
            text=text, user_id=uid, agent_id=agent_id, run_id=run_id,
            metadata=metadata, infer=infer, enable_graph=enable_graph,
        )
        try:
            if messages:
                msgs = messages
            else:
                msgs = [{"role": "user", "content": text}]

            kwargs: dict[str, Any] = {"user_id": uid}
            if agent_id:
                kwargs["agent_id"] = agent_id
            if run_id:
                kwargs["run_id"] = run_id
            if metadata:
                kwargs["metadata"] = metadata
            if infer is not None:
                kwargs["infer"] = infer

            mem = _ensure_memory()
            if mem is None:
                logger.error("[TOOL] add_memory: mem is None — returning error")
                result = json.dumps({"error": "Memory not initialized"}, ensure_ascii=False)
                _log_done("add_memory", _t0, result="<error: not initialized>")
                return result

            def _do_add():
                logger.info("[CALL] mem.add() START msgs_count=%d kwargs=%s", len(msgs), kwargs)
                _t = time.perf_counter()
                try:
                    r = mem.add(msgs, **kwargs)
                    logger.info(
                        "[CALL] mem.add() OK in %.2fs result=%s",
                        time.perf_counter() - _t, _summarize(r, 400),
                    )
                    return r
                except Exception as exc:
                    logger.error(
                        "[CALL] mem.add() FAIL in %.2fs exc=%s: %s",
                        time.perf_counter() - _t, type(exc).__name__, exc,
                    )
                    raise

            result = _mem0_call(call_with_graph, mem, enable_graph, _enable_graph_default, _do_add)
            _log_done("add_memory", _t0, result=result)
            return result
        except Exception as exc:
            _log_fail("add_memory", _t0, exc)
            raise

    @mcp.tool()
    def search_memories(
        query: Annotated[str, Field(description="Search query.")],
        user_id: Annotated[str | None, Field(description="User scope.")] = None,
        agent_id: Annotated[str | None, Field(description="Agent scope.")] = None,
        run_id: Annotated[str | None, Field(description="Run scope.")] = None,
        filters: Annotated[dict | None, Field(description="Filters.")] = None,
        limit: Annotated[int | None, Field(description="Max results.")] = None,
        threshold: Annotated[float | None, Field(description="Min score.")] = None,
        rerank: Annotated[bool | None, Field(description="Rerank.")] = None,
        enable_graph: Annotated[bool | None, Field(description="Graph toggle.")] = None,
    ) -> str:
        """Semantic search across existing memories."""
        uid = user_id or get_default_user_id()
        _t0 = _log_call(
            "search_memories",
            query=query, user_id=uid, agent_id=agent_id, run_id=run_id,
            filters=filters, limit=limit, threshold=threshold, rerank=rerank,
            enable_graph=enable_graph,
        )
        try:
            # [CUSTOM-FIX] mem0ai 1.x: user_id/agent_id/run_id PHẢI top-level
            # (chỉ mem0ai 2.x mới đòi đặt trong filters). Custom server pin <2.0.
            kwargs: dict[str, Any] = {"query": query, "user_id": uid}
            if agent_id:
                kwargs["agent_id"] = agent_id
            if run_id:
                kwargs["run_id"] = run_id
            if filters:
                kwargs["filters"] = filters
            if limit is not None:
                kwargs["limit"] = limit
            if threshold is not None:
                kwargs["threshold"] = threshold
            if rerank is not None:
                kwargs["rerank"] = rerank

            mem = _ensure_memory()
            if mem is None:
                result = json.dumps({"error": "Memory not initialized"}, ensure_ascii=False)
                _log_done("search_memories", _t0, result="<error: not initialized>")
                return result

            def _do_search():
                logger.info("[CALL] mem.search() START kwargs=%s", kwargs)
                _t = time.perf_counter()
                try:
                    r = mem.search(**kwargs)
                    n = len(r.get("results", [])) if isinstance(r, dict) else "?"
                    logger.info("[CALL] mem.search() OK in %.2fs num_results=%s",
                                time.perf_counter() - _t, n)
                    return r
                except Exception as exc:
                    logger.error("[CALL] mem.search() FAIL in %.2fs exc=%s: %s",
                                 time.perf_counter() - _t, type(exc).__name__, exc)
                    raise

            result = _mem0_call(call_with_graph, mem, enable_graph, _enable_graph_default, _do_search)
            _log_done("search_memories", _t0, result=result)
            return result
        except Exception as exc:
            _log_fail("search_memories", _t0, exc)
            raise

    @mcp.tool()
    def get_memories(
        user_id: Annotated[str | None, Field(description="User scope.")] = None,
        agent_id: Annotated[str | None, Field(description="Agent scope.")] = None,
        run_id: Annotated[str | None, Field(description="Run scope.")] = None,
        limit: Annotated[int | None, Field(description="Max results.")] = None,
    ) -> str:
        """Page through memories using filters."""
        uid = user_id or get_default_user_id()
        _t0 = _log_call("get_memories", user_id=uid, agent_id=agent_id, run_id=run_id, limit=limit)
        try:
            # [CUSTOM-FIX] mem0ai 1.x: user_id top-level (giống search)
            kwargs: dict[str, Any] = {"user_id": uid}
            if agent_id:
                kwargs["agent_id"] = agent_id
            if run_id:
                kwargs["run_id"] = run_id
            if limit is not None:
                kwargs["limit"] = limit

            mem = _ensure_memory()
            if mem is None:
                result = json.dumps({"error": "Memory not initialized"}, ensure_ascii=False)
                _log_done("get_memories", _t0, result="<error: not initialized>")
                return result

            def _do_get_all():
                logger.info("[CALL] mem.get_all() START kwargs=%s", kwargs)
                _t = time.perf_counter()
                try:
                    r = mem.get_all(**kwargs)
                    n = len(r.get("results", [])) if isinstance(r, dict) else "?"
                    logger.info("[CALL] mem.get_all() OK in %.2fs num_results=%s",
                                time.perf_counter() - _t, n)
                    return r
                except Exception as exc:
                    logger.error("[CALL] mem.get_all() FAIL in %.2fs exc=%s: %s",
                                 time.perf_counter() - _t, type(exc).__name__, exc)
                    raise

            result = _mem0_call(_do_get_all)
            _log_done("get_memories", _t0, result=result)
            return result
        except Exception as exc:
            _log_fail("get_memories", _t0, exc)
            raise

    @mcp.tool()
    def get_memory(memory_id: Annotated[str, Field(description="Memory UUID.")]) -> str:
        """Fetch a single memory by ID."""
        _t0 = _log_call("get_memory", memory_id=memory_id)
        try:
            mem = _ensure_memory()
            if mem is None:
                result = json.dumps({"error": "Memory not initialized"}, ensure_ascii=False)
                _log_done("get_memory", _t0, result="<error>")
                return result
            def _do_get():
                logger.info("[CALL] mem.get(%r) START", memory_id)
                _t = time.perf_counter()
                r = mem.get(memory_id)
                logger.info("[CALL] mem.get() OK in %.2fs", time.perf_counter() - _t)
                return r
            result = _mem0_call(_do_get)
            _log_done("get_memory", _t0, result=result)
            return result
        except Exception as exc:
            _log_fail("get_memory", _t0, exc)
            raise

    @mcp.tool()
    def update_memory(
        memory_id: Annotated[str, Field(description="Memory UUID.")],
        text: Annotated[str, Field(description="New text.")],
    ) -> str:
        """Overwrite an existing memory's text."""
        _t0 = _log_call("update_memory", memory_id=memory_id, text=text)
        try:
            mem = _ensure_memory()
            if mem is None:
                result = json.dumps({"error": "Memory not initialized"}, ensure_ascii=False)
                _log_done("update_memory", _t0, result="<error>")
                return result
            def _do_update():
                logger.info("[CALL] mem.update(memory_id=%r, data_len=%d) START", memory_id, len(text))
                _t = time.perf_counter()
                mem.update(memory_id, data=text)
                logger.info("[CALL] mem.update() OK in %.2fs", time.perf_counter() - _t)
                return {"message": "Memory updated successfully!"}
            result = _mem0_call(_do_update)
            _log_done("update_memory", _t0, result=result)
            return result
        except Exception as exc:
            _log_fail("update_memory", _t0, exc)
            raise

    @mcp.tool()
    def delete_memory(memory_id: Annotated[str, Field(description="Memory UUID.")]) -> str:
        """Delete a single memory."""
        _t0 = _log_call("delete_memory", memory_id=memory_id)
        try:
            mem = _ensure_memory()
            if mem is None:
                result = json.dumps({"error": "Memory not initialized"}, ensure_ascii=False)
                _log_done("delete_memory", _t0, result="<error>")
                return result
            def _do_delete():
                logger.info("[CALL] mem.delete(%r) START", memory_id)
                _t = time.perf_counter()
                mem.delete(memory_id)
                logger.info("[CALL] mem.delete() OK in %.2fs", time.perf_counter() - _t)
                return {"message": "Memory deleted successfully!"}
            result = _mem0_call(_do_delete)
            _log_done("delete_memory", _t0, result=result)
            return result
        except Exception as exc:
            _log_fail("delete_memory", _t0, exc)
            raise

    @mcp.tool()
    def delete_all_memories(
        user_id: Annotated[str | None, Field(description="User scope.")] = None,
        agent_id: Annotated[str | None, Field(description="Agent scope.")] = None,
        run_id: Annotated[str | None, Field(description="Run scope.")] = None,
    ) -> str:
        """Bulk-delete all memories in scope."""
        uid = user_id or get_default_user_id()
        _t0 = _log_call("delete_all_memories", user_id=uid, agent_id=agent_id, run_id=run_id)
        try:
            if not any([uid, agent_id, run_id]):
                result = json.dumps({"error": "At least one scope required."}, ensure_ascii=False)
                _log_done("delete_all_memories", _t0, result="<error: no scope>")
                return result
            filters: dict[str, Any] = {}
            if uid:
                filters["user_id"] = uid
            if agent_id:
                filters["agent_id"] = agent_id
            if run_id:
                filters["run_id"] = run_id
            mem = _ensure_memory()
            if mem is None:
                result = json.dumps({"error": "Memory not initialized"}, ensure_ascii=False)
                _log_done("delete_all_memories", _t0, result="<error: not initialized>")
                return result
            def _do_bulk_delete():
                logger.info("[CALL] safe_bulk_delete(filters=%s, graph_enabled=%s) START",
                            filters, _enable_graph_default)
                _t = time.perf_counter()
                count = safe_bulk_delete(mem, filters, graph_enabled=_enable_graph_default)
                logger.info("[CALL] safe_bulk_delete() OK in %.2fs deleted=%d",
                            time.perf_counter() - _t, count)
                return {"message": f"Deleted {count} memories.", "count": count}
            result = _mem0_call(_do_bulk_delete)
            _log_done("delete_all_memories", _t0, result=result)
            return result
        except Exception as exc:
            _log_fail("delete_all_memories", _t0, exc)
            raise

    @mcp.tool()
    def list_entities() -> str:
        """List which users/agents/runs hold memories."""
        _t0 = _log_call("list_entities")
        try:
            mem = _ensure_memory()
            if mem is None:
                result = json.dumps({"error": "Memory not initialized"}, ensure_ascii=False)
                _log_done("list_entities", _t0, result="<error>")
                return result
            def _do_list():
                logger.info("[CALL] list_entities_facet() START")
                _t = time.perf_counter()
                r = list_entities_facet(mem)
                logger.info("[CALL] list_entities_facet() OK in %.2fs result=%s",
                            time.perf_counter() - _t, _summarize(r, 200))
                return r
            result = _mem0_call(_do_list)
            _log_done("list_entities", _t0, result=result)
            return result
        except Exception as exc:
            _log_fail("list_entities", _t0, exc)
            raise

    @mcp.tool()
    def delete_entities(
        user_id: Annotated[str | None, Field(description="User scope.")] = None,
        agent_id: Annotated[str | None, Field(description="Agent scope.")] = None,
        run_id: Annotated[str | None, Field(description="Run scope.")] = None,
    ) -> str:
        """Delete an entity and cascade-delete its memories."""
        _t0 = _log_call("delete_entities", user_id=user_id, agent_id=agent_id, run_id=run_id)
        try:
            if not any([user_id, agent_id, run_id]):
                result = json.dumps({"error": "At least one scope required."}, ensure_ascii=False)
                _log_done("delete_entities", _t0, result="<error>")
                return result
            filters: dict[str, Any] = {}
            if user_id:
                filters["user_id"] = user_id
            if agent_id:
                filters["agent_id"] = agent_id
            if run_id:
                filters["run_id"] = run_id
            mem = _ensure_memory()
            if mem is None:
                result = json.dumps({"error": "Memory not initialized"}, ensure_ascii=False)
                _log_done("delete_entities", _t0, result="<error>")
                return result
            def _do_delete_entity():
                logger.info("[CALL] safe_bulk_delete(filters=%s) START", filters)
                _t = time.perf_counter()
                count = safe_bulk_delete(mem, filters, graph_enabled=_enable_graph_default)
                logger.info("[CALL] safe_bulk_delete() OK in %.2fs deleted=%d",
                            time.perf_counter() - _t, count)
                return {"message": f"Entity deleted. Removed {count} memories.", "count": count}
            result = _mem0_call(_do_delete_entity)
            _log_done("delete_entities", _t0, result=result)
            return result
        except Exception as exc:
            _log_fail("delete_entities", _t0, exc)
            raise

    @mcp.tool()
    def mcp_search_graph(query: Annotated[str, Field(description="Entity name.")]) -> str:
        """Search entities in Neo4j knowledge graph."""
        _t0 = _log_call("mcp_search_graph", query=query)
        try:
            from mem0_mcp_selfhosted.graph_tools import search_graph
            result = search_graph(query)
            _log_done("mcp_search_graph", _t0, result=result)
            return result
        except Exception as exc:
            _log_fail("mcp_search_graph", _t0, exc)
            raise

    @mcp.tool()
    def mcp_get_entity(name: Annotated[str, Field(description="Entity name.")]) -> str:
        """Get all relationships for a specific entity."""
        _t0 = _log_call("mcp_get_entity", name=name)
        try:
            from mem0_mcp_selfhosted.graph_tools import get_entity
            result = get_entity(name)
            _log_done("mcp_get_entity", _t0, result=result)
            return result
        except Exception as exc:
            _log_fail("mcp_get_entity", _t0, exc)
            raise


def _register_prompts(mcp: FastMCP) -> None:
    @mcp.prompt()
    def memory_assistant() -> str:
        """Quick-start guide."""
        return (
            "You are using the mem0 MCP server for long-term memory management.\n"
            "Quick Start: add_memory to save, search_memories to find, get_memories to list.\n"
        )


def run_server() -> None:
    """Entry point: create server and run.

    [CUSTOM-DEBUG] Logging strategy: file handler gets INFO+, stderr handler only
    WARNING+. This prevents the MCP stderr pipe (read by Claude Code) from filling
    up under heavy INFO logging — a fill would block the next logger.info call
    and hang the server.
    """
    log_level = env("MEM0_LOG_LEVEL", "INFO").upper()
    log_format = "%(asctime)s %(levelname)s %(name)s | %(message)s"
    level_int = getattr(logging, log_level, logging.INFO)

    # Reset root logger handlers to take full control
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
    root.setLevel(level_int)

    formatter = logging.Formatter(log_format)

    # stderr — WARNING+ only, never INFO, to avoid pipe buffer fill blocking
    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setLevel(logging.WARNING)
    stderr_handler.setFormatter(formatter)
    root.addHandler(stderr_handler)

    # File — everything at INFO+
    log_file = env("MEM0_LOG_FILE", "")
    if log_file:
        try:
            file_handler = logging.FileHandler(log_file, encoding="utf-8")
            file_handler.setFormatter(formatter)
            file_handler.setLevel(level_int)
            root.addHandler(file_handler)
            logger.info("[CUSTOM-DEBUG] Timing logs ghi vao file: %s", log_file)
        except Exception as exc:
            logger.warning("[CUSTOM-DEBUG] Khong mo duoc MEM0_LOG_FILE %r: %s", log_file, exc)
    else:
        logger.warning(
            "[CUSTOM-DEBUG] MEM0_LOG_FILE not set — INFO logs sent to stderr (may fill pipe)"
        )

    logger.info("[CUSTOM-DEBUG] Server starting (pid=%d, log_level=%s)", os.getpid(), log_level)

    load_dotenv()

    server = _create_server()

    # [CUSTOM-DEBUG] Prewarm: gọi _ensure_memory() trong background thread NGAY
    # khi server start. mem0ai import tốn 60-300s trên máy có antivirus công ty;
    # nếu chờ đến tool call đầu thì VS Code thấy server treo và respawn vô tận.
    # Background thread giúp main thread vẫn handshake MCP nhanh, trong khi import
    # chạy ở thread khác. Khi tool call đến: nếu prewarm xong → trả về ngay;
    # nếu chưa → chờ qua _memory_init_lock (tự nhiên, không deadlock).
    def _prewarm():
        try:
            logger.info("[ACTION] Prewarm: starting background _ensure_memory()...")
            _t = time.perf_counter()
            _ensure_memory()
            logger.info(
                "[ACTION] Prewarm: DONE in %.2fs — first tool call now fast",
                time.perf_counter() - _t,
            )
        except Exception as exc:
            logger.error("[ACTION] Prewarm FAILED: %s", exc, exc_info=True)

    prewarm_thread = threading.Thread(target=_prewarm, daemon=True, name="mem0-prewarm")
    prewarm_thread.start()
    logger.info("[CUSTOM-DEBUG] Prewarm thread spawned (daemon=True)")

    transport = env("MEM0_TRANSPORT", "stdio").lower()
    logger.info("[CUSTOM-DEBUG] Transport=%s — calling server.run()", transport)

    if transport == "sse":
        server.run(transport="sse")
    elif transport == "streamable-http":
        server.run(transport="streamable-http")
    else:
        server.run(transport="stdio")
