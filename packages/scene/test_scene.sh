#!/usr/bin/env bash
# The @agentmux/scene suite, in the shape dashboard/run_tests.sh reads.
#
#   bash <(tr -d '\r' < packages/scene/test_scene.sh)
#
# The translation lives in packages/nodesuite.sh - see its header for why a
# green `node --test` run would otherwise be reported as a failed one.
#
# `three` is the dependency marker. Most of this suite is deliberately pure
# arithmetic and needs no browser and no three.js - the layout, the origin
# whitelist, the conflict-splitting rule and the resource ledger all run in
# bare Node. The handful that do need three skip themselves by name, so the
# rules stay verifiable from a clone with nothing installed.
set -u
[ -f dashboard/server.py ] || { echo 'run this from the agentmux repo root' >&2; exit 2; }
[ -f packages/scene/package.json ] || { echo 'packages/scene is missing' >&2; exit 2; }
. <(tr -d '\r' < packages/nodesuite.sh)
node_suite scene "packages/scene/test/*.test.*" three
