# WSL networking: why the API↔sidecar hop needs a decision

ADR-0023 puts `agentmux-api` **inside WSL**, next to `cc.db` and the `tmux -L agentmux`
server, and the Python field sidecar **on Windows**, because serial Modbus RTU needs COM
ports (`modbus_rtu.py:3`, `:97-98`) and the plant NIC is Windows-side.

Those two halves have to reach each other. On this host, as configured, they cannot.

## Measured, 2026-09-25

No `%USERPROFILE%\.wslconfig` exists, so WSL 2.3.26.0 is in **default NAT mode** on
Windows 10.0.26200.

```
WSL eth0:        172.30.116.31/20
default gateway: 172.30.112.1
resolv.conf ns:  10.255.255.254      <- the DNS proxy, NOT the host
```

Direction matters, and only one of them works:

| | Result |
|---|---|
| Windows browser → WSL listener on `127.0.0.1:8787` | **works** — `localhostForwarding` is on by default. This is how the dashboard is viewed today (verified HTTP 200) |
| WSL → Windows listener on `127.0.0.1:9999` | **unreachable** — `127.0.0.1` inside WSL is WSL's own loopback |
| WSL → Windows listener via the gateway `172.30.112.1:9999` | **also unreachable**, because that listener is bound to `127.0.0.1` only |

That last row is the one worth internalising. Reaching Windows from WSL in NAT mode is
not simply "use the gateway address" — the Windows service must *also* bind the
`vEthernet (WSL)` address. So **"the sidecar binds loopback only" and "the API runs in
WSL" cannot both be true under NAT.**

Do **not** parse `/etc/resolv.conf` for the host address: it is `10.255.255.254`, the DNS
proxy, not the host. Do not use `$(hostname).local` either; mDNS is unreliable here.

## The decision, and why it is not yet applied

ADR-0024 chose **mirrored networking**:

```ini
# %USERPROFILE%\.wslconfig
[wsl2]
networkingMode=mirrored
```

Supported on this build (WSL ≥ 2.0.0, Windows ≥ 22H2). After it, `127.0.0.1` means the
same thing on both sides, all Windows-side services stay **genuinely** loopback-bound,
and `netscan.py`'s documented WSL degradation is repaired — `netscan.py:186-201` names
mirrored mode as the case where the Linux ARP path is correct.

**It has not been applied, deliberately.** Mirrored networking is a *machine-wide*
change, it brings WSL traffic under Windows Firewall, and it has known interactions with
other hypervisors' virtual adapters. This host has two of those up right now:

```
VMware Network Adapter VMnet8
VMware Network Adapter VMnet1
vEthernet (WSL (Hyper-V firewall))
```

Applying it also requires `wsl --shutdown`, which restarts every distro. Nothing in
Phase 1 exists yet that needs the hop, so flipping it now buys nothing and risks
disturbing VMware networking that the operator cannot observe while away.

**Apply it when Phase 1.1 actually stands the sidecar up, with the operator present.**

## Applying it

```powershell
# 1. Write the config
@"
[wsl2]
networkingMode=mirrored
"@ | Set-Content -Encoding utf8 $env:USERPROFILE\.wslconfig

# 2. Restart every distro
wsl --shutdown
```

Then verify **both** directions, because only one of them is broken today and it is easy
to test the working one and declare victory:

```powershell
# Windows listener, read from WSL
Start-Process python -ArgumentList '-m','http.server','9999','--bind','127.0.0.1' -WindowStyle Hidden
wsl.exe -e curl -sf http://127.0.0.1:9999/ && echo "WSL -> Windows loopback OK"
```

```bash
# WSL listener, read from Windows
wsl.exe -e python3 -m http.server 9998 --bind 127.0.0.1 &
powershell.exe -NoProfile -Command "curl.exe -sf http://127.0.0.1:9998/"
```

And check what mirrored mode can disturb:

- DNS resolution still works (`nslookup github.com` in both).
- The VMware VMnet1/VMnet8 adapters are still `Up` and any VM still has its network.
- Docker Desktop still starts and its containers still reach the network. The
  `docker-desktop` distro is installed on this host.
- Any VPN client in use still routes correctly, including split-tunnel.

Record the outcome here rather than in a chat log.

## Rollback

One line, under a minute, and it should be exercised once so it is known to work:

```powershell
Remove-Item $env:USERPROFILE\.wslconfig
wsl --shutdown
```

## If mirrored mode is rejected

The fallback works today, and it is strictly weaker:

- The Windows sidecar binds `127.0.0.1` **plus** the `vEthernet (WSL)` host address —
  loopback alone is not reachable, per the table above.
- A Windows Firewall inbound rule scopes that port to the WSL subnet (`172.30.112.0/20`
  as measured; it changes).
- The API resolves the host at startup from `ip route show default | awk '{print $3}'`,
  and re-resolves on every connection failure, because the gateway changes across
  reboots.
- `AGENTMUX_FIELD_URL` overrides all of it.

If that path is taken, **stop calling it "loopback-only" in the docs.** Call it
"loopback plus the WSL virtual adapter", or someone will later rely on a property the
system does not have.
