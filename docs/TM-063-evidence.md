
## Follow-up: bounded persistence

Chose least-recently-touched eviction, documented beside rememberOpen, because
hashing alone would still allow an unbounded number of entries. The shared map
now holds at most 512 boolean choices and 65,536 serialized UTF-16 code units
(about 128 KiB). Updating a key moves it to the newest position; order survives
reload. Old oversized maps are trimmed on the next write. Evicted items use the
view default; individual keys larger than the entire budget cannot be retained.

Re-ran only the targeted suites: test_frontend.sh passed 13, failed 0;
test_frontend_collapse.sh passed 11, failed 0. Added checks for count eviction,
last-touch ordering across reload, large legacy content keys, escaped/non-ASCII
serialized size, oversized individual keys, and successful subsequent writes.
Scoped git diff --check passed. No full gate ran.
