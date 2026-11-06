# Subnet plan for 10.20.0.0/16

Rule: allocate from the largest requirement to the smallest, start at 10.20.0.0,
place each subnet directly after the previous one, smallest prefix that fits.
Usable hosts = 2^(32 − prefix) − 2.

## Working

| Subnet | Hosts needed | Smallest fit | Why the next smaller prefix fails |
|---|---|---|---|
| app | 1,000 | /22 → 2^10 − 2 = 1,022 | /23 → 2^9 − 2 = 510 < 1,000 |
| public | 250 | /24 → 2^8 − 2 = 254 | /25 → 126 < 250 |
| data | 100 | /25 → 2^7 − 2 = 126 | /26 → 62 < 100 |
| management | 20 | /27 → 2^5 − 2 = 30 | /28 → 14 < 20 |

Placement:
- app starts at 10.20.0.0; a /22 spans 1,024 addresses = 4 × 256 → 10.20.0.0 – 10.20.3.255.
- public starts at the next address, 10.20.4.0; /24 = 256 addresses → 10.20.4.0 – 10.20.4.255.
- data starts at 10.20.5.0; /25 = 128 addresses → 10.20.5.0 – 10.20.5.127.
- management starts at 10.20.5.128 (aligned to 32); /27 = 32 addresses → 10.20.5.128 – 10.20.5.159.

Every start address is a multiple of its block size, so each network address is valid.
10.20.5.160 – 10.20.255.255 remains free.

## Result

| Subnet | Network address | Prefix | Usable host range | Broadcast | Usable hosts |
|---|---|---|---|---|---|
| app | 10.20.0.0 | /22 | 10.20.0.1 – 10.20.3.254 | 10.20.3.255 | 1,022 |
| public | 10.20.4.0 | /24 | 10.20.4.1 – 10.20.4.254 | 10.20.4.255 | 254 |
| data | 10.20.5.0 | /25 | 10.20.5.1 – 10.20.5.126 | 10.20.5.127 | 126 |
| management | 10.20.5.128 | /27 | 10.20.5.129 – 10.20.5.158 | 10.20.5.159 | 30 |

## NACL for the public subnet (`nacl.json`)

The rules are defined once in `network/make_nacl.py`, which writes `nacl.json`.
If `python tools/nacl_sim.py -h` describes different field names, change only
the `fmt()` function there and regenerate.

| Dir | # | Protocol | Ports | CIDR | Action | Purpose |
|---|---|---|---|---|---|---|
| in | 90 | all | all | 198.51.100.0/24 | deny | abusive range, must precede the web allows |
| in | 100 | tcp | 80 | 0.0.0.0/0 | allow | HTTP to the load balancer |
| in | 110 | tcp | 443 | 0.0.0.0/0 | allow | HTTPS to the load balancer |
| in | 120 | tcp | 22 | 10.20.5.128/27 | allow | SSH from management only |
| in | 130 | tcp | 1024–65535 | 10.20.0.0/22 | allow | replies from app (src 8000 → LB ephemeral port) |
| in | * | all | all | 0.0.0.0/0 | deny | default |
| out | 100 | tcp | 8000 | 10.20.0.0/22 | allow | LB → app service |
| out | 110 | tcp | 1024–65535 | 0.0.0.0/0 | allow | replies to clients' ephemeral ports |
| out | * | all | all | 0.0.0.0/0 | deny | default |

Port ranges are destination ports, as in AWS NACLs.

## Why reply rules and rule order matter

A NACL is stateless: it evaluates every packet on its own and keeps no record of
the connections it has allowed. When a client opens TCP 443 to the load balancer,
the inbound rule admits the request, but the response leaves the subnet as a new,
unrelated packet addressed to the client's ephemeral port (1024–65535). Unless an
outbound rule explicitly allows that port range, the reply is dropped. The same
applies in the other direction: the load balancer's request to the app tier on
port 8000 needs an outbound rule, and the app's answer, arriving at the load
balancer's ephemeral port, needs its own inbound rule. A stateful security group
would allow such replies automatically; a NACL never does.

Rules are evaluated in ascending rule number and the first match decides. A
packet from 198.51.100.7 to port 443 matches both the deny for 198.51.100.0/24
and the allow for 443 from 0.0.0.0/0. If the allow had the lower number it
would match first and the abusive client would get in. The deny therefore has
number 90, below every allow it must override.
