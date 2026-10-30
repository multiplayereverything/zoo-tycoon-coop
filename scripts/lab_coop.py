"""Two-copy ZooTogether lab.

Starts private/lab-host and private/lab-client (parked off-screen, below-normal priority). The host
loads a freeform map and hosts; the client joins from the main menu and must receive the host's zoo.
Checks, in order:

  zoo_transfer   client receives the host's saved zoo, loads it and is in the game
  layout         both copies have the same placed, non-moving entities (count + hash)
  cash_join      client budget equals the host budget
  host_change    host add_cash(+12345) shows up on the client
  client_spend   client spends 777 through vanilla subtractCash; host drops by 777; copies agree
  no_double      that spend is applied once
  date           host date advances; host jumps +30 days and the client follows within 3 s
  host_pause     host pauses -> client paused; host unpauses -> client running
  client_pause   client pauses -> host paused (request acked); client unpauses -> host running
  cursor_c2h     client's map cursor (faked at pixel 400,300) arrives at the host, same world position
  cursor_projection  projecting that world position back on the client lands within 8 px of 400,300
  cursor_drawn   the host draws the client's cursor on its frames (FLIP detour counter rises)
  cursor_h2c     host's cursor arrives at the client
  build_c2h      client buys a snack machine with real (posted) mouse clicks; the host builds it too and
                 both copies' layouts match again
  build_drawn    the host's screen changes where the client built (window capture before/after)
  build_h2c      the host buys one with real clicks; the client builds it and the layouts match
  remove_c2h     the client sells its snack machine (the game's sell path, sell dialog skipped); the
                 host removes it too and the layouts match
  remove_h2c     the host sells its snack machine; the client removes it; both are back to the map's
                 original layout
  hire_c2h       the client hires a zookeeper with real clicks; the host adds the same keeper
  admission_c2h  the client sets the admission price (through the price panel's setter); the host takes it
  admission_h2c  the host sets it; the client follows
  move_c2h       the client picks up the keeper it hired and drops it elsewhere; the host moves its copy
                 of that keeper there (staff and animals walk on each copy, so it is found by nearest)
  exhibit_c2h    the client drags a square of fence (real drags; the copies run with ZT_LAB_FAKE_MOUSE so
                 the game's GetCursorPos follows the lab's mouse) and names the new exhibit; the host
                 builds the same fence, gets one more exhibit and shows no name prompt
  exhibit_h2c    the host builds its own exhibit the same way; the client gets it
  animal_c2h     the client adopts an African Elephant inside that exhibit; the host adds it

--mutant nojoin      client never joins          -> zoo_transfer..client_spend must FAIL
--mutant drop_spend  host ignores client spends  -> client_spend must FAIL, the rest pass
--mutant no_date     client ignores host date    -> date must FAIL
--mutant no_cursor   client never sends its cursor -> cursor_c2h and cursor_drawn must FAIL
--mutant no_place    client never sends its builds -> build_c2h, build_drawn (and so remove_c2h) must FAIL
--mutant no_remove   client never sends its removals -> remove_c2h must FAIL
                     (no_place also stops the client's hire, fence and animal, so hire_c2h,
                     exhibit_c2h and animal_c2h fail under it too)
--mutant no_admission  client never sends its price -> admission_c2h must FAIL
--mutant no_move     client never sends its moves -> move_c2h must FAIL

build_drawn needs Pillow; the lab looks for it in private/pylib (pip install --target private/pylib pillow).

Writes private/lab-results/<timestamp>-<mutant>.json; exits 0 when the run's expectation holds.
"""

import argparse
import datetime as dt
import json
import os
import re
import socket
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.join(ROOT, "private", "pylib"))
import zt_launch  # noqa: E402

HOST_DIR = os.path.join(ROOT, "private", "lab-host")
CLIENT_DIR = os.path.join(ROOT, "private", "lab-client")
HOST_CONSOLE = ("127.0.0.1", 8181)
CLIENT_CONSOLE = ("127.0.0.1", 8182)
COOP_PORT = 27150
MAP = "maps\\default.zoo"

ALL_CHECKS = ["zoo_transfer", "layout", "cash_join", "host_change", "client_spend", "no_double", "date",
              "host_pause", "client_pause", "cursor_c2h", "cursor_h2c", "cursor_projection", "cursor_drawn",
              "build_c2h", "build_drawn", "build_h2c", "remove_c2h", "remove_h2c", "hire_c2h",
              "admission_c2h", "admission_h2c", "move_c2h", "exhibit_c2h", "exhibit_h2c", "animal_c2h"]
