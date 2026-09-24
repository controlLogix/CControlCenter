# Vendor protocol manuals

The PDFs themselves are gitignored. They are freely downloadable from the vendor,
but distributing them from this repository is the vendor's call and not ours, so
this file carries the URLs instead and the documents are fetched on demand.

## Rockwell Automation

**1756-PM020 — Logix 5000 Controllers Data Access** (92 pages)

    curl -sL -o docs/vendor/1756-pm020_-en-p.pdf \
      https://literature.rockwellautomation.com/idc/groups/literature/documents/pm/1756-pm020_-en-p.pdf

The authoritative specification for reading and writing Logix controller tags over
EtherNet/IP. Page 16 lists the five vendor-specific services a Logix 5000 controller
supports — Read Tag `0x4C`, Read Tag Fragmented `0x52`, Write Tag `0x4D`, Write Tag
Fragmented `0x53`, Read Modify Write Tag `0x4E` — and the two addressing methods,
Symbolic Segment and Symbol Instance (version 21 and later).

Worth stating because the two are easily confused: this is the **data access
protocol**, which is open and documented. It is not the **Logix Designer SDK**, which
automates Studio 5000 and is licensed, Windows-only, .NET, and requires Studio 5000
installed. TM-078 implements the former and does not pretend to the latter.
