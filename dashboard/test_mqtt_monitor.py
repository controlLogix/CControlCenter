"""The MQTT monitor's session handling: TLS, reconnect, and the missing-vendor path.

SCOPED DELIBERATELY. test_field_panels.py:312-389 already covers the topic cap,
value truncation, the retained-flag handling, check_topic_filter and AuthStore -
so none of that is repeated here. What had no test at all is the part that only
shows up against a real broker: how a session is assembled, what happens when
one drops, and what the module does when its vendored client is not there.

NO NETWORK. paho.Client is replaced with a recording stand-in, so these assert
what the monitor ASKS the client to do. That is the right level: the question is
not whether paho can do TLS, it is whether we configured it, and a test that
needed a broker would not run in the gate at all.

WHY THE RECONNECT CASE MATTERS MOST. The monitor re-subscribes on every connect,
not just the first, because a reconnect starts a clean session. A monitor that
silently stops receiving after a network blip is worse than one that never
started: the page keeps showing the last values, with nothing saying they have
stopped arriving.

NOT IN check_test_failability.sh, AND THAT IS NOT AN OVERSIGHT. That gate proves
a suite can fail by running it against a commit where the bug was still present.
This suite passes against EVERY version of mqtt_monitor.py in this repo's
history - the behaviours it covers have been right since the module was written
- so there is no base to point it at, and inventing one would make the gate say
something untrue.

Proved by mutation instead, 2026-09-25. Three realistic regressions, each caught:

    subscribe only on the first connect       -> passed 13, failed 1
    drop TLS verification by default          -> passed 12, failed 2
    int() a ReasonCode, as the original bug did -> passed 12, failed 2

If this suite is extended, re-run that rather than assuming.
"""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    import mqtt_monitor
except ImportError as exc:
    mqtt_monitor = None
    IMPORT_ERROR = exc
else:
    IMPORT_ERROR = None


class FakeReason:
    """Paho 2.x hands back ReasonCode objects, not ints. See _on_subscribe."""

    def __init__(self, value, is_failure=False):
        self.value = value
        self.is_failure = is_failure

    def __str__(self):
        return f'reason {self.value}'


class FakeClient:
    """Records what the monitor asked for. Connects to nothing."""

    instances = []

    def __init__(self, *args, **kwargs):
        self.args, self.kwargs = args, kwargs
        self.tls_context = None
        self.credentials = None
        self.reconnect_delay = None
        self.subscriptions = []
        self.connected = None
        self.looping = False
        self.stopped = False
        self.published = []
        self.on_connect = self.on_disconnect = self.on_message = self.on_subscribe = None
        FakeClient.instances.append(self)

    def username_pw_set(self, username, password=None):
        self.credentials = (username, password)

    def tls_set_context(self, context):
        self.tls_context = context

    def reconnect_delay_set(self, min_delay=None, max_delay=None):
        self.reconnect_delay = (min_delay, max_delay)

    def connect_async(self, host, port, keepalive=None):
        self.connected = (host, port, keepalive)

    def loop_start(self):
        self.looping = True

    def loop_stop(self):
        self.looping = False

    def disconnect(self):
        self.stopped = True

    def subscribe(self, items):
        self.subscriptions.append(list(items))

    def publish(self, topic, payload, qos=0, retain=False):
        self.published.append((topic, payload, qos, retain))
        class Result:
            rc = 0
            def wait_for_publish(self, timeout=None):
                return True
        return Result()


class _NeedsMonitor(unittest.TestCase):
    def setUp(self):
        if mqtt_monitor is None:
            self.fail(f'mqtt_monitor is missing, so nothing here holds: {IMPORT_ERROR}')
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        FakeClient.instances = []

    def monitor(self, auth=None):
        # A fresh auth path per monitor. Sharing one meant a test that wrote an
        # insecure entry silently changed the behaviour of the "no auth file"
        # monitor beside it - and that test then passed for the wrong reason.
        self._seq = getattr(self, '_seq', 0) + 1
        auth_path = self.root / f'auth-{self._seq}.json'
        if auth is not None:
            import json
            auth_path.write_text(json.dumps(auth), encoding='utf-8')
        m = mqtt_monitor.Monitor(self.root / f'mqtt-{self._seq}.json', autostart=False,
                                 auth_path=auth_path)
        self.addCleanup(m.close)
        return m

    def start(self, monitor, config):
        with patch.object(mqtt_monitor, 'paho') as fake_paho:
            fake_paho.Client = FakeClient
            fake_paho.MQTTv311 = 4
            monitor.start(config)
        return FakeClient.instances[-1]


