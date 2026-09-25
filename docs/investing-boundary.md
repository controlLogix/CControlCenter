# Where financial artifacts live, and why it is not here

**This repository is public.** `gh repo view` reports
`controlLogix/CControlCenter`, `isPrivate: false`, and `.bytedesk/task-management/`
is committed along with everything else.

Phase 5 of the rewrite adds a brokerage session. That produces positions,
balances, account numbers, order records, confirmation numbers and research
packs — every one of which is a thing that must never reach a public remote.

A push cannot be taken back. A file deleted in the next commit stays in the
history, and by the time anyone notices it has been cloned, mirrored and
indexed. So this is not a tidiness rule; it is the one mistake in Phase 5 that
cannot be undone by writing the old value back — unlike a PLC tag, and unlike a
board row.

## The two destinations

| What | Where | Why there |
| --- | --- | --- |
| The Fidelity session: browser profile, cookies, device-trust token, order records, screenshots taken on selector drift | `%LOCALAPPDATA%\agentmux\broker\` | Windows-side, because that is where the headed browser and DPAPI/Credential Manager are. NTFS rather than 9p, so the profile is not on the least reliable path in the system. |
| Positions, balances, unrealised P/L, research session state | `$AGENTMUX_HOME/investing/` | ext4, beside `cc.db` and everything else this project keeps per-operator. |

Neither is inside the repository, and neither is inside any directory the
repository walks.

## What enforces it

Three things, and they cover different failure modes on purpose:

1. **`.gitignore`** pins `investing/`, `broker/`, `agentmux-broker/` and
   `research/sessions/`, so an artifact written into the tree by mistake lands
   ignored rather than staged.
2. **`dashboard/check_no_financial_artifacts.sh`** runs in the gate. It fails
   if anything is tracked under those paths, if a tracked file is *named* as a
   position/order/balance record, if a value labelled as an account number is
   committed, or **if the `.gitignore` pins themselves go missing** — because a
   check that only looked at today's tree would pass the moment someone removed
   them.
3. **This document**, which is checked for by that script. The pins record where
   artifacts must not go; only prose can record where they must go instead, and
   a decision that lives solely in the author's memory is one the next person
   will make differently.

## What it does not catch, stated plainly

The account-number check is anchored on the **word**, not on the digit shape: it
fires on an assignment that *names* the value an account number, and not on a
bare nine-digit literal on its own. That is
deliberate. Nine digits in a source file are a port, a timestamp or an id far
more often than an account, and a check that flagged the shape would fire across
half the repo and be switched off within a week — which is how a gate stops
being read.

So this makes the careless case impossible and the determined case no harder.
It is a guard against a slip, not against intent, and it should not be described
as more than that.

## The research carve-out

`enhance-research` writes finished packs to
`.bytedesk/task-management/research/<date>-<slug>.md`, which **is** committed —
that is the point of keeping research with the work it informed.

**Financial research does not go there.** Not a summary, not a thesis, not a
position sized in it. `research/sessions/` is ignored for unfinished thinking of
any kind, following the reasoning already written into this repo's `.gitignore`
for `planner/`: *one machine's unfinished thinking.* Anything about money stays
under `$AGENTMUX_HOME/investing/` with the rest of it.