CURSOR_CHECKS = {"cursor_c2h", "cursor_h2c", "cursor_projection", "cursor_drawn"}
EXPECTED_FAIL = {
    None: set(),
    "nojoin": {"zoo_transfer", "layout", "cash_join", "host_change", "client_spend", "date", "host_pause",
               "client_pause", "cursor_c2h", "cursor_h2c", "cursor_projection", "cursor_drawn",
               "build_c2h", "build_drawn", "build_h2c", "remove_c2h", "remove_h2c", "hire_c2h",
               "admission_c2h", "admission_h2c", "move_c2h", "exhibit_c2h", "exhibit_h2c",
               "animal_c2h"},
    "drop_spend": {"client_spend"},
    "no_date": {"date"},
    "no_cursor": {"cursor_c2h", "cursor_drawn"},
    # no_place also breaks what depends on the client's placements reaching the host; exhibit_h2c fails
    # because the copies then number exhibits differently and a gate carries its exhibit's name.
    "no_place": {"build_c2h", "build_drawn", "remove_c2h", "hire_c2h", "move_c2h", "exhibit_c2h", "exhibit_h2c",
                 "animal_c2h"},  # the host never had the client's build to remove
    "no_remove": {"remove_c2h"},
    "no_admission": {"admission_c2h"},
    "no_move": {"move_c2h"},
}
# Buy menu: the Buildings button, then a free grass pixel; the first item (Snack Machine) is selected.
BUILDINGS_BUTTON = (25, 125)
CLIENT_BUILD_AT = (600, 150)
HOST_BUILD_AT = (450, 110)
STAFF_BUTTON = (25, 170)  # first item: Zookeeper, $800 a month
CLIENT_HIRE_AT = (500, 150)
MOVE_TO = (700, 230)
CONSTRUCTION_BUTTON = (30, 34)  # opens the Fences list
CREATURES_BUTTON = (30, 80)  # first item: African Elephant, $2500
FENCE_LIST = (110, 160)  # 8 wheel notches down puts Low Stick Pole Fence ($55, land) first
FENCE_ITEM = (82, 77)
NAME_OK = (406, 332)  # OK in the "New Exhibit Name" prompt
# The exhibit: a square from S along the two map axes, 3 tiles a side.
EXHIBIT_S, AXIS_A, AXIS_B = (520, 140), (96, 48), (96, -48)
HOST_EXHIBIT_S = (300, 170)  # the host's own exhibit, left of the client's


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


def status(addr):
    """coop_status() as a dict."""
    return dict(kv.split("=", 1) for kv in lua(addr, "return coop_status()").split() if "=" in kv)


def cash(addr):
    m = re.search(r"-?\d+(?:\.\d+)?", lua(addr, "return coop_cash()"))
    return float(m.group()) if m else None


def game_date(addr):
    d = status(addr).get("date", "none")
    try:
        return dt.datetime.strptime(d, "%Y-%m-%dT%H:%M")
    except ValueError:  # "none", or all zeros before any zoo is loaded
        return None


def ui_click(pid, console, x, y):
    """A posted click. Clicks use the message's position, so the fake mouse stays off (see drags)."""
    zt_launch.click(pid, x, y)


PANEL_CLOSE = (172, 17)  # the close button of whichever build panel is open


def open_panel(pid, console, button):
    # One click. (Window captures of these DirectDraw windows can be stale, so the lab doesn't try
    # to read the panel state back.)
    ui_click(pid, console, *button)
    time.sleep(0.8)


def close_panel(pid, console):
    ui_click(pid, console, *PANEL_CLOSE)
    time.sleep(0.5)


def exhibits(addr):
    return int(status(addr).get("exhibits", -1))


def wait_until(pred, seconds, step=0.25):
    end = time.time() + seconds
    while time.time() < end:
        v = pred()
        if v:
            return v
        time.sleep(step)
    return pred()