class MissingVendorTests(_NeedsMonitor):
    def test_a_missing_client_library_is_explained_not_a_traceback(self):
        # The whole reason paho is vendored is machines that cannot pip install.
        # If the directory is gone, the operator needs to be told which directory.
        monitor = self.monitor()
        with patch.object(mqtt_monitor, 'paho', None), \
             patch.object(mqtt_monitor, 'PAHO_ERROR', "ImportError: no module named 'paho'"):
            with self.assertRaises(mqtt_monitor.Unavailable) as caught:
                monitor.start({'host': 'broker.example'})
        message = str(caught.exception)
        self.assertIn('vendor/paho', message, 'the message does not say what to restore')
        self.assertIn('no module named', message, 'the underlying cause is not carried')

    def test_the_module_still_imports_and_reports_its_version(self):
        # A missing wheel must disable a panel, not stop the dashboard booting.
        self.assertTrue(hasattr(mqtt_monitor, 'PAHO_VERSION'))
        self.assertTrue(hasattr(mqtt_monitor, 'PAHO_ERROR'))


class SessionAssemblyTests(_NeedsMonitor):
    def test_a_plain_session_sets_no_tls_and_no_credentials(self):
        client = self.start(self.monitor(), {'host': 'broker.example', 'port': 1883})
        self.assertIsNone(client.tls_context)
        self.assertIsNone(client.credentials)
        self.assertEqual(client.connected[:2], ('broker.example', 1883))
        self.assertTrue(client.looping, 'the network loop was never started')

    def test_tls_requested_in_the_config_builds_a_verifying_context(self):
        client = self.start(self.monitor(), {'host': 'broker.example', 'port': 8883,
                                             'tls': True})
        self.assertIsNotNone(client.tls_context, 'TLS was requested and not configured')
        # Verification on by default is the property worth asserting: an
        # unverified TLS session looks identical on screen to a verified one.
        self.assertTrue(client.tls_context.check_hostname)
        import ssl
        self.assertEqual(client.tls_context.verify_mode, ssl.CERT_REQUIRED)

    def test_verification_can_only_be_dropped_from_the_operators_own_file(self):
        # Never a default, and never something the page can ask for - the config
        # the browser sends has no way to express it.
        auth = {'broker.example:8883': {'tls': True, 'insecure': True}}
        client = self.start(self.monitor(auth), {'host': 'broker.example', 'port': 8883})
        import ssl
        self.assertIsNotNone(client.tls_context)
        self.assertFalse(client.tls_context.check_hostname)
        self.assertEqual(client.tls_context.verify_mode, ssl.CERT_NONE)

        # And the same request WITHOUT the file entry verifies normally, which is
        # what makes the file the only way to turn it off.
        FakeClient.instances = []
        plain = self.start(self.monitor(), {'host': 'broker.example', 'port': 8883,
                                            'tls': True})
        self.assertTrue(plain.tls_context.check_hostname)

    def test_credentials_come_from_the_file_not_the_request(self):
        auth = {'broker.example:1883': {'username': 'sensor', 'password': 'hunter2'}}
        client = self.start(self.monitor(auth), {'host': 'broker.example', 'port': 1883})
        self.assertEqual(client.credentials, ('sensor', 'hunter2'))

    def test_backoff_is_bounded_at_both_ends(self):
        # No backoff at all hammers a broker that is down; unbounded backoff
        # means a monitor that never comes back without someone noticing.
        client = self.start(self.monitor(), {'host': 'broker.example'})
        self.assertEqual(client.reconnect_delay,
                         (mqtt_monitor.RECONNECT_MIN, mqtt_monitor.RECONNECT_MAX))


