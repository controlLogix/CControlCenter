// Entry point. Opens the store, refuses loudly if it cannot, then listens.
//
// A refusal here is a normal outcome, not a crash: the database is absent, or at
// the wrong schema version, or sitting behind a symlink. Each of those has a
// message that names the path and the fix, and each exits 1 without a stack trace,
// because a stack trace above a perfectly clear sentence trains people to stop
// reading the sentence.

import { DbRefusal, openStore } from "./db.ts";
import { startServer } from "./server.ts";

async function main(): Promise<number> {
  let store;
  try {
    store = openStore();
  } catch (error: unknown) {
    if (error instanceof DbRefusal) {
      console.error(`@agentmux/api: ${error.message}`);
      return 1;
    }
    throw error;
  }

  try {
    const running = await startServer({ store });
    console.error(`@agentmux/api listening on http://${running.address}:${running.port}`);
    console.error(`  store ${store.dbPath} (user_version ${store.userVersion}, ${store.journalMode})`);
    return 0;
  } catch (error: unknown) {
    store.close();
    throw error;
  }
}

const code = await main();
if (code !== 0) {
  process.exit(code);
}
