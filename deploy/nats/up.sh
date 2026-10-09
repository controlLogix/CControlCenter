#!/usr/bin/env bash
# up.sh - bring the federation cluster up from nothing (docs/FEDERATION.md phase 0).
#
#   up.sh [--circle NAME] [--peers "nick alice"] [--no-kind] [--replicas N]
#
# 1. kind cluster (skipped with --no-kind: uses the current kubectl context)
# 2. self-signed CA + server cert -> secret nats-tls          (assumption A3)
# 3. circle: operator, SYS, account, admin, one user per peer (circle.sh)
# 4. helm upgrade --install nats nats/nats 2.15.0 with values.yaml + auth-values.yaml
# 5. NodePort on kind, wait for the pods, create streams and KV buckets
# Idempotent: re-running skips what exists.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GEN="$HERE/.generated"
CIRCLE=agentmux_demo PEERS="nick alice" KIND=1 REPLICAS=3
while [ $# -gt 0 ]; do
  case "$1" in
    --circle) CIRCLE="$2"; shift 2 ;;
    --peers) PEERS="$2"; shift 2 ;;
    --no-kind) KIND=0; shift ;;
    --replicas) REPLICAS="$2"; shift 2 ;;
    *) echo "unknown arg $1" >&2; exit 2 ;;
  esac
done
mkdir -p "$GEN/tls"; chmod 700 "$GEN"
say() { printf '\n== %s\n' "$*"; }

if [ "$KIND" = 1 ]; then
  say "kind cluster"
  kind get clusters 2>/dev/null | grep -qx agentmux-nats || kind create cluster --config "$HERE/kind.yaml"
  kubectl config use-context kind-agentmux-nats >/dev/null
fi
kubectl get ns nats >/dev/null 2>&1 || kubectl create ns nats

say "TLS (self-signed CA)"
if [ ! -f "$GEN/tls/server.pem" ]; then
  ( cd "$GEN/tls"
    # Python 3.13+ verifies strictly (VERIFY_X509_STRICT): the CA needs basicConstraints
    # and keyUsage, the leaf needs an Authority Key Identifier, or every hub refuses it.
    cat > ca.cnf <<EOF
[req]
distinguished_name=dn
[dn]
[ca]
basicConstraints=critical,CA:TRUE
keyUsage=critical,keyCertSign,cRLSign
subjectKeyIdentifier=hash
EOF
    openssl req -x509 -newkey rsa:2048 -nodes -days 825 -subj "/CN=agentmux-federation-ca" \
      -config ca.cnf -extensions ca -keyout ca-key.pem -out ca.pem 2>/dev/null
    cat > san.cnf <<EOF
[req]
distinguished_name=dn
[dn]
[ext]
basicConstraints=CA:FALSE
keyUsage=critical,digitalSignature,keyEncipherment
subjectKeyIdentifier=hash
authorityKeyIdentifier=keyid,issuer
subjectAltName=DNS:localhost,DNS:nats,DNS:nats.nats,DNS:nats.nats.svc,DNS:nats.nats.svc.cluster.local,DNS:*.nats-headless,DNS:*.nats-headless.nats.svc.cluster.local,IP:127.0.0.1
extendedKeyUsage=serverAuth
EOF
    openssl req -newkey rsa:2048 -nodes -subj "/CN=nats" -keyout server-key.pem -out server.csr 2>/dev/null
    openssl x509 -req -in server.csr -CA ca.pem -CAkey ca-key.pem -CAcreateserial -days 825 \
      -extfile san.cnf -extensions ext -out server.pem 2>/dev/null
    chmod 600 ./*-key.pem )
fi
kubectl -n nats create secret tls nats-tls --cert "$GEN/tls/server.pem" --key "$GEN/tls/server-key.pem" \
  --dry-run=client -o yaml | kubectl apply -f - >/dev/null

say "circle $CIRCLE"
[ -e "$GEN/circle/circle" ] || "$HERE/circle.sh" init "$CIRCLE"
for p in $PEERS; do
  [ -f "$GEN/circle/$p.creds" ] || "$HERE/circle.sh" add "$p" >/dev/null
  echo "  peer $p -> $GEN/circle/$p.creds"
done
"$HERE/circle.sh" helm-values >/dev/null

say "helm nats/nats 2.15.0"
helm repo add nats https://nats-io.github.io/k8s/helm/charts/ >/dev/null 2>&1 || true
helm upgrade --install nats nats/nats --version 2.15.0 -n nats \
  -f "$HERE/values.yaml" -f "$GEN/auth-values.yaml" --set config.cluster.replicas="$REPLICAS" --wait --timeout 10m
[ "$KIND" = 1 ] && kubectl apply -f "$HERE/nodeport.yaml" >/dev/null
kubectl -n nats rollout status statefulset/nats --timeout=5m

say "accounts pushed, streams and buckets"
# A redeploy keeps the resolver PVC; push makes sure it has the current account JWT.
for _ in 1 2 3 4 5 6 7 8 9 10; do
  "$HERE/circle.sh" push >/dev/null 2>&1 && break; sleep 3
done
"$HERE/circle.sh" streams --replicas "$REPLICAS"
say "ready: tls://127.0.0.1:4222  ca=$GEN/tls/ca.pem  creds=$GEN/circle/<peer>.creds"
