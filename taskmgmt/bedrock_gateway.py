"""OpenAI **Responses API** -> AWS Bedrock **Chat Completions** gateway. Stdlib only.

    python3 taskmgmt/bedrock_gateway.py [--port 4000] [--region us-west-2]
                                        [--log /tmp/gw.jsonl] [--verbose]

WHY THIS EXISTS
---------------
codex 0.155.0 speaks only the OpenAI Responses API: it rejects
`wire_api = "chat"` outright ("no longer supported. set wire_api = "responses"").

Bedrock offers an OpenAI-COMPATIBLE endpoint, but it is Chat Completions:

    POST /openai/v1/chat/completions   -> 200, works
    POST /openai/v1/responses          -> 404 "model doesn't support this API"

Both verified against a live key in us-west-2. So the two ends are one API generation
apart and something has to translate. That is this file.

AUTH
----
A Bedrock API key is a bearer token, so no SigV4 signing is needed - just
`Authorization: Bearer <key>`. The key is read from the environment
(AWS_BEARER_TOKEN_BEDROCK) and never logged, never echoed, and never placed in argv.

SECURITY POSTURE
----------------
  - Binds 127.0.0.1 only. A gateway holding a cloud credential must not listen on a
    routable address; that is a confused deputy waiting for a request.
  - Requires no client credential, BECAUSE it is loopback-only and single-user. codex
    still sends its env_key, which is accepted and ignored.
  - Request bodies are capped. The log, when enabled, records the request SHAPE and
    omits the Authorization header.

PROVENANCE - READ THIS BEFORE "TIDYING UP"
------------------------------------------
This file was **reconstructed on 2026-09-22**. The original was written on 2026-09-19
and then lost: neither it nor its test suite was ever committed, and both were most
likely deleted alongside the two Bedrock setup scripts during the 2026-09-20 credential
purge - scripts that existed to copy a key out of another tool's settings file and
deserved deleting. This one holds no credential; it reads one from the environment.

What survived was the compiled bytecode, which still loaded on CPython 3.12. This
source was rebuilt from it: every docstring here is the original's, verbatim; the wire
format, constants, control flow and error handling were read out of the bytecode; and
the result was then checked **differentially against the original module**, function by
function, on identical inputs. See dashboard/test_gateway.py, which runs both and
compares, and taskmgmt/recovered/ for the preserved bytecode.

So the odd-looking details here are deliberate reproductions, not fresh choices:
the tool-namespace recursion depth of 3, the `call_0` fallback id, the 800- and
300-character truncations on upstream errors, the hold-back arithmetic in
ReasoningFilter. Changing one changes behaviour that was verified against live Bedrock.
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MAX_BODY = 8 * 1024 * 1024
UPSTREAM_TIMEOUT = 600

STATE = {"region": "us-west-2", "log": None, "verbose": False, "model_default": None}

REASONING_OPEN = "<reasoning>"
REASONING_CLOSE = "</reasoning>"


def log_event(kind, payload):
    """Append one JSON line. Never called with a credential in `payload`."""
    path = STATE["log"]
    if not path:
        return
    try:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(
                {"at": time.time(), "kind": kind, "payload": payload})[:200000] + "\n")
    except OSError:
        pass


def say(*args):
    if STATE["verbose"]:
        print(*args, file=sys.stderr, flush=True)


# ── request translation ──────────────────────────────────────────────────────

def text_from_content(content):
    """Flatten a Responses content array into plain text."""
    if isinstance(content, str):
        return content
    parts = []
    for part in content or []:
        if isinstance(part, str):
            parts.append(part)
        elif isinstance(part, dict):
            parts.append(part.get("text") or part.get("refusal") or "")
    return "".join(parts)


def to_chat_messages(body):
    """Build Chat Completions `messages` from a Responses request.

    Handles the item kinds codex actually emits: plain strings, `message`,
    `function_call`, and `function_call_output`. Anything unrecognised is skipped
    rather than guessed at, and logged so the gap is visible instead of silent.
    """
    messages = []
    instructions = body.get("instructions")
    if isinstance(instructions, str) and instructions.strip():
        messages.append({"role": "system", "content": instructions})

    items = body.get("input")
    if isinstance(items, str):
        items = [items] if items else []
    if not isinstance(items, list):
        # A number or an object here is malformed input, not something to iterate:
        # iterating a dict yields its keys and would invent messages out of them.
        items = []
    for item in items:
        # A string item is passed through as-is, including an empty one. Filtering
        # blanks here looks tidy and is wrong: codex's turn structure is positional,
        # so dropping an item silently shifts everything after it.
        if isinstance(item, str):
            messages.append({"role": "user", "content": item})
            continue
        if not isinstance(item, dict):
            continue
        kind = item.get("type")
        if kind == "message":
            # An empty message is dropped rather than sent: Bedrock rejects a
            # content-less message outright, which would fail the whole request.
            text = text_from_content(item.get("content"))
            if text:
                messages.append({"role": item.get("role") or "user",
                                 "content": text})
        elif kind == "function_call":
            messages.append({
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": item.get("call_id") or item.get("id") or "call_0",
                    "type": "function",
                    "function": {"name": item.get("name") or "",
                                 "arguments": item.get("arguments") or "{}"},
                }],
            })
        elif kind == "function_call_output":
            messages.append({"role": "tool",
                             "tool_call_id": item.get("call_id") or "call_0",
                             "content": item.get("output") or ""})
        elif kind in ("reasoning", "item_reference"):
            # codex round-trips its own reasoning items; Chat Completions has no
            # slot for them and they carry nothing the model needs restated.
            continue
        else:
            log_event("unhandled_input_item",
                      {"type": kind, "keys": sorted(item.keys())})
    return messages


def to_chat_tools(body):
    """Responses tools -> Chat Completions tools.

    Two shape differences and one structural one:

      Responses function: {type:"function", name, description, parameters}
      Chat function:      {type:"function", function:{name, description, parameters}}

    STRUCTURAL: codex groups related tools under a `namespace` item -
    {type:"namespace", name:"multi_agent_v1", description, tools:[ ...functions... ]} -
    which Chat Completions has no concept of. Dropping those groups is what an earlier
    version did, and it silently left the agent with NO tools at all: it could talk but
    not read a file or run a command. They are flattened instead, keeping each inner
    name exactly as codex declared it, because codex matches the tool call it gets back
    by that name.

    `web_search` and other server-hosted tool types genuinely have no equivalent and are
    dropped - but logged, so the gap is visible rather than silent.
    """
    out = []
    seen = set()

    def add(spec):
        if not isinstance(spec, dict):
            return
        name = spec.get("name") or ""
        if not name or name in seen:
            log_event("duplicate_tool", {"name": name})
            return
        seen.add(name)
        out.append({"type": "function", "function": {
            "name": name,
            "description": spec.get("description") or "",
            "parameters": spec.get("parameters") or {"type": "object", "properties": {}},
        }})

    def walk(items, depth):
        for tool in items or []:
            if not isinstance(tool, dict):
                continue
            kind = tool.get("type")
            if kind == "function":
                add(tool)
            elif kind == "namespace" and depth < 3:
                # Bounded rather than unbounded: a cyclic or absurdly nested tool
                # manifest must not take the gateway down with a recursion error.
                walk(tool.get("tools"), depth + 1)
            else:
                log_event("unsupported_tool", {"type": kind, "name": tool.get("name")})

    walk(body.get("tools"), 0)
    return out


class ReasoningFilter:
    """Remove <reasoning> spans from a stream of text fragments.

    NEVER LOSES OUTPUT. Two ways the first version did, both found by running every
    model end to end rather than by reading the code:

      1. It always held back 10 characters in case a `<reasoning` open tag was split
         across deltas. A short reply - "MODEL OK" is 8 characters - was therefore held
         back in its entirety and, because the caller only emitted the flush when a
         delta had already been sent, never appeared at all. Streaming produced zero
         deltas while the non-streaming path was fine.
      2. An unclosed `<reasoning>` discarded everything after it. gpt-oss-20b does
         exactly that, so its answers came back empty. Losing the answer is far worse
         than showing the model's working, so an unterminated span is now treated as a
         malformed tag and released instead of swallowed.
    """

    def __init__(self):
        self.inside = False
        self.pending = ""
        self.swallowed = []

    def feed(self, chunk):
        self.pending += chunk
        out = []
        while self.pending:
            if self.inside:
                index = self.pending.find(REASONING_CLOSE)
                if index < 0:
                    # Hold back only enough to catch a closing tag split across
                    # deltas; everything before that is certainly inside the span.
                    hold = len(REASONING_CLOSE) - 1
                    if len(self.pending) > hold:
                        self.swallowed.append(self.pending[:-hold])
                        self.pending = self.pending[-hold:]
                    break
                self.swallowed.append(self.pending[:index])
                self.pending = self.pending[index + len(REASONING_CLOSE):]
                self.inside = False
                self.swallowed.clear()
                continue
            index = self.pending.find(REASONING_OPEN)
            if index < 0:
                hold = len(REASONING_OPEN) - 1
                if len(self.pending) > hold:
                    out.append(self.pending[:-hold])
                    self.pending = self.pending[-hold:]
                break
            out.append(self.pending[:index])
            self.pending = self.pending[index + len(REASONING_OPEN):]
            self.inside = True
        return "".join(out)

    def flush(self):
        """Everything still held once upstream is done. Emits, never discards."""
        text = self.pending
        if self.inside:
            # Unterminated span: release it rather than lose the answer inside it.
            text = "".join(self.swallowed) + text
        self.pending = ""
        self.swallowed = []
        self.inside = False
        return text


def build_chat_request(body):
    chat = {
        "model": body.get("model") or STATE["model_default"],
        "messages": to_chat_messages(body),
    }
    tools = to_chat_tools(body)
    if tools:
        chat["tools"] = tools
        choice = body.get("tool_choice")
        if choice in ("auto", "none", "required"):
            chat["tool_choice"] = choice
    for source, target in (("max_output_tokens", "max_completion_tokens"),
                           ("temperature", "temperature"),
                           ("top_p", "top_p")):
        if body.get(source) is not None:
            chat[target] = body[source]
    if body.get("stream"):
        chat["stream"] = True
        # Without this Bedrock omits usage from the streamed response entirely.
        chat["stream_options"] = {"include_usage": True}
    return chat


def make_response_object(response_id, model, text, tool_calls, usage, status):
    """The Responses object codex reads back."""
    output = []
    if text:
        output.append({
            "type": "message",
            "id": response_id + "-msg",
            "role": "assistant",
            "status": "completed",
            "content": [{"type": "output_text", "text": text, "annotations": []}],
        })
    for index, call in enumerate(tool_calls or []):
        function = call.get("function") or {}
        output.append({
            "type": "function_call",
            "id": response_id + "-fc" + str(index),
            "call_id": call.get("id") or "call_" + str(index),
            "name": function.get("name") or "",
            "arguments": function.get("arguments") or "{}",
            "status": "completed",
        })
    usage = usage or {}
    prompt = usage.get("prompt_tokens") or 0
    completion = usage.get("completion_tokens") or 0
    return {
        "id": response_id,
        "object": "response",
        "created_at": int(time.time()),
        "status": status,
        "model": model,
        "output": output,
        "usage": {"input_tokens": prompt, "output_tokens": completion,
                  "total_tokens": prompt + completion},
        "parallel_tool_calls": True,
        "tool_choice": "auto",
        "tools": [],
    }


# ── upstream ─────────────────────────────────────────────────────────────────

def bedrock_url():
    return ("https://bedrock-runtime." + STATE["region"]
            + ".amazonaws.com/openai/v1/chat/completions")


def call_bedrock(chat_body, stream):
    key = os.environ.get("AWS_BEARER_TOKEN_BEDROCK", "")
    if not key:
        raise RuntimeError("AWS_BEARER_TOKEN_BEDROCK is not set in this process")
    request = urllib.request.Request(
        bedrock_url(),
        method="POST",
        data=json.dumps(chat_body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + key,
            "Accept": "text/event-stream" if stream else "application/json",
        },
    )
    return urllib.request.urlopen(request, timeout=UPSTREAM_TIMEOUT)


class Gateway(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "agentmux-bedrock-gateway"

    def log_message(self, fmt, *args):
        say("http:", fmt % args)

    def send_json(self, code, obj):
        raw = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        try:
            self.wfile.write(raw)
        except OSError:
            pass

    def read_body(self):
        length = self.headers.get("Content-Length")
        if not length or not length.isdigit():
            return None
        size = int(length)
        if size > MAX_BODY:
            return None
        return self.rfile.read(size)

    def sse(self, event, data):
        self.wfile.write(("event: " + event + "\ndata: "
                          + json.dumps(data) + "\n\n").encode("utf-8"))
        self.wfile.flush()

    def do_GET(self):
        path = self.path.rstrip("/") or "/"
        if path in ("/health", "/v1/health"):
            self.send_json(200, {
                "ok": True,
                "region": STATE["region"],
                "upstream": bedrock_url(),
                "key_present": bool(os.environ.get("AWS_BEARER_TOKEN_BEDROCK")),
            })
            return
        if path == "/v1/models":
            self.send_json(200, {"object": "list", "data": [
                {"id": name, "object": "model", "owned_by": "bedrock"}
                for name in ("openai.gpt-oss-120b-1:0", "openai.gpt-oss-20b-1:0",
                             "openai.gpt-5.6-sol", "openai.gpt-6-astra")]})
            return
        self.send_json(404, {"error": {"message": "not found"}})

    def do_POST(self):
        path = self.path.split("?", 1)[0].rstrip("/") or "/"
        if path not in ("/v1/responses", "/responses"):
            self.send_json(404, {"error": {"message": "unsupported path " + self.path}})
            return
        raw = self.read_body()
        if raw is None:
            self.send_json(413, {"error": {"message": "missing or oversized body"}})
            return
        try:
            body = json.loads(raw)
        except ValueError as err:
            self.send_json(400, {"error": {"message": "invalid JSON: " + str(err)}})
            return

        # SHAPE only - never the content, and never a header.
        log_event("responses_request", {
            "model": body.get("model"),
            "stream": bool(body.get("stream")),
            "keys": sorted(body.keys())[:40],
            "tool_count": len(body.get("tools") or []),
            "input_kinds": sorted({
                item.get("type") if isinstance(item, dict) else "str"
                for item in (body.get("input") or [])})[:40],
        })

        chat = build_chat_request(body)
        stream = bool(body.get("stream"))
        say("-> bedrock", chat["model"],
            "msgs=" + str(len(chat["messages"])),
            "tools=" + str(len(chat.get("tools") or [])),
            "stream=" + str(stream))

        try:
            upstream = call_bedrock(chat, stream)
        except urllib.error.HTTPError as err:
            detail = err.read().decode("utf-8", "replace")[:800]
            log_event("upstream_http_error", {"code": err.code, "detail": detail})
            self.send_json(502, {"error": {
                "message": "bedrock " + str(err.code) + ": " + detail}})
            return
        except (urllib.error.URLError, RuntimeError, OSError) as err:
            log_event("upstream_error", {"detail": str(err)[:300]})
            self.send_json(502, {"error": {
                "message": "bedrock unreachable: " + str(err)}})
            return

        if stream:
            self.relay_stream(upstream, chat["model"])
        else:
            self.relay_once(upstream, chat["model"])

    def relay_once(self, upstream, model):
        try:
            data = json.loads(upstream.read())
        except ValueError as err:
            self.send_json(502, {"error": {"message": "bad upstream JSON: " + str(err)}})
            return
        choices = data.get("choices") or [{}]
        message = choices[0].get("message") or {}
        reasoning = ReasoningFilter()
        text = reasoning.feed(message.get("content") or "") + reasoning.flush()
        self.send_json(200, make_response_object(
            data.get("id") or "resp_gw", model, text,
            message.get("tool_calls"), data.get("usage"), "completed"))

    def relay_stream(self, upstream, model):
        """Translate an upstream Chat Completions SSE stream into Responses events.

        codex reads the deltas to render live output and `response.completed` to finish
        the turn, so the terminating event matters as much as the text.
        """
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.close_connection = True
        self.end_headers()

        response_id = "resp_gw_" + str(int(time.time() * 1000))
        item_id = response_id + "-msg"
        reasoning = ReasoningFilter()
        started = False
        pieces = []
        calls = {}
        usage = None

        self.sse("response.created", {
            "type": "response.created",
            "response": make_response_object(response_id, model, "", [], None,
                                             "in_progress")})

        def emit(text):
            nonlocal started
            if not text:
                return
            if not started:
                self.sse("response.output_item.added", {
                    "type": "response.output_item.added",
                    "output_index": 0,
                    "item": {"type": "message", "id": item_id, "role": "assistant",
                             "status": "in_progress", "content": []}})
                started = True
            pieces.append(text)
            self.sse("response.output_text.delta", {
                "type": "response.output_text.delta",
                "item_id": item_id, "output_index": 0, "content_index": 0,
                "delta": text})

        try:
            for raw in upstream:
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if payload == "[DONE]":
                    break
                try:
                    chunk = json.loads(payload)
                except ValueError:
                    continue
                if chunk.get("usage"):
                    usage = chunk["usage"]
                choices = chunk.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta") or {}
                if delta.get("content"):
                    emit(reasoning.feed(delta["content"]))
                for call in delta.get("tool_calls") or []:
                    index = call.get("index") or 0
                    slot = calls.setdefault(index, {"id": None, "name": "",
                                                    "arguments": ""})
                    if call.get("id"):
                        slot["id"] = call["id"]
                    function = call.get("function") or {}
                    if function.get("name"):
                        slot["name"] = function["name"]
                    if function.get("arguments"):
                        # Arguments arrive as a JSON string in fragments.
                        slot["arguments"] += function["arguments"]

            emit(reasoning.flush())
            text = "".join(pieces)

            if started:
                self.sse("response.output_text.done", {
                    "type": "response.output_text.done",
                    "item_id": item_id, "output_index": 0, "content_index": 0,
                    "text": text})
                self.sse("response.output_item.done", {
                    "type": "response.output_item.done",
                    "output_index": 0,
                    "item": {"type": "message", "id": item_id, "role": "assistant",
                             "status": "completed",
                             "content": [{"type": "output_text", "text": text,
                                          "annotations": []}]}})

            tool_calls = []
            for offset, index in enumerate(sorted(calls)):
                slot = calls[index]
                call_id = slot["id"] or "call_" + str(offset)
                # Raw, NOT defaulted to "{}" here. The streamed item events carry
                # exactly what arrived; only the final response object substitutes a
                # default, via make_response_object.
                arguments = slot["arguments"]
                tool_calls.append({
                    "id": call_id,
                    "type": "function",
                    "function": {"name": slot["name"], "arguments": arguments},
                })
                # output_index is offset + 1 even when no message was produced:
                # index 0 belongs to the assistant message whether or not one exists,
                # so a tool call never takes it.
                item = {"type": "function_call",
                        "id": response_id + "-fc" + str(offset),
                        "call_id": call_id,
                        "name": slot["name"],
                        "arguments": arguments,
                        "status": "in_progress"}
                self.sse("response.output_item.added", {
                    "type": "response.output_item.added",
                    "output_index": offset + 1,
                    "item": item})
                self.sse("response.output_item.done", {
                    "type": "response.output_item.done",
                    "output_index": offset + 1,
                    "item": dict(item, status="completed")})

            final = make_response_object(response_id, model, text, tool_calls, usage,
                                         "completed")
            self.sse("response.completed", {"type": "response.completed",
                                            "response": final})
            log_event("stream_done", {"chars": len(text),
                                      "tool_calls": len(tool_calls),
                                      "usage": usage})
        except (BrokenPipeError, ConnectionResetError):
            log_event("client_disconnected", {})
        except (Exception, OSError) as err:  # noqa: B014 - mirrors the original
            log_event("stream_error", {"detail": str(err)[:300]})
            try:
                self.sse("response.failed", {
                    "type": "response.failed",
                    "response": make_response_object(response_id, model, "", [], usage,
                                                     "failed"),
                    "error": {"message": str(err)[:300]}})
            except OSError:
                pass


def main():
    parser = argparse.ArgumentParser(
        description="Responses API -> Bedrock Chat gateway.")
    parser.add_argument("--port", type=int, default=4000)
    parser.add_argument("--region", default=os.environ.get("AWS_REGION", "us-west-2"))
    parser.add_argument("--model", default="openai.gpt-oss-120b-1:0",
                        help="fallback when a request names no model")
    parser.add_argument("--log", help="append request/response SHAPES as JSON lines")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    STATE.update(region=args.region, log=args.log, verbose=args.verbose,
                 model_default=args.model)

    if not os.environ.get("AWS_BEARER_TOKEN_BEDROCK"):
        print("warning: AWS_BEARER_TOKEN_BEDROCK is not set; requests will fail "
              "with 502", file=sys.stderr)

    # 127.0.0.1 and nothing else. See SECURITY POSTURE above.
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Gateway)
    server.daemon_threads = True
    print("bedrock gateway on http://127.0.0.1:" + str(args.port) + "/v1  ->  "
          + bedrock_url(), file=sys.stderr, flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