def run(args, results):
    checks = results["checks"]
    pids = results["pids"]
    base_env = {"OPENZT_NO_CONSOLE": "1", "ZT_LAB_FAKE_MOUSE": "1"}
    client_env = dict(base_env)
    if args.mutant in ("no_date", "no_cursor", "no_place", "no_remove", "no_admission", "no_move"):
        client_env["ZT_COOP_MUTANT"] = args.mutant
    host_env = dict(base_env)
    if args.mutant == "drop_spend":
        host_env["ZT_COOP_MUTANT"] = "drop_spend"

    pids.append(zt_launch.launch(HOST_DIR, host_env))
    time.sleep(3)
    pids.append(zt_launch.launch(CLIENT_DIR, client_env))

    deadline = time.time() + 120
    for addr in (HOST_CONSOLE, CLIENT_CONSOLE):
        if not wait_console(addr, deadline):
            raise RuntimeError(f"console {addr} never came up")
        # The console accepts before the game thread ticks; wait for a real answer.
        t0 = time.time()
        lua(addr, "return coop_status()", timeout=180)
        results.setdefault("first_tick_s", {})[addr[1]] = round(time.time() - t0, 1)
    time.sleep(4)
    for pid in pids:
        zt_launch.park(pid)

    results["notes"].append("host load: " + lua(HOST_CONSOLE, f'return coop_load_zoo([[{os.path.join(HOST_DIR, MAP)}]])', timeout=180))
    time.sleep(3)
    lua(HOST_CONSOLE, "return add_cash(5000)")  # host budget differs from the map's starting budget
    results["notes"].append("host: " + lua(HOST_CONSOLE, f"return coop_host({COOP_PORT})"))
    if args.mutant != "nojoin":
        results["notes"].append("client: " + lua(CLIENT_CONSOLE, f'return coop_join("127.0.0.1:{COOP_PORT}")'))

    checks["zoo_transfer"] = bool(wait_until(
        lambda: status(CLIENT_CONSOLE).get("world_ready") == "true" and status(CLIENT_CONSOLE).get("in_game") == "true", 30))
    layouts = {a[1]: lua(a, "return coop_layout()") for a in (HOST_CONSOLE, CLIENT_CONSOLE)}
    results["layout"] = layouts
    checks["layout"] = layouts[8181] == layouts[8182] and "count=0 " not in layouts[8181]

    def same_cash():
        h, c = cash(HOST_CONSOLE), cash(CLIENT_CONSOLE)
        return h is not None and c is not None and abs(h - c) < 0.01 and (h, c)

    checks["cash_join"] = bool(wait_until(same_cash, 10))

    lua(HOST_CONSOLE, "return add_cash(12345)")
    h1 = cash(HOST_CONSOLE)
    checks["host_change"] = bool(wait_until(lambda: abs((cash(CLIENT_CONSOLE) or 0) - h1) < 1.0, 5))

    time.sleep(1)
    h_before = cash(HOST_CONSOLE)
    lua(CLIENT_CONSOLE, "return coop_test_spend(777)")
    time.sleep(2)
    h_after = cash(HOST_CONSOLE)
    drop = (h_before or 0) - (h_after or 0)
    results["spend"] = {"host_before": h_before, "host_after": h_after, "drop": drop}
    # The host's own sim moves cash a little during the 2 s window; allow +-100.
    checks["client_spend"] = abs(drop - 777) < 100 and bool(wait_until(same_cash, 5))
    checks["no_double"] = drop < 777 * 2 - 100

    # Date: the host's clock runs, and when the host's date jumps 30 days the client follows.
    hd0 = game_date(HOST_CONSOLE)
    time.sleep(4)
    hd1 = game_date(HOST_CONSOLE)
    lua(HOST_CONSOLE, "return coop_test_shift_date(30)")

    def client_follows():
        h, c = game_date(HOST_CONSOLE), game_date(CLIENT_CONSOLE)
        return h and c and h - hd1 > dt.timedelta(days=29) and abs((c - h).total_seconds()) < 86400 and (h, c)

    followed = wait_until(client_follows, 3)
    hd2, cd2 = game_date(HOST_CONSOLE), game_date(CLIENT_CONSOLE)
    results["dates"] = {"host_t0": str(hd0), "host_t4": str(hd1), "host_after_shift": str(hd2), "client_after_shift": str(cd2)}
    checks["date"] = bool(hd0 and hd1 and hd1 > hd0 and followed)
    lua(HOST_CONSOLE, "return coop_set_pause(true)")

    # Pause, host side (host is paused right now from the date check).
    host_paused = wait_until(lambda: status(CLIENT_CONSOLE).get("paused") == "true", 3)
    lua(HOST_CONSOLE, "return coop_set_pause(false)")
    host_unpaused = wait_until(lambda: status(CLIENT_CONSOLE).get("paused") == "false", 3)
    checks["host_pause"] = bool(host_paused and host_unpaused)

    # Pause, client side: a request the host must apply and ack.
    time.sleep(1)
    lua(CLIENT_CONSOLE, "return coop_set_pause(true)")
    c_paused = wait_until(lambda: status(HOST_CONSOLE).get("paused") == "true", 3)
    still = status(CLIENT_CONSOLE).get("paused") == "true"  # not flipped back by a stale snapshot
    lua(CLIENT_CONSOLE, "return coop_set_pause(false)")
    c_unpaused = wait_until(lambda: status(HOST_CONSOLE).get("paused") == "false", 3)
    checks["client_pause"] = bool(c_paused and still and c_unpaused)

    # Cursors. The lab fakes each mouse at a client-area pixel inside the map view.
    lua(CLIENT_CONSOLE, "return coop_test_cursor(400, 300)")
    c_local = status(CLIENT_CONSOLE).get("local_cursor")
    checks["cursor_c2h"] = bool(c_local not in (None, "none") and wait_until(
        lambda: status(HOST_CONSOLE).get("remote_cursor") == c_local, 3))
    back = lua(CLIENT_CONSOLE, f"return coop_world_to_screen({c_local})") if c_local not in (None, "none") else "none"
    m = re.match(r"(-?\d+),(-?\d+)", back)
    # World positions carry no terrain height (z=0), so allow a few pixels.
    checks["cursor_projection"] = bool(m and abs(int(m.group(1)) - 400) <= 8 and abs(int(m.group(2)) - 300) <= 8)
    drawn0 = int(status(HOST_CONSOLE).get("cursors_drawn", 0))
    time.sleep(1.5)
    checks["cursor_drawn"] = checks["cursor_c2h"] and int(status(HOST_CONSOLE).get("cursors_drawn", 0)) > drawn0
    lua(HOST_CONSOLE, "return coop_test_cursor(200, 150)")
    h_local = status(HOST_CONSOLE).get("local_cursor")
    checks["cursor_h2c"] = bool(h_local not in (None, "none") and wait_until(
        lambda: status(CLIENT_CONSOLE).get("remote_cursor") == h_local, 3))
    results["cursor"] = {"client_local": c_local, "client_projection": back, "host_local": h_local}
    for addr in (HOST_CONSOLE, CLIENT_CONSOLE):
        lua(addr, "return coop_test_cursor(-1, 0)")  # back to the (off-window) real mouse for clicks

    # Building, client -> host: a real purchase through the buy menu with posted mouse clicks.
    host_pid, client_pid = pids
    shot = os.path.join(ROOT, "private", "lab-results", "_build.png")
    os.makedirs(os.path.dirname(shot), exist_ok=True)

    def host_region():
        from PIL import Image
        zt_launch.capture(host_pid, shot)
        x, y = CLIENT_BUILD_AT
        with Image.open(shot) as im:
            return list(im.crop((x - 40, y - 60, x + 40, y + 20)).get_flattened_data())

    before = host_region()
    applied0 = int(status(HOST_CONSOLE).get("places_applied", 0))
    open_panel(client_pid, CLIENT_CONSOLE, BUILDINGS_BUTTON)
    ui_click(client_pid, CLIENT_CONSOLE, *CLIENT_BUILD_AT)
    c_placed = status(CLIENT_CONSOLE).get("last_placed")
    got = wait_until(lambda: int(status(HOST_CONSOLE).get("places_applied", 0)) > applied0, 3)
    time.sleep(0.5)
    layouts = {a[1]: lua(a, "return coop_layout()") for a in (HOST_CONSOLE, CLIENT_CONSOLE)}
    checks["build_c2h"] = bool(c_placed not in (None, "none") and got and layouts[8181] == layouts[8182])
    def changed_pixels():
        after = host_region()
        return sum(1 for a, b in zip(before, after) if sum(abs(i - j) for i, j in zip(a, b)) > 60)

    # A capture can return an old frame, so look again for a few seconds before calling it unchanged.
    changed = wait_until(lambda: (lambda n: n if n > 200 else 0)(changed_pixels()), 3, step=0.5) or 0
    checks["build_drawn"] = checks["build_c2h"] and changed > 200
    results["build"] = {"client_placed": c_placed, "host_layout": layouts[8181], "client_layout": layouts[8182],
                        "host_pixels_changed": changed}

    def count(layout):
        m = re.search(r"count=(\d+)", layout)
        return int(m.group(1)) if m else -1

    applied0 = int(status(CLIENT_CONSOLE).get("places_applied", 0))
    client_count0 = count(layouts[8182])
    open_panel(host_pid, HOST_CONSOLE, BUILDINGS_BUTTON)
    ui_click(host_pid, HOST_CONSOLE, *HOST_BUILD_AT)
    h_placed = status(HOST_CONSOLE).get("last_placed")
    got = wait_until(lambda: int(status(CLIENT_CONSOLE).get("places_applied", 0)) > applied0, 3)
    time.sleep(0.5)
    layouts = {a[1]: lua(a, "return coop_layout()") for a in (HOST_CONSOLE, CLIENT_CONSOLE)}
    # Equal layouts only if the client's build reached the host (not under the no_place mutant).
    checks["build_h2c"] = bool(h_placed not in (None, "none") and h_placed != c_placed and got
                               and count(layouts[8182]) == client_count0 + 1
                               and (layouts[8181] == layouts[8182] or not checks["build_c2h"]))
    results["build"].update(host_placed=h_placed, host_layout_2=layouts[8181], client_layout_2=layouts[8182])

    # Removal: each side sells the machine it built.
    def sell(addr, placed):
        m = re.match(r"(\w+)/(\w+)@(-?\d+),(-?\d+),(-?\d+)", placed or "")
        return lua(addr, f'return coop_test_sell("{m[1]}", "{m[2]}", {m[3]}, {m[4]}, {m[5]})') if m else "nothing"

    applied0 = int(status(HOST_CONSOLE).get("removes_applied", 0))
    results["remove"] = {"client_sell": sell(CLIENT_CONSOLE, c_placed)}
    got = wait_until(lambda: int(status(HOST_CONSOLE).get("removes_applied", 0)) > applied0, 3)
    time.sleep(0.5)
    layouts = {a[1]: lua(a, "return coop_layout()") for a in (HOST_CONSOLE, CLIENT_CONSOLE)}
    c_removed = status(CLIENT_CONSOLE).get("last_removed")
    checks["remove_c2h"] = bool(c_removed == c_placed and got and layouts[8181] == layouts[8182])
    results["remove"].update(client_removed=c_removed, host_layout=layouts[8181], client_layout=layouts[8182])

    applied0 = int(status(CLIENT_CONSOLE).get("removes_applied", 0))
    client_count0 = count(layouts[8182])
    results["remove"]["host_sell"] = sell(HOST_CONSOLE, h_placed)
    got = wait_until(lambda: int(status(CLIENT_CONSOLE).get("removes_applied", 0)) > applied0, 3)
    time.sleep(0.5)
    layouts = {a[1]: lua(a, "return coop_layout()") for a in (HOST_CONSOLE, CLIENT_CONSOLE)}
    h_removed = status(HOST_CONSOLE).get("last_removed")
    original = results["layout"][8181]
    checks["remove_h2c"] = bool(h_removed == h_placed and got and count(layouts[8182]) == client_count0 - 1
                                and (layouts[8182] == original or not checks["remove_c2h"]))
    results["remove"].update(host_removed=h_removed, host_layout_2=layouts[8181], client_layout_2=layouts[8182])

    # Staff: hiring places the keeper through the same placement path as a purchase.
    applied0 = int(status(HOST_CONSOLE).get("places_applied", 0))
    open_panel(client_pid, CLIENT_CONSOLE, STAFF_BUTTON)
    ui_click(client_pid, CLIENT_CONSOLE, *CLIENT_HIRE_AT)
    close_panel(client_pid, CLIENT_CONSOLE)
    hired = status(CLIENT_CONSOLE).get("last_placed", "")
    got = wait_until(lambda: int(status(HOST_CONSOLE).get("places_applied", 0)) > applied0, 3)
    host_error = status(HOST_CONSOLE).get("last_error")
    checks["hire_c2h"] = bool(hired.startswith("keeper/") and got and host_error == "-")
    results["hire"] = {"client_placed": hired, "host_last_error": host_error}

    # Admission price, both ways.
    def admission(addr):
        return status(addr).get("admission")

    lua(CLIENT_CONSOLE, "return coop_test_admission(37)")
    checks["admission_c2h"] = bool(wait_until(lambda: admission(HOST_CONSOLE) == "37.00", 3)
                                   and admission(CLIENT_CONSOLE) == "37.00")
    a_host_1, a_client_1 = admission(HOST_CONSOLE), admission(CLIENT_CONSOLE)
    time.sleep(2.5)  # past the client's 2 s hold, so a failed send can't keep the client at 37
    lua(HOST_CONSOLE, "return coop_test_admission(62)")
    checks["admission_h2c"] = bool(wait_until(lambda: admission(CLIENT_CONSOLE) == "62.00", 3))
    results["admission"] = {"after_client_set": [a_host_1, a_client_1],
                            "after_host_set": [admission(HOST_CONSOLE), admission(CLIENT_CONSOLE)]}

    if not checks["zoo_transfer"]:
        # The client never entered the zoo (nojoin): the in-zoo steps below would click its menu.
        for k in ("move_c2h", "exhibit_c2h", "exhibit_h2c", "animal_c2h"):
            checks[k] = False
        return

    # Move: pick up the keeper just hired (the game's pick-up; clicking a walking keeper in a parked
    # window is unreliable) and drop it with a posted click where the fake mouse is.
    applied0 = int(status(HOST_CONSOLE).get("moves_applied", 0))
    m = re.match(r"(\w+)/(\w+)@(-?\d+),(-?\d+),(-?\d+)", hired)
    moved = "none"
    if m:
        lua(CLIENT_CONSOLE, f'return coop_test_pickup("{m[1]}", "{m[2]}", {m[3]}, {m[4]}, {m[5]})')
        lua(CLIENT_CONSOLE, f"return coop_test_cursor({MOVE_TO[0]}, {MOVE_TO[1]})")
        time.sleep(0.5)
        zt_launch.click(client_pid, *MOVE_TO)
        time.sleep(0.5)
        lua(CLIENT_CONSOLE, "return coop_test_cursor(-1, 0)")
        moved = status(CLIENT_CONSOLE).get("last_moved", "none")
    got = wait_until(lambda: int(status(HOST_CONSOLE).get("moves_applied", 0)) > applied0, 3)
    to = re.search(r"->(\w+)/(\w+)@(-?\d+),(-?\d+),(-?\d+)", moved)
    host_near = lua(HOST_CONSOLE, f'return coop_nearest("{to[1]}", "{to[2]}", {to[3]}, {to[4]}, {to[5]})') if to else "none"
    hn = re.search(r"@(-?\d+),(-?\d+)", host_near)
    # The keeper starts walking again right away, so allow a little distance.
    checks["move_c2h"] = bool(got and to and hn and abs(int(hn[1]) - int(to[3])) <= 64 and abs(int(hn[2]) - int(to[4])) <= 64)
    results["move"] = {"client_moved": moved, "host_nearest": host_near}

    def exhibit(builder_pid, builder, other, start):
        """The builder drags a closed square of fence from `start`; the other copy must end with the
        same fence pieces and one more exhibit, with no name prompt of its own."""
        ex0 = {a[1]: exhibits(a) for a in (builder, other)}
        before = set(lua(builder, "return coop_layout_list()").splitlines())
        applied0 = int(status(other).get("places_applied", 0))
        open_panel(builder_pid, builder, CONSTRUCTION_BUTTON)
        zt_launch.wheel(builder_pid, *FENCE_LIST, -8)
        ui_click(builder_pid, builder, *FENCE_ITEM)
        (sx, sy), (ax, ay), (bx, by) = start, AXIS_A, AXIS_B
        corners = [(sx, sy), (sx + ax, sy + ay), (sx + ax + bx, sy + ay + by), (sx + bx, sy + by), (sx, sy)]
        move = (lambda x, y: lua(builder, f"return coop_test_cursor({x}, {y})"))
        for a, b in zip(corners, corners[1:]):
            zt_launch.drag(builder_pid, *a, *b, on_move=move)
        # Closing the exhibit opens the builder's name prompt, which blocks its console until OK.
        time.sleep(1)
        zt_launch.click(builder_pid, *NAME_OK)  # a dialog button takes the message's position
        time.sleep(1)
        lua(builder, "return coop_test_cursor(-1, 0)")
        applied = int(status(other).get("places_applied", 0)) - applied0
        fence_type = (status(builder).get("last_placed") or "?").split("/")[0] + "/"

        def fences(addr):  # every piece of that fence type: position, rotation, type and name
            return sorted(line for line in lua(addr, "return coop_layout_list()").splitlines() if line.startswith(fence_type))

        def same():
            # The pieces this drag added on the builder must all be on the other copy, identical
            # (earlier steps may already have left other differences under a mutant).
            added = set(fences(builder)) - before
            return added if added and added <= set(fences(other)) else None

        # The game turns a fence piece into a gate some frames after the exhibit closes; the
        # replaying copy undoes its own one on a later tick, so give it a few seconds.
        wait_until(same, 5)
        ex1 = {a[1]: exhibits(a) for a in (builder, other)}
        close_panel(builder_pid, builder)
        # Only the fence is compared: under some mutants earlier steps already left the layouts apart.
        ok = bool(all(ex1[k] == ex0[k] + 1 for k in ex0) and same() and applied >= 8)
        return ok, {"exhibits_before": ex0, "exhibits_after": ex1, "pieces_applied": applied,
                    "fence_pieces": len(fences(builder))}

    checks["exhibit_c2h"], results["exhibit_c2h"] = exhibit(client_pid, CLIENT_CONSOLE, HOST_CONSOLE, EXHIBIT_S)
    checks["exhibit_h2c"], results["exhibit_h2c"] = exhibit(host_pid, HOST_CONSOLE, CLIENT_CONSOLE, HOST_EXHIBIT_S)
    (sx, sy), (ax, ay), (bx, by) = EXHIBIT_S, AXIS_A, AXIS_B

    # Animal: adopt one inside the exhibit.
    applied0 = int(status(HOST_CONSOLE).get("places_applied", 0))
    placed0 = status(CLIENT_CONSOLE).get("last_placed")
    open_panel(client_pid, CLIENT_CONSOLE, CREATURES_BUTTON)
    ui_click(client_pid, CLIENT_CONSOLE, sx + (ax + bx) // 2, sy + (ay + by) // 2)
    animal = status(CLIENT_CONSOLE).get("last_placed", "")
    got = wait_until(lambda: int(status(HOST_CONSOLE).get("places_applied", 0)) > applied0, 3)
    host_error = status(HOST_CONSOLE).get("last_error")
    # Animal types are named by species ("elephant/m"); any new placement here is the animal.
    checks["animal_c2h"] = bool(animal not in ("", "none", placed0) and got and host_error == "-")
    results["animal"] = {"client_placed": animal, "host_last_error": host_error}
    close_panel(client_pid, CLIENT_CONSOLE)

    results["status"] = {"host": lua(HOST_CONSOLE, "return coop_status()"),
                         "client": lua(CLIENT_CONSOLE, "return coop_status()")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mutant", choices=["nojoin", "drop_spend", "no_date", "no_cursor", "no_place", "no_remove", "no_admission", "no_move"], default=None)
    ap.add_argument("--keep", action="store_true", help="leave the copies running")
    ap.add_argument("--shots", action="store_true", help="save window captures (needs Pillow)")
    args = ap.parse_args()

    results = {"mutant": args.mutant, "checks": {}, "notes": [], "pids": []}
    try:
        run(args, results)
    except Exception as e:  # noqa: BLE001
        results["error"] = repr(e)
    finally:
        out_dir = os.path.join(ROOT, "private", "lab-results")
        os.makedirs(out_dir, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S") + f"-{args.mutant or 'normal'}"
        if args.shots:
            for name, pid in zip(("host", "client"), results["pids"]):
                try:
                    zt_launch.capture(pid, os.path.join(out_dir, f"{stamp}-{name}.png"))
                except Exception as e:  # noqa: BLE001
                    results["notes"].append(f"capture {name}: {e!r}")
        if not args.keep:
            for pid in results["pids"]:
                zt_launch.kill(pid)

    checks = results["checks"]
    expect_fail = EXPECTED_FAIL[args.mutant]
    ok = "error" not in results and all(
        k in checks and (checks[k] is False if k in expect_fail else checks[k] is True) for k in ALL_CHECKS)
    results["expectation_met"] = bool(ok)

    path = os.path.join(out_dir, stamp + ".json")
    with open(path, "w") as f:
        json.dump(results, f, indent=2)
    print(json.dumps(results, indent=2))
    print("RESULT:", "PASS" if ok else "FAIL", path)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
