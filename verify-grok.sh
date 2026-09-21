#!/usr/bin/env bash
# verify-grok.sh - prove the xAI/Grok setup works, without ever printing the key.
#
#   bash <(tr -d '\r' < /mnt/c/path/to/agentmux/verify-grok.sh)
#
# Checks, in order of how early they fail:
#   1. env file exists and is mode 0600
#   2. key is present and has a plausible shape
#   3. codex config loads and the xai provider + grok profile are wired
#   4. xAI /v1/responses answers with the configured model  (live API call)
#   5. codex itself can reach it through the grok profile     (live, via agentmux)

set -uo pipefail
ENVFILE="$HOME/.agentmux/env"
MODEL="$(grep -oP '(?<=^model = ")[^"]+' "$HOME/.codex/grok.config.toml" 2>/dev/null)"
: "${MODEL:=grok-4.6}"
pass() { printf '  PASS  %s\n' "$*"; }
fail() { printf '  FAIL  %s\n' "$*"; FAILED=1; }
FAILED=0

echo "1. env file"
if [ ! -f "$ENVFILE" ]; then
  fail "$ENVFILE does not exist - key not set yet"
  exit 1
fi
mode="$(stat -c '%a' "$ENVFILE")"
case "$mode" in
  600|400) pass "mode $mode" ;;
  *) fail "mode $mode - must be 600. The harness will refuse to load it. Run: chmod 600 '$ENVFILE'" ;;
esac

echo "2. key present"
# shellcheck disable=SC1090
set -a; . "$ENVFILE"; set +a
if [ -z "${XAI_API_KEY:-}" ]; then
  fail "XAI_API_KEY is empty or not set in $ENVFILE"
  exit 1
fi
# Length and prefix only - never the value.
pass "XAI_API_KEY set (${#XAI_API_KEY} chars, starts '${XAI_API_KEY:0:4}...')"

echo "3. codex config"
export PATH="$(ls -d "$HOME"/.nvm/versions/node/*/bin 2>/dev/null | sort -V | tail -1):$PATH"
export COLUMNS=200 LINES=50
if codex doctor 2>&1 | grep -q '✓ config'; then pass "config loads"; else fail "codex config does not load"; fi
grep -q 'model_providers.xai' "$HOME/.codex/config.toml" && pass "xai provider block present" || fail "no [model_providers.xai]"
grep -q 'wire_api = "responses"' "$HOME/.codex/config.toml" && pass 'wire_api = "responses"' || fail 'wire_api must be "responses"'
pass "profile model = $MODEL"

echo "4. live xAI /v1/responses call"
body="$(printf '{"model":"%s","input":"Reply with exactly: GROK_OK","max_output_tokens":2000}' "$MODEL")"
resp="$(curl -sS --max-time 60 https://api.x.ai/v1/responses \
  -H "Authorization: Bearer $XAI_API_KEY" \
  -H "Content-Type: application/json" \
  -d "$body" 2>&1)"
if printf '%s' "$resp" | grep -q 'GROK_OK'; then
  pass "API answered with GROK_OK"
elif printf '%s' "$resp" | grep -qi 'invalid.*api.*key\|unauthor\|401'; then
  fail "API rejected the key (401/unauthorised). Re-check the key value."
elif printf '%s' "$resp" | grep -qi 'model.*not.*found\|does not exist\|invalid model'; then
  fail "model '$MODEL' rejected by xAI. Check docs.x.ai/docs/models and edit ~/.codex/grok.config.toml"
else
  fail "unexpected response (first 300 chars, key never echoed):"
  printf '        %s\n' "$(printf '%s' "$resp" | head -c 300 | tr -d '\n')"
fi

echo "5. codex --profile grok  (KNOWN BROKEN - not a key problem)"
cat <<'NOTE'
      SKIPPED. Measured 2026-09-18: codex 0.155.0 always sends a built-in
      tool of type "namespace", and xAI's Responses API rejects it:

        tools[8].type: unknown variant `namespace`, expected one of
        `function`, `web_search`, `x_search`, `image_generation`,
        `collections_search`, `file_search`, `code_execution`,
        `code_interpreter`, `mcp`, `shell`, `tool_search`

      Independent of authentication - it reproduces with a fake token. No
      config option removes it: under [tools] only `web_search` is
      toggleable, and `[features] tool_search = false` does not help.
      So a valid XAI_API_KEY will NOT make `codex --profile grok` work.

      To actually USE Grok, prefer xAI's own CLI (browser login, no key):
        curl -fsSL https://x.ai/cli/install.sh | bash
      or call the API directly, as step 4 above does.
NOTE

echo
if [ "$FAILED" = 0 ]; then
  echo "KEY VERIFIED AND USED: xAI answered a live /v1/responses call."
  echo "The codex route is separately blocked - see step 5."
else
  echo "Some checks failed; fix those first."
fi
exit "$FAILED"
