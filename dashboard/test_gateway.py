#!/usr/bin/env python3
"""Verify the Responses-to-Chat-Completions translation in the Bedrock gateway.

    python3 dashboard/test_gateway.py     # no network, no key, no server

NO LIVE BEDROCK CALL IS MADE and no credential is needed. Everything asserted here
is pure translation: request shaping, tool flattening, the reasoning filter and the
response object codex reads back. `call_bedrock` and the HTTP handler are the only
parts that touch the network, and they are not exercised.

WHY THIS FILE LOOKS UNUSUAL
---------------------------
`taskmgmt/bedrock_gateway.py` **does not exist**. Neither did its test suite, which
STATUS_CCC_2026-09-20.md lists as 31 checks. Both are absent from the working tree and
from git history, so neither was ever committed; they were most likely deleted with
the two Bedrock setup scripts during the 2026-09-20 credential purge, which is a
different class of file - those existed to copy a key out of another tool's settings,
these did not.

What survives is `taskmgmt/__pycache__/bedrock_gateway.cpython-312.pyc`, compiled from
a 27,384-byte source on 2026-09-19. Its magic matches CPython 3.12, so the module still
imports and runs. This suite loads the source if it is ever restored and falls back to
that bytecode otherwise, and says which one it used.

Two consequences worth stating plainly:

  - The gateway is one Python upgrade away from being lost outright. A 3.13
    interpreter will refuse that .pyc and there is no source to recompile.
  - These assertions are therefore also a specification. If the source is rewritten
    or decompiled, this suite is the record of what the working version did -
    including the three bugs fixed on 2026-09-20, each of which has a check below so
    a rewrite cannot quietly reintroduce them.
"""

import importlib.machinery
import importlib.util
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SOURCE = REPO / "taskmgmt" / "bedrock_gateway.py"
# The cache entry is the live one, but __pycache__/ and *.py[cod] are both gitignored,
# so it was the ONLY copy of a lost file and untracked - one `git clean -xdf` from
# gone. The preserved copy under recovered/ is the tracked fallback.
CACHED = REPO / "taskmgmt" / "__pycache__" / "bedrock_gateway.cpython-312.pyc"
PRESERVED = REPO / "taskmgmt" / "recovered" / "bedrock_gateway.cpython-312.pyc.bin"
passed = failed = 0


def check(label, expected, actual):
    global passed, failed
    if expected == actual:
        print(f"  ok    {label:<52} {str(actual)[:60]!r}")
        passed += 1
    else:
        print(f"  FAIL  {label:<52} got {actual!r} want {expected!r}")
        failed += 1


def load_gateway():
    """Prefer real source; fall back to the surviving bytecode."""
    if SOURCE.is_file():
        spec = importlib.util.spec_from_file_location("bedrock_gateway", SOURCE)
        origin = f"source ({SOURCE.name})"
    else:
        blob = CACHED if CACHED.is_file() else PRESERVED
        if not blob.is_file():
            print("  FAIL  no gateway found: no source, no cache entry, no preserved copy")
            print("        see taskmgmt/recovered/README.md - this file was the last copy")
            print()
            print("passed 0, failed 1")
            sys.exit(1)
        loader = importlib.machinery.SourcelessFileLoader("bedrock_gateway", str(blob))
        spec = importlib.util.spec_from_file_location("bedrock_gateway", str(blob),
                                                      loader=loader)
        origin = f"BYTECODE ONLY ({blob.name}) - source is missing"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, origin


print("--- loading ---")
gw, origin = load_gateway()
print(f"        loaded from {origin}")
check("module imports", True, hasattr(gw, "to_chat_messages"))
if not SOURCE.is_file():
    print("        NOTE: running against bytecode. A CPython upgrade will break this.")


# ── security posture ─────────────────────────────────────────────────────────
# Asserted against the code object rather than by binding a socket: the point is
# that the literal is in the source, not that one particular run happened to bind
# loopback. A gateway holding a cloud credential must never listen on a routable
# address.

