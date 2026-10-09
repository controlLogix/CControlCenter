// A bounded wire-format check, not an Agentmux TypeScript SDK.
import { connect } from "@nats-io/transport-node";
import { deepStrictEqual } from "node:assert";

const env = (name: string): string => {
  const value = process.env[name];
  if (!value) throw new Error(`Missing ${name}`);
  return value;
};
const nc = await connect({ servers: env("AMX_SPIKE_URL"), token: env("AMX_SPIKE_TOKEN"),
  timeout: 2000, reconnect: false });
try {
  const payload = env("AMX_SPIKE_PAYLOAD");
  const reply = await nc.request(env("AMX_SPIKE_SUBJECT"), new TextEncoder().encode(payload), { timeout: 2000 });
  deepStrictEqual(JSON.parse(new TextDecoder().decode(reply.data)), { request: JSON.parse(payload), server: "python" });
  console.log(JSON.stringify({ client: "typescript", ok: true }));
} finally {
  await nc.close();
}
