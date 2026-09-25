# field/vendor

Third-party code for the field sidecar, committed rather than installed.

Same rule as `dashboard/vendor`, and for the same reason: the sidecar has to
install from a clone, with no network and no `pip`. It runs on plant-side boxes
where `sudo apt install` is somebody else's change request and outbound PyPI is
often blocked outright.

The rule being protected is **not** "standard library only" — it is "installs
from a clone, offline". Vendoring honours that; so, in this directory, does the
requirement that every package be a pure-Python `py3-none-any` wheel with no
compiled extensions, so one committed copy is correct on every platform the
sidecar runs on.

| Path | Version | Licence | Why |
| --- | --- | --- | --- |
| `pycomm3/` | pycomm3 1.2.16 | MIT | Logix tag browsing, template/UDT member decoding, device discovery |

## pycomm3

Extracted from the official pure-Python wheel:

    https://files.pythonhosted.org/packages/82/60/c31ddd4903be23d4056571d31ccaf4c6d71d9b6a085a3d488236996e0010/pycomm3-1.2.16-py3-none-any.whl
    sha256 88e95c70472154ee32233f76af126526db208830e1e803eb9f621c8bd1d8fcd0

`py3-none-any`, and **no runtime dependencies** — PyPI lists only
`pytest; extra == "tests"`, so nothing is pulled in behind it. That was checked
rather than assumed: a transitive dependency would have meant vendoring its
dependencies too, and the policy would have quietly become a package manager.

Only the `pycomm3/` package was kept. The `.dist-info` metadata was not, because
nothing here resolves it as an installed distribution — `field/` puts this
directory on `sys.path` and imports it, exactly as `mqtt_monitor.py` does with
paho.

`pycomm3-LICENSE.txt` comes from the sdist rather than the wheel, because the
wheel ships no licence file. The sdist was hash-checked too:

    pycomm3-1.2.16.tar.gz
    sha256 dda3bd1713614af9d20089f0920195a8ad7922f42b283fe62cf2d256ad2f52c6

### What it is for

`logix.py` names its own gaps, and pycomm3 closes exactly those:

- *"callers supply an instance ID obtained from the controller"* (`logix.py:6-7`)
  → `LogixDriver.tags`, where each entry carries `instance_id`, `tag_type`,
  `data_type` and `dim`.
- *"template discovery/member layout decoding is not included"* (`logix.py:10-11`)
  → a struct's `data_type` carries `template` and `internal_tags`, giving each
  member's offset, type and bit position.
- *"the caller must supply the handle and element size... not guess a UDT
  layout"* (`logix.py:11-12`) → `read('UDT.Member')` resolves both from the
  cached template.
- *"version 21 or later... callers supply"* → `get_plc_info().revision.major`,
  read once on connect.
- *"No routing through a chassis/backplane"* (`enip.py:4`) → `'10.1.2.3/bp/1'`.

`logix.py` is **not** retired by this. It stays as a second, independent decoder
and is used as a verification oracle: two decoders agreeing about a value is
stronger evidence than either alone.

## MANIFEST.sha256

A hash per vendored file, checked by `dashboard/check_vendor.sh`.

The wheel hashes above are **provenance** — they let anyone re-derive these
files from PyPI. They are deliberately not what the gate verifies, because
verifying them needs the network, and a check that only works where PyPI is
reachable is useless on exactly the boxes this directory exists for. The
manifest is what makes "these bytes are the ones that were reviewed" checkable
offline.

## Upgrading

Download the new `py3-none-any` wheel, check its sha256 against PyPI, confirm
`requires_dist` is still empty of runtime dependencies, extract only the
package, refresh the licence from the sdist, regenerate `MANIFEST.sha256`, and
update the version and both hashes here.
