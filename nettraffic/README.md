# nettraffic

Python 3.12 standard library only. No installation or external packages required.
Run from the repository root:

```sh
python3 nettraffic/analyze.py nettraffic/fixtures/sample.pcap -o traffic.png
python3 -m unittest discover -s nettraffic -v
python3 nettraffic/make_fixture.py
```

The CLI prints the detected byte order and raw magic bytes, packet count, and
advertised PNG dimensions (1000 x 900). It returns 1 and a concise error on
malformed captures or I/O failures, without a traceback. The module entry point
also works: `python3 -m nettraffic.analyze CAPTURE -o OUTPUT`.

The PNG contains protocol packet counts, protocol byte counts, the top five
source talkers by bytes, and a timeline. Bars carry exact values and zero/maximum
axis labels. Bytes mean **original Ethernet frame lengths** (`orig_len`), including
any captured Ethernet padding; they are not IP payload bytes. Source talkers mean
source IP addresses for recognized IP headers and source MAC addresses otherwise.
Short headers are labelled SHORT, rather than silently discarded. IP protocol
classification uses IPv4's protocol field or IPv6's immediate next-header field;
IPv6 extension chains are grouped under IPV6-OTHER, not traversed. VLAN tags are
supported. This is a traffic summary, not full packet validation or reassembly.

Timeline bins start at the earliest integer Unix second (shown in the image).
Captures up to 60 seconds use one-second bins; longer captures use wider bins,
whose duration is printed on the chart. The final bin may extend past the final
packet. Unordered timestamps and empty captures are supported.

The streaming reader supports big- and little-endian classic pcap, with either
microsecond or nanosecond timestamps. It accepts Ethernet linktype 1 only; other
linktypes are rejected with a known name or UNKNOWN and their numeric ID.
Pcapng is unsupported. Per-record lengths are validated against remaining file
bytes, snaplen, orig_len, and a 16 MiB allocation limit before reading payloads.
A second streaming pass builds at most 60 timeline bins, avoiding storage that
scales with capture duration or packet count. Unique source storage has a 10,000
entry safety limit; exceeding it produces an explicit error instead of an
approximate top-talkers result. Analyze a stable capture file, not a live writer.

The committed sample is deterministic: 18 packets over six seconds, six each of
TCP, UDP and ICMP. Their original-frame byte totals are respectively 474, 420 and
430. `make_fixture.py --big-endian OUTPUT` generates its big-endian equivalent.

## Verification and mutation evidence

On Python 3.12.3, all 10 tests pass. Tests exercise both byte orders through the
CLI, reproducibility, protocol classification, malformed/truncated inputs,
oversized declared lengths with a guarded reader, exact summary totals, empty and
long unordered timelines, PNG chunk CRCs, IHDR dimensions, and inflated IDAT
scanlines. The generated PNG was also visually inspected for labels and bars.

A deliberate single-line mutation was performed in `analyze.py`:

```diff
-            counts[0] += 1
+            counts[0] += 2
```

Running `python3 -B -m unittest
nettraffic.test_nettraffic.CaptureTests.test_summary_exact_counts -v` (on one
shell line) failed with exit 1: every protocol reported 12 packets against the
expected 6. The implementation was restored in a `finally` block, its cached
bytecode removed, and the complete suite passed again. This evidence is also in
the agentmux journal for TM-083.
