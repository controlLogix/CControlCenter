# Two-hub leaf recovery fixture

Run `python tests/leaf/run.py` with the prepared `nats-py==2.16.0` environment. The runner requires NATS Server 2.15.0 at `~/.cache/agentmux-governance/tools/nats-server`; `AGENTMUX_LEAF_SERVER` may select the same pinned version elsewhere. Missing or different dependencies fail; no checks are skipped.

The test starts two owned loopback servers with separate file stores and JetStream domains, `ORIGIN` and `RECEIVER`. Each has a private owner account, a dedicated link account and an unrelated account. The receiver's leaf authenticates to an origin link user whose publish/subscribe permissions allow only the fixture event and command subjects. Ordinary bridge clients have directional subject permissions and no JetStream access. Test-only local probes in the link accounts have broader permissions to prove that the leaf itself blocks unrelated subjects in both directions. They close before the lost-acknowledgment test. Owner clients write only their local account's ledger. There are no account exports or imports exposing private ledgers.

The fixture follows this sequence:

1. Prove a command crosses the authenticated leaf, then check rejected subjects, private storage access and an unrelated account. A successful delivery acts as the control for the account-isolation timeout.
2. Persist an origin reservation, send an offer across the leaf and persist receiver acceptance. Publish its acknowledgment while the origin has no event subscription, deliberately losing that acknowledgment. The origin still records an unknown acceptance outcome.
3. Stop the origin broker. The receiver retains the reservation and computes a hash of one approved fixture file. Its local guard rejects another project, another path and write actions. The input remains unchanged.
4. Restart the receiver while the origin remains stopped. Read its stored result. Restart the origin and verify that its reservation survived and differs from the receiver's independently stored state.
5. Reconnect the leaf and resolve the acceptance outcome using the original operation identity and digest. Reject a conflicting digest. Retry the actual original offer and an altered offer, recompute their digests, and verify that neither replay adds a write or a second execution.
6. Return the retained completion event over the leaf. Completion alone leaves the origin task reserved. The origin owner checks the result and writes acceptance to its private ledger; the receiver still records completion rather than task acceptance.

Each owner update is one complete JSON record appended with `Nats-Expected-Last-Subject-Sequence`. Both servers use the same stream and subject names, so distinct recovered contents also check that their stores are not silently shared. This is a test protocol for the accepted P00 reservation rules. It does not import the evolving SDKs or claim full message-envelope, signature or registered payload conformance; those have separate P01 checks.

The runner writes source-bound results to `docs/planning/2026-10-09/delivery/evidence/P01/leaf-result.json`, including failures. It records source and broker hashes, runtime versions, individual checks and explicit limits. Generated passwords remain in private temporary configuration files or process memory, never command arguments or saved evidence. Broker logs stay inside the owned temporary directory. All clients and owned processes are stopped and temporary data is removed after the run.

This qualifies a local two-broker fixture, not production enrollment, TLS, OIDC, current-grant enforcement, plugin execution, replica quorum, power-loss recovery, native macOS or final bilateral release acceptance. The scope guard and task acceptance are explicit fixture logic; account and subject denials come from the real brokers. Existing application source, user configuration and data are untouched.

Configuration follows the official [leaf topology guide](https://docs.nats.io/learn/topologies/leaf-nodes), [leaf account binding](https://docs.nats.io/reference/config/leafnodes/remotes) and [NATS authorization reference](https://docs.nats.io/running-a-nats-service/configuration/securing_nats/authorization). Separate JetStream domains keep local storage independent; a leaf link does not itself persist disconnected messages or transfer task ownership.