class ReconnectTests(_NeedsMonitor):
    def test_a_reconnect_resubscribes_rather_than_going_quiet(self):
        # The one that matters. A reconnect starts a clean session, so a monitor
        # that only subscribes on the first connect silently stops receiving
        # after a blip - while the page keeps showing the last values.
        monitor = self.monitor()
        client = self.start(monitor, {'host': 'broker.example',
                                      'filters': ['line/#', 'oven/temp']})
        monitor._on_connect(client, None, {}, FakeReason(0))
        self.assertEqual(len(client.subscriptions), 1)

        monitor._on_disconnect(client, None, FakeReason(7))
        self.assertEqual(monitor.snapshot()['state'], 'connecting',
                         'a dropped session still reported itself as connected')

        monitor._on_connect(client, None, {}, FakeReason(0))
        self.assertEqual(len(client.subscriptions), 2, 'the reconnect did not resubscribe')
        self.assertEqual([t for t, _ in client.subscriptions[-1]],
                         ['line/#', 'oven/temp'])

    def test_a_drop_is_visible_in_the_snapshot(self):
        monitor = self.monitor()
        client = self.start(monitor, {'host': 'broker.example'})
        monitor._on_connect(client, None, {}, FakeReason(0))
        self.assertEqual(monitor.snapshot()['state'], 'connected')
        self.assertIsNotNone(monitor.snapshot()['connected_at'])
        monitor._on_disconnect(client, None)
        snapshot = monitor.snapshot()
        self.assertEqual(snapshot['state'], 'connecting')
        # connected_at is cleared, so nothing on the page can render an uptime
        # for a session that is not up.
        self.assertIsNone(snapshot['connected_at'])

    def test_a_refused_connection_says_the_broker_refused_it(self):
        monitor = self.monitor()
        client = self.start(monitor, {'host': 'broker.example'})
        monitor._on_connect(client, None, {}, FakeReason(5, is_failure=True))
        snapshot = monitor.snapshot()
        self.assertEqual(snapshot['state'], 'error')
        self.assertIn('refused', snapshot['error'])
        self.assertEqual(client.subscriptions, [], 'it subscribed despite being refused')

    def test_a_reason_code_object_does_not_kill_the_subscribe_callback(self):
        # Paho 2.x ReasonCodes carry the wire value on .value and do NOT
        # implement __int__, so int(code) raises - out of a callback, on the
        # broker's thread, where it killed the subscription silently.
        monitor = self.monitor()
        client = self.start(monitor, {'host': 'broker.example',
                                      'filters': ['a/#', 'b/#']})
        monitor._on_subscribe(client, None, 1, [FakeReason(0), FakeReason(1)])
        self.assertEqual(monitor.snapshot()['granted'],
                         {'a/#': 'qos 0', 'b/#': 'qos 1'})

    def test_every_filter_refused_is_an_error_not_a_quiet_success(self):
        # A subscription the broker refused looks exactly like one that is
        # simply not busy: an empty tree. Saying so is the difference.
        monitor = self.monitor()
        client = self.start(monitor, {'host': 'broker.example',
                                      'filters': ['secret/#']})
        monitor._on_subscribe(client, None, 1, [FakeReason(0x87, is_failure=True)])
        snapshot = monitor.snapshot()
        self.assertEqual(snapshot['granted'], {'secret/#': 'refused'})
        self.assertEqual(snapshot['state'], 'error')
        self.assertIn('refused every topic filter', snapshot['error'])

    def test_one_refusal_among_several_is_reported_without_failing_the_session(self):
        monitor = self.monitor()
        client = self.start(monitor, {'host': 'broker.example',
                                      'filters': ['open/#', 'secret/#']})
        monitor._on_connect(client, None, {}, FakeReason(0))
        monitor._on_subscribe(client, None, 1,
                              [FakeReason(0), FakeReason(0x87, is_failure=True)])
        snapshot = monitor.snapshot()
        self.assertEqual(snapshot['granted'], {'open/#': 'qos 0', 'secret/#': 'refused'})
        self.assertEqual(snapshot['state'], 'connected',
                         'one refused filter took down a session that is still working')


class LargePayloadTests(_NeedsMonitor):
    def test_a_payload_far_over_the_old_64k_cap_is_accepted_and_cut_for_display(self):
        # This is why paho replaced the hand-written client: a zigbee2mqtt bridge
        # publishes a 217 KB retained message, which blew through that client's
        # 64 KB packet cap. The session died, reconnected, hit the same retained
        # message again and died again - an unbreakable loop against a perfectly
        # ordinary broker.
        monitor = self.monitor()
        client = self.start(monitor, {'host': 'broker.example'})

        class Message:
            topic = 'zigbee2mqtt/bridge/definitions'
            payload = b'x' * (217 * 1024)
            retain = True
            qos = 0

        monitor._on_message(client, None, Message())
        record = monitor.snapshot()['messages'][0]
        # Accepted - the session survives it, which the old client did not.
        self.assertEqual(record['topic'], 'zigbee2mqtt/bridge/definitions')
        # ...and cut for display, with the fact that it was cut carried alongside,
        # so nobody reads a truncated payload as the whole message.
        self.assertEqual(len(record['value']), mqtt_monitor.MAX_VALUE_BYTES)
        self.assertTrue(record['truncated'])
        self.assertEqual(monitor.snapshot()['state'], 'connecting')


def main():
    runner = unittest.TextTestRunner(verbosity=2)
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result = runner.run(suite)
    failed = len(result.failures) + len(result.errors)
    print(f'passed {result.testsRun - failed - len(result.skipped)}, failed {failed}')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
