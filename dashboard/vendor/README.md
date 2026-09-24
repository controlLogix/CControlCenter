# dashboard/vendor

Third-party code, committed rather than installed.

The dashboard is meant to run from a clone with nothing but a Python 3 interpreter
and a browser: no `pip install`, no virtualenv, no network at start-up. The machines
it runs on are plant-side boxes where `sudo apt install` is somebody else's change
request and outbound PyPI is often blocked outright. So anything it depends on that
is not in the standard library lives here, at a pinned version, the same way
`xterm.js` does.

| Path | Version | Licence | Why |
| --- | --- | --- | --- |
| `xterm.js`, `addon-fit.js`, `xterm.css` | see file headers | MIT | terminal rendering |
| `paho/` | paho-mqtt 2.1.0 | EPL-2.0 OR BSD-3-Clause | the MQTT client |

## paho-mqtt

Extracted from the official pure-Python wheel:

    https://files.pythonhosted.org/packages/c4/cb/00451c3cf31790287768bb12c6bec834f5d292eaf3022afc88e14b8afc94/paho_mqtt-2.1.0-py3-none-any.whl
    sha256 6db9ba9b34ed5bc6b6e3812718c7e06e2fd7444540df2455d2c51bd58808feee

`py3-none-any`: no compiled extensions, so the same files work on every platform the
dashboard runs on. Only the `paho/` package and its `LICENSE.txt` were kept; the
`.dist-info` metadata was not, because nothing here resolves it as an installed
distribution — `mqtt_monitor.py` puts this directory on `sys.path` and imports it.

### Why it replaced the hand-written client

`dashboard/mqtt.py` still exists and still speaks enough MQTT 3.1.1 for the bounded
publish/subscribe endpoints. It was never adequate for a *monitor*, and a real
broker proved it: a zigbee2mqtt bridge publishes a 217 KB retained message on
`zigbee2mqtt/bridge/definitions`, which blew through that client's 64 KB packet cap.
The session died, reconnected, hit the same retained message on re-subscribe, and
died again — an unbreakable loop, against a perfectly ordinary broker.

Raising the cap would only have moved the number. The real list of things a monitor
needs and a weekend implementation does not have is long: arbitrary packet sizes,
TLS, username/password, MQTT 5, QoS 1/2 flows, topic-alias handling, keepalive and
backoff that have been tested against more than one broker. Paho is the Eclipse
reference implementation, it is the fastest of the Python clients in published
benchmarks, and it has all of that.

### Upgrading

Download the new `py3-none-any` wheel, check its sha256 against PyPI, extract only
`paho/`, keep `LICENSE.txt`, and update the version and hash in this file.
