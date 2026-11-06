"""Generate network/nacl.json for the public subnet from one rule table.

If tools/nacl_sim.py -h documents other field names, adapt fmt() only.
"""
import json
from pathlib import Path

APP, MGMT, ABUSE, ANY = "10.20.0.0/22", "10.20.5.128/27", "198.51.100.0/24", "0.0.0.0/0"
EPH = (1024, 65535)

INBOUND = [
    (90, "all", None, ABUSE, "deny"),
    (100, "tcp", (80, 80), ANY, "allow"),
    (110, "tcp", (443, 443), ANY, "allow"),
    (120, "tcp", (22, 22), MGMT, "allow"),
    (130, "tcp", EPH, APP, "allow"),
]
OUTBOUND = [
    (100, "tcp", (8000, 8000), APP, "allow"),
    (110, "tcp", EPH, ANY, "allow"),
]


def fmt(rule):
    num, proto, ports, cidr, action = rule
    r = {"rule": num, "protocol": proto, "cidr": cidr, "action": action}
    if ports:
        r["port_from"], r["port_to"] = ports
    return r


if __name__ == "__main__":
    out = {"inbound": [fmt(r) for r in INBOUND], "outbound": [fmt(r) for r in OUTBOUND]}
    Path(__file__).with_name("nacl.json").write_text(json.dumps(out, indent=2) + "\n")
    print("wrote network/nacl.json")
