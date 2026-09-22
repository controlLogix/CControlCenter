# Recovered artifacts

## `bedrock_gateway.cpython-312.pyc.bin`

> **UPDATE 2026-09-22, later the same day: the source has been reconstructed.**
> `taskmgmt/bedrock_gateway.py` exists again, rebuilt from this bytecode and verified
> against it differentially - both implementations run on identical inputs and their
> outputs compared, by `dashboard/test_gateway.py`. This file is therefore no longer the
> last copy of anything, but **keep it**: it is the reference the reconstruction is
> checked against, and that check is the only evidence the rewrite behaves like the
> version that actually worked against live Bedrock. It also proved its worth
> immediately - importing the new source overwrote the `__pycache__` entry, so without
> this copy the act of writing the replacement would have destroyed the original.

This was the **only surviving copy of `taskmgmt/bedrock_gateway.py`**, which no longer
existed. Neither the source nor its test suite was in the working tree or in git history,
so neither was ever committed. Both were most likely deleted alongside
`dashboard/setup_bedrock_codex.sh` and `dashboard/probe_bedrock.sh` during the
2026-09-20 credential purge — those two existed to copy an API key out of another tool's
settings file and deserved deleting; the gateway did not, since it holds no credential
and reads one from the environment.

Compiled from a **27,384-byte** source on **2026-09-19 20:43:47**. Its magic number
matches **CPython 3.12**, so it still imports and every function still runs.

### Why it is here rather than in `__pycache__`

`__pycache__/` and `*.py[cod]` are both in `.gitignore`, so the one remaining copy of a
lost file was **untracked**. A routine cache purge, a `git clean -xdf`, or a Python
version bump that rewrites the cache directory would have destroyed it silently. The
`.bin` suffix keeps it clear of those ignore rules and stops it being mistaken for a
live cache entry that Python might load in place of a real module.

### The deadline that applied, and what was done about it

A CPython 3.13 interpreter will refuse this file, and there was **no source to
recompile** - so the gateway was one routine Python upgrade away from being lost
outright. Three options were on the table: decompile it, rewrite it, or let the Bedrock
path go deliberately rather than by accident.

Decompilation was not available: nothing suitable is installed, and the mature
decompilers (uncompyle6, decompyle3) do not support CPython 3.12 at all. **Option 2 was
taken** while the bytecode still loaded, which is what made the differential check
possible. That window is now closed permanently - the source no longer depends on this
file being loadable, only the verification does.

### What was extracted while it was still reachable

The full module docstring — including the measured endpoint table
(`/openai/v1/chat/completions` 200 versus `/openai/v1/responses` 404) and the security
posture — plus every function docstring, the complete structure, and all constants. The
substance is preserved in `dashboard/test_gateway.py` and in
`STATUS_CCC_2026-09-22.md`.

### Checked before committing

Every string constant and name in the bytecode (300 of them) was screened for credential
material: no key-shaped literals, no bearer tokens, no long opaque strings. The only
match for "long and opaque" was the URL fragment
`.amazonaws.com/openai/v1/chat/completions`. The credential is read from
`AWS_BEARER_TOKEN_BEDROCK` at run time and never appears in the file.

### Running it

`dashboard/test_gateway.py` loads `taskmgmt/bedrock_gateway.py` if it is ever restored,
then the `__pycache__` entry, then this file — and reports which one it used.