def constants_of(function):
    """Every string constant reachable from a function, nested code included."""
    found = set()
    stack = [function.__code__]
    while stack:
        code = stack.pop()
        for const in code.co_consts:
            if isinstance(const, str):
                found.add(const)
            elif hasattr(const, "co_consts"):
                stack.append(const)
    return found


print("--- security posture ---")
main_constants = constants_of(gw.main)
check("binds loopback only", True, "127.0.0.1" in main_constants)
check("never binds all interfaces", False,
      any(host in main_constants for host in ("0.0.0.0", "::", "")) and "0.0.0.0" in main_constants)
check("request bodies are capped", True, isinstance(gw.MAX_BODY, int) and gw.MAX_BODY > 0)
check("upstream timeout is bounded", True,
      isinstance(gw.UPSTREAM_TIMEOUT, int) and 0 < gw.UPSTREAM_TIMEOUT <= 3600)
check("credential comes from the environment", True,
      any("AWS_BEARER_TOKEN_BEDROCK" in c for c in constants_of(gw.call_bedrock)))
# A literal key would be a 100+ character opaque string sitting in a constant.
suspicious = [c for c in constants_of(gw.call_bedrock) | constants_of(gw.main)
              if len(c) > 80 and " " not in c and "\n" not in c]
check("no long opaque literal in the credential path", [], suspicious)


# ── content flattening ───────────────────────────────────────────────────────

print("--- text_from_content ---")
check("a bare string passes through", "plain", gw.text_from_content("plain"))
check("input_text and output_text concatenate", "ab", gw.text_from_content(
    [{"type": "input_text", "text": "a"}, {"type": "output_text", "text": "b"}]))
check("an unknown part contributes nothing", "", gw.text_from_content([{"type": "weird"}]))
check("empty content is empty text", "", gw.text_from_content([]))


# ── request translation ──────────────────────────────────────────────────────

print("--- to_chat_messages ---")
messages = gw.to_chat_messages({
    "instructions": "be terse",
    "input": [
        "bare string",
        {"type": "message", "role": "user",
         "content": [{"type": "input_text", "text": "hello"}]},
        {"type": "function_call", "name": "read", "arguments": '{"p":1}', "call_id": "c1"},
        {"type": "function_call_output", "call_id": "c1", "output": "365"},
        {"type": "no_such_kind", "x": 1},
    ]})
roles = [m["role"] for m in messages]
check("instructions become the system message", "system", messages[0]["role"])
check("instructions text is carried", "be terse", messages[0]["content"])
check("every item kind is mapped", ["system", "user", "user", "assistant", "tool"], roles)
check("an unrecognised item is skipped, not guessed", 5, len(messages))
check("a bare string becomes a user turn", "bare string", messages[1]["content"])
check("a message item is flattened to text", "hello", messages[2]["content"])

call = messages[3]
check("a function_call becomes an assistant tool_call", None, call["content"])
check("tool_call carries the call id", "c1", call["tool_calls"][0]["id"])
check("tool_call is typed as a function", "function", call["tool_calls"][0]["type"])
check("tool name survives verbatim", "read", call["tool_calls"][0]["function"]["name"])
check("arguments are passed as a string", '{"p":1}',
      call["tool_calls"][0]["function"]["arguments"])
check("function_call_output becomes a tool message", "tool", messages[4]["role"])
check("the tool result is linked by call id", "c1", messages[4]["tool_call_id"])
check("the tool result body is carried", "365", messages[4]["content"])
check("no instructions means no system message", "user",
      gw.to_chat_messages({"input": "hi"})[0]["role"])


# ── tools: the bug that left the agent with none ─────────────────────────────

print("--- to_chat_tools (bug 27: namespace groups must be flattened) ---")
tools = gw.to_chat_tools({"tools": [
    {"type": "function", "name": "shell", "description": "run",
     "parameters": {"type": "object"}},
    {"type": "namespace", "name": "multi_agent_v1", "description": "group", "tools": [
        {"type": "function", "name": "spawn", "description": "s", "parameters": {}},
        {"type": "function", "name": "close", "description": "c", "parameters": {}},
    ]},
    {"type": "web_search"},
]})
names = [t["function"]["name"] for t in tools]
check("a namespace is flattened, not dropped", ["shell", "spawn", "close"], names)
check("inner names are kept verbatim", True, "spawn" in names and "multi_agent_v1" not in names)
check("every tool is nested under 'function'", True,
      all(t["type"] == "function" and "function" in t for t in tools))
