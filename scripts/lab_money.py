"""Two-copy lab: shared budget stays in sync (ZooTogether first vertical slice).

Starts private/lab-host and private/lab-client (parked off-screen, below-normal priority), loads the same
freeform map in both through openzt's Lua console, connects them over localhost TCP, then checks:

  1. join:        client budget converges to the host budget
  2. host_change: host add_cash(+12345) shows up on the client
  3. client_spend: client spends 777 through vanilla subtractCash; host budget drops by 777 and
                   both copies agree afterwards
  4. no_double:   the spend is applied once (host is down exactly 777, not 1554)

--mutant nojoin      client never joins -> checks 1-3 must FAIL
--mutant drop_spend  host ignores client spends (ZT_COOP_MUTANT=drop_spend) -> check 3 must FAIL

Writes private/lab-results/<timestamp>.json and exits 0 when the run's expectation holds.
"""

import argparse
import json
import os
import re
import socket
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import zt_launch  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOST_DIR = os.path.join(ROOT, "private", "lab-host")
CLIENT_DIR = os.path.join(ROOT, "private", "lab-client")
HOST_CONSOLE = ("127.0.0.1", 8181)
CLIENT_CONSOLE = ("127.0.0.1", 8182)
COOP_PORT = 27150
MAP = "maps\\default.zoo"


def lua(addr, code, timeout=30.0):
    """Sends one Lua chunk to openzt's console and returns its reply text."""
    with socket.create_connection(addr, timeout=timeout) as s:
        s.sendall(code.encode())
        s.settimeout(timeout)
        data = s.recv(65536)
        s.settimeout(0.3)
        try:
            while True:
                more = s.recv(65536)
                if not more:
                    break
                data += more
        except socket.timeout:
            pass
    return data.decode(errors="replace").strip()


def wait_console(addr, deadline):
    while time.time() < deadline:
        try:
            # Connect only: a queued command would sit until the game thread starts ticking.
            socket.create_connection(addr, timeout=3).close()
            return True
        except OSError:
            time.sleep(1)
    return False


def cash(addr):
    out = lua(addr, "return coop_cash()")
    m = re.search(r"-?\d+(?:\.\d+)?", out)
    return float(m.group()) if m else None


def wait_until(pred, seconds, step=0.25):
    end = time.time() + seconds
    while time.time() < end:
        v = pred()
        if v:
            return v
        time.sleep(step)
    return pred()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mutant", choices=["nojoin", "drop_spend"], default=None)
    ap.add_argument("--keep", action="store_true", help="leave the copies running")
    args = ap.parse_args()

    results = {"mutant": args.mutant, "checks": {}, "notes": []}
    pids = []
    base_env = {"OPENZT_NO_CONSOLE": "1"}
    try:
        host_env = dict(base_env)
        if args.mutant == "drop_spend":
            host_env["ZT_COOP_MUTANT"] = "drop_spend"
        pids.append(zt_launch.launch(HOST_DIR, host_env))
        time.sleep(3)
        pids.append(zt_launch.launch(CLIENT_DIR, base_env))
        results["pids"] = pids

        deadline = time.time() + 120
        for addr in (HOST_CONSOLE, CLIENT_CONSOLE):
            if not wait_console(addr, deadline):
                raise RuntimeError(f"console {addr} never came up")
            # The console accepts before the game thread ticks; wait for a real answer.
            t0 = time.time()
            lua(addr, "return coop_status()", timeout=180)
            results.setdefault("first_tick_s", {})[addr[1]] = round(time.time() - t0, 1)
        for pid in pids:
            zt_launch.park(pid)
        time.sleep(5)  # let the main menu settle

        for addr, d in ((HOST_CONSOLE, HOST_DIR), (CLIENT_CONSOLE, CLIENT_DIR)):
            out = lua(addr, f'return coop_load_zoo([[{os.path.join(d, MAP)}]])', timeout=180)
            results["notes"].append(f"load {addr[1]}: {out}")
        time.sleep(5)
        for pid in pids:
            zt_launch.park(pid)

        # Give the two copies different budgets so convergence is visible.
        lua(HOST_CONSOLE, "return add_cash(5000)")
        h0, c0 = cash(HOST_CONSOLE), cash(CLIENT_CONSOLE)
        results["before_join"] = {"host": h0, "client": c0}

        results["notes"].append("host: " + lua(HOST_CONSOLE, f"return coop_host({COOP_PORT})"))
        if args.mutant != "nojoin":
            results["notes"].append("client: " + lua(CLIENT_CONSOLE, f'return coop_join("127.0.0.1:{COOP_PORT}")'))

        def same():
            h, c = cash(HOST_CONSOLE), cash(CLIENT_CONSOLE)
            return h is not None and c is not None and abs(h - c) < 0.01 and (h, c)

        results["checks"]["join"] = bool(wait_until(same, 10))

        lua(HOST_CONSOLE, "return add_cash(12345)")
        h1 = cash(HOST_CONSOLE)
        results["checks"]["host_change"] = bool(wait_until(lambda: abs((cash(CLIENT_CONSOLE) or 0) - h1) < 0.01, 5))

        # Let the economies tick a moment, then spend on the client and look at the host.
        time.sleep(1)
        h_before = cash(HOST_CONSOLE)
        lua(CLIENT_CONSOLE, "return coop_test_spend(777)")
        time.sleep(2)
        h_after = cash(HOST_CONSOLE)
        drop = (h_before or 0) - (h_after or 0)
        results["spend"] = {"host_before": h_before, "host_after": h_after, "drop": drop}
        # The host's own sim can move cash a little during the 2 s window; allow +-100.
        results["checks"]["client_spend"] = abs(drop - 777) < 100 and bool(wait_until(same, 5))
        results["checks"]["no_double"] = drop < 777 * 2 - 100

        results["status"] = {"host": lua(HOST_CONSOLE, "return coop_status()"),
                             "client": lua(CLIENT_CONSOLE, "return coop_status()")}
    except Exception as e:  # noqa: BLE001
        results["error"] = repr(e)
    finally:
        if not args.keep:
            for pid in pids:
                zt_launch.kill(pid)

    checks = results["checks"]
    if args.mutant is None:
        ok = "error" not in results and len(checks) == 4 and all(checks.values())
    elif args.mutant == "nojoin":
        ok = "error" not in results and not checks.get("join") and not checks.get("host_change")
    else:
        ok = "error" not in results and checks.get("join") and not checks.get("client_spend")
    results["expectation_met"] = bool(ok)

    out_dir = os.path.join(ROOT, "private", "lab-results")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, time.strftime("%Y%m%d-%H%M%S") + f"-{args.mutant or 'normal'}.json")
    with open(path, "w") as f:
        json.dump(results, f, indent=2)
    print(json.dumps(results, indent=2))
    print("RESULT:", "PASS" if ok else "FAIL", path)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