check("description survives", "run", tools[0]["function"]["description"])
check("parameters survive", {"type": "object"}, tools[0]["function"]["parameters"])
check("a server-hosted tool is dropped", False, any("web_search" in n for n in names))
check("no tools in means no tools out", [], gw.to_chat_tools({}))
deep = gw.to_chat_tools({"tools": [
    {"type": "namespace", "name": "outer", "tools": [
        {"type": "namespace", "name": "inner", "tools": [
            {"type": "function", "name": "buried", "parameters": {}}]}]}]})
check("a nested namespace is still reached", ["buried"],
      [t["function"]["name"] for t in deep])


# ── the reasoning filter: two bugs that ate the answer ───────────────────────

print("--- ReasoningFilter (bugs 28 and 29: the answer must never be lost) ---")
f = gw.ReasoningFilter()
emitted = f.feed("MODEL OK")
check("a short reply is not emitted early", "", emitted)
check("bug 28: a short reply survives to flush", "MODEL OK", f.flush())

f = gw.ReasoningFilter()
f.feed("<reasoning>thinking out loud</reasoning>")
f.feed("the answer")
check("a closed reasoning span is stripped", "the answer", f.flush())

f = gw.ReasoningFilter()
f.feed("<reasoning>never closed, and the answer is in here")
check("bug 29: an unterminated span is released, not swallowed",
      "never closed, and the answer is in here", f.flush())

f = gw.ReasoningFilter()
f.feed("<reas")
f.feed("oning>x</reasoning>done")
check("a tag split across deltas is still matched", "done", f.flush())

f = gw.ReasoningFilter()
body = "y" * 400
streamed = f.feed(body)
check("long output does emit incrementally", True, len(streamed) > 0)
check("and loses nothing overall", body, streamed + f.flush())

f = gw.ReasoningFilter()
check("plain text with no tags is untouched", "just text", f.feed("just text") + f.flush())


# ── the objects codex reads back ─────────────────────────────────────────────

print("--- build_chat_request ---")
chat = gw.build_chat_request({"model": "openai.gpt-oss-120b-1:0", "input": "hi",
                              "stream": True, "max_output_tokens": 50})
check("model passes through", "openai.gpt-oss-120b-1:0", chat["model"])
check("stream passes through", True, chat["stream"])
check("messages are built", "hi", chat["messages"][-1]["content"])
check("no tools key when none were sent", False, bool(chat.get("tools")))

print("--- make_response_object ---")
obj = gw.make_response_object("resp_1", "m", "hi", [],
                              {"prompt_tokens": 1, "completion_tokens": 2}, "completed")
check("object is a Responses object", "response", obj["object"])
check("id is echoed", "resp_1", obj["id"])
check("status is carried", "completed", obj["status"])
check("text lands in output content", "hi", obj["output"][0]["content"][0]["text"])
check("output is typed for codex", "output_text", obj["output"][0]["content"][0]["type"])
check("prompt tokens map to input_tokens", 1, obj["usage"]["input_tokens"])
check("completion tokens map to output_tokens", 2, obj["usage"]["output_tokens"])
check("totals are summed", 3, obj["usage"]["total_tokens"])

print("--- bedrock_url ---")
gw.STATE["region"] = "us-west-2"
check("url is built from the configured region", True,
      "us-west-2" in gw.bedrock_url())
check("url targets chat completions, not responses", True,
      gw.bedrock_url().endswith("/openai/v1/chat/completions"))
gw.STATE["region"] = "eu-central-1"
check("region is not hardcoded", True, "eu-central-1" in gw.bedrock_url())
gw.STATE["region"] = "us-west-2"

print()
print(f"passed {passed}, failed {failed}")
sys.exit(1 if failed else 0)
