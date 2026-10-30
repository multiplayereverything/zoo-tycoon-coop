# ZooTogether — Zoo Tycoon (2001) co-op: plan and hand-off

Status: **join-in-progress, budget, date, pause, player cursors, building / selling objects, hiring
staff and the admission price work in a two-copy lab** (see "Lab"), version 0.5.0-dev (protocol 6).
Animals (they need exhibits, i.e. drag-built fences), firing staff, guests, research and awards are not
synced yet.
How to work on this repo: [AGENTS.md](AGENTS.md) (Karpathy guidelines + project rules). Repo: https://github.com/multiplayereverything/zoo-tycoon-coop (no
release yet). Built on [openzt](https://github.com/openzt1/openzt) (by the openzt authors; LICENSE file
GPL-3.0, Cargo metadata MIT/Apache-2.0, so this repo is GPL-3.0), a Rust DLL that the game loads as
`res-openzt.dll` and that detours game functions at fixed addresses.

## Layout

```
Zoo Tycoon\                      the game install (Complete Collection, zoo.exe 1.0 build 12.4.0.9)
Zoo Tycoon\ZooTogether\          this repo (the game never scans it)
  handoff.md                     this file
  AGENTS.md                      working rules for agents and humans (Karpathy guidelines)
  scripts\build.cmd              builds res-openzt.dll with the coop feature (VS x86 env)
  scripts\setup-lab.ps1          makes private\lab-host + private\lab-client (hardlinked copies)
  scripts\zt_launch.py           starts a copy suspended, lifts the one-instance check, parks it
                                 off-screen, captures its window (PrintWindow, needs Pillow)
  scripts\lab_coop.py            the two-copy co-op lab, 21 checks (+ 7 mutants)
  scripts\lab_all.py             runs lab_coop normally and once per mutant, writes a summary table
  scripts\get-openzt.ps1         clones openzt at df01b96 and applies the patch into vendor\openzt
  patches\openzt-zoo-together.patch   our changes to openzt, as patches on upstream df01b96
  vendor\openzt\                 openzt checkout, branch zoo-together (its own git repo, ignored here)
  private\                       lab copies and results (ignored)
```

## Game identity

- zoo.exe SHA-256 `9cec15e08b8c0bac1a7418422452ffb22e6d98f397fb8c4e69ec13faa05a43ef`, 2,440,327 bytes,
  PE32 x86, FileVersion 12.4.0.9, PE header at offset 12 (REA can't open it; plain PE parsing and
  capstone work).
- Matches openzt's address tables: `ZTGameMgr::addCash` at 0x40f018 is `mov eax,[esp+4]; add ecx,0xc`
  (cash at `this+0xC`), as openzt expects.
- No Steamworks, no anti-cheat. Retail/CD-era install copied to the Desktop (setuplog shows it was
  unwrapped from `C:\Program Files (x86)\Microsoft Games\Zoo Tycoon`, which no longer exists).
- Imports `WS2_32.dll` and tries `dpnhpast.dll` (DirectPlay NAT helper), probably for the web/
  "download" features; there is no multiplayer mode to reuse.

## Research (coop-triage / coop-research)

- Co-op Anything directory: no Zoo Tycoon entry. Web and GitHub: no ZT1 multiplayer mod or attempt
  found. Co-op exists only in the unrelated 2013 Xbox *Zoo Tycoon*. openzt has no networking code or
  issue; related projects (openzt2, openzt-loader PoC) are not multiplayer either.
- Route: **build from zero on top of openzt** (coop-build-from-zero).

## What openzt gives us (and what it doesn't)

Has (and we reuse):
- DLL loading with no exe patching: the game loads `res*.dll`; openzt hooks `BFApp::loadLangDLLs` for
  late init.
- Detour framework with a generated table of thousands of vanilla function addresses
  (`openzt-detour/src/generated.rs`), plus Rust reimplementations of whole managers.
- **`ZTGameMgr` fully ported to Rust** (`ztgamemgr.rs`): cash, date, add/subtractCash detoured, save/load.
- Lua console on TCP (default 127.0.0.1:8080, set per copy in `openzt.toml [dev] console_listen`),
  run on the game thread from the `ZTApp::updateSim` detour. Our lab drives the game through it.
- World/entity readers (`ztworldmgr.rs`: entity lists, types, positions), habitats, research,
  marketing, guests (partial), UI helpers, save/load primitives (`ztui_gameopts::LOAD_FILE`).

Missing for multiplayer (what we add):
- Networking of any kind (added: `coop.rs`).
- Entering a zoo and saving one from code (added: `load_zoo`, `save_zoo_bytes`).
- A clean "entity placed / removed" event and a way to place or remove an entity of a given type
  from code (added, see "Building sync").
- Determinism: the sim uses its own RNG and timing; we will not try lockstep (see authority model).
- In-game UI for host/join (today: env vars or console commands).
- openzt is still WIP upstream, so we pin to upstream df01b96 and rebase deliberately.

## Authority model

**Host-authoritative, state-sync (not lockstep).** The host runs the only real simulation. Clients
send *intents* (spend, pause, later place/delete/set admission price...) and receive *state* (budget,
date, pause, later entity add/remove). Zoo Tycoon's sim is not deterministic across machines, and a
zoo has thousands of guests, which we can stream coarsely or let each client simulate cosmetically.

Phases:
1. **Shared budget** (done): host streams cash at 5 Hz; client purchases through vanilla
   `subtractCash` become `Spend{seq}` intents; host acks by seq; client shows host cash minus unacked
   spends (no flicker).
2. **Join-in-progress** (done): on the client's hello the host saves its zoo through the game's own
   `SAVE_GAME` (the save dialog `GET_SAVE_FILE_NAME_A` 0x477046 is detoured to answer with
   `Saved Games\zootogether-host.zoo`), streams the file in 32 KB `ZooChunk`s, and the client loads it
   the way the main menu's "Load Saved Game" does (`LOAD_FILE` → `ZTGameMgr::start` → hide the start
   screen element 0x1a, see `ztui_startup::TRIGGER_LOAD` 0x4cc606). State is ignored until then.
3. **Date and pause** (done): the host's 16-byte `SYSTEMTIME` and paused flag ride in every `State`.
   The client overwrites its date each snapshot (its own clock runs in between, so it can be up to
   ~30 game-minutes ahead for 200 ms). The paused flag is the byte at `ZTApp(0x638148)+0x440`, set and
   cleared by `ztui_main::PAUSE_GAME`/`UNPAUSE_GAME`. A client toggle becomes `Pause{seq}`; the host
   applies and acks it; the client keeps its choice until acked. Either player pausing pauses both.
   Zoo Tycoon 1 has no game-speed setting, so there is no speed to sync.
4. **Player cursors** (done): each player sends their mouse's map position in **world** units
   (`Cursor`, at most every 100 ms, only when it changes; `None` when the mouse is off the map). The
   other side projects it through its own camera and draws a yellow crosshair labelled "Player 2" /
   "Host" on the back buffer just before the frame is presented (`GXVideoManager::flip` detour).
   Geometry: `ZTMapView+0x360` is the `BFMap`; `BFMap+0x14/+0x18` is the camera origin in virtual
   (projected screen-plane) pixels; `ZTMapView+0x4c/+0x50` is the view size; view pixel = virtual −
   origin; `BFMap::virtualToWorld(this, out, in)` 0x4441ab and `worldToVirtual(this, out, in)` 0x40f041
   convert (3 × i32); `UIElement::getScreenPos` gives the view's top-left. Back buffer:
   `videomgr+0x20` (`IDirectDrawSurface`; `GetDC` slot 17, `ReleaseDC` slot 26); windowed mode Blts it
   to the primary, fullscreen Flips. The local mouse comes from `GetCursorPos` + `ScreenToClient` on the
   game thread's window.
5. **Building and selling** (done): see "Building sync". Hiring staff is the same placement (the
   Staff menu puts a keeper on the cursor and the map click places it), so it replicates too; the hired
   keeper then walks on its own on each copy.
6. **Admission price** (done): `ZooStatus` is at `ZTGameMgr+0x10`, the adult price is the f32 at
   `+0x1150`. The price panel calls `ZooStatus::setAdultAdmissionPrice` (0x4bbf10; callers 0x616e78,
   0x616ea7, 0x616ff2 look like the panel's buttons, not clicked in the lab), which openzt's
   `zoostatus.rs` detours; it now reports to coop. The host's price rides in every `State`; a client
   change goes to the host as `Admission(price)`, and the client keeps its value until a `State` shows
   it (2 s at most).
7. Animals (needs fence/exhibit sync first), animal/staff positions, guests (interest-managed, low rate), exhibits, research, awards. Until then
   each copy simulates guests and animals on its own from the join snapshot on.

## Networking

- No Steamworks in this build → **direct IP / LAN TCP**, default port **27150**. Host: `coop_host()`,
  client: `coop_join("ip[:port]")`, or set `ZT_COOP_HOST=<port>` / `ZT_COOP_JOIN=<ip[:port]>` before
  launching. Over the internet the host must forward TCP 27150, or both use a VPN (Tailscale/ZeroTier).
- Next: global mod relay (tunnel mode) so friends can join by room code without port forwarding.
- Frames: `u32 len | u8 type | payload` (max 64 KB), protocol 6: Hello{protocol,role},
  State{seq,cash,acked_spend,acked_pause,paused,date[16],admission}, Spend{seq,amount},
  Pause{seq,paused}, ZooChunk{offset,total,data}, ZooLoaded{ok}, Cursor{visible,x,y,z},
  Placed/Removed{x,y,z,rotation,zt_type,zt_sub_type}, Admission{price}, Keepalive (writer thread, 1 s; read timeout 30 s, per
  Baldi's link-health lesson). A protocol mismatch shows in `coop_status()` and nothing is applied.

## Building sync (protocol 4-5, 2026-10-30)

Objects are named on the wire by their type's `zt_type`/`zt_sub_type` strings (type `+0x98`/`+0xa4`,
e.g. `building/vendfood`) plus world position (entity `+0x114`, x/y/z) and rotation (`+0x12c`). Both
copies loaded the same save, so the same strings name the same type, and type + position finds the same
object. Each side sends what its player did; the other side replays it. Both sides send (a purchase is
already paid through the shared budget; the host replays the client's builds at no cost).

- **Place.** A purchase puts a created entity on the cursor (`ZTMapView::setTempEntity` 0x4f189a) and
  the map click calls `ZTMapView::placeEntityOnMap(entity, cost, 0)` (0x4d9088, from the
  left-button-up handler 0x4d871e), which returns the placed entity. openzt's `roofs.rs` already
  detours it, so coop is called from inside that detour (`on_entity_placed`). Replay (`place_entity`):
  `BFEntityType::create(type, false)` (0x412669; openzt calls it `bfoverlaytype::CREATE`), write the
  rotation, `BFEntity::setWorldPos`, **`BFEntity::snapToGrid` (0x505763)**, then `placeEntityOnMap` with
  cost 0. Without `snapToGrid` the entity is in the world list but never drawn: it fills the screen
  position at `+0xb4/+0xb8`, which the buy cursor does while the player moves the object (found by
  diffing a UI-placed and a code-placed entity).
- **Remove.** Selling and bulldozing end in `ZTMapView::removeEntityFromMap(entity, refund, ...)`
  (0x50a0b0; callers `removeEntity` 0x50a432, which the sell path `removeSelectedEntity` 0x48d065 uses,
  plus 0x485b41 and 0x4efd12). Coop detours it (`removal_detours`), takes the object's description
  before the call, and sends it only if the object is really gone afterwards. Selling a building asks
  "are you sure?" inside that call (0x50bf8d → `BFUIMgr` confirm dialog 0x4fff2c, which runs nested
  game frames until answered; the player may say no). It only asks when the map view's byte `+0x456`
  is set, so the replay (`remove_entity` → `removeEntity`) clears that byte for the call and the other
  player gets no dialog. The replaying copy refunds itself; on the client that refund is overwritten by
  the host's budget, so only the host's refund counts.
- **Nested frames.** That dialog's nested frames re-enter openzt's per-frame hook. The console's
  `call_next_command` and `coop::tick` now `try_lock` their mutex and skip a re-entered frame instead of
  deadlocking (found with a stack sample of the hung copy).
- Only placed, non-moving objects are synced (the `coop_layout` set: buildings, scenery, fences,
  paths, tank walls/filters). Animals, guests and staff are not.

## Our changes to openzt (branch `zoo-together`)

- `openzt/src/coop.rs` (new, feature `coop`): session, wire format, ledgers, pause sync, zoo transfer,
  save-dialog detour, cursor sync + `GXVideoManager::flip` detour that draws the other player's cursor,
  building sync (place replay, `removeEntityFromMap` detour, remove replay), Lua commands
  (`coop_host/join/stop/status/cash/layout/load_zoo/place/remove`, lab helpers `coop_test_spend`,
  `coop_set_pause`, `coop_test_shift_date`, `coop_test_cursor`, `coop_world_to_screen`,
  `coop_test_sell`), 8 unit tests.
  user32/gdi32 calls are declared locally so openzt's `windows` crate features stay untouched.
- `ztgamemgr.rs`: `set_cash_and_refresh`, `is_started`, `coop_date_bytes`/`coop_set_date_bytes`; the
  vanilla `subtractCash` detour reports spends to coop.
- `ztworldmgr.rs`: `static_layout_fingerprint()` (count + hash of buildings, scenery, fences, paths,
  tank walls/filters by class, type name and position), `coop_static_entities()`, `coop_entity_types()`.
- `roofs.rs`: its `PLACE_ENTITY_ON_MAP_1` detour calls `coop::on_entity_placed` with the placed entity.
- `command_console.rs`: `coop::tick()` each frame in the existing `ZTApp::updateSim` detour;
  per-request reply channel and FIFO queue (fixes the busy-spin/stolen-reply bug); `call_next_command`
  uses `try_lock` so nested game frames (modal dialogs) don't deadlock it.
- `logging.rs`: `OPENZT_NO_CONSOLE=1` skips `AllocConsole` (hidden lab copies).
- Cargo features: `coop` in `openzt` and `openzt-dll`.

## Build

`scripts\get-openzt.ps1`, then `scripts\build.cmd` (needs VS 2022 Build Tools with x86, Rust from
`rust-toolchain.toml`). Two traps: LuaJIT's msvcbuild needs **x86** `cl` on PATH (vcvars32), and fails
with "'minilua' is not recognized" when `NoDefaultCurrentDirectoryInExePath` is set (Claude Code sets
it). The script handles both. Output: `vendor\openzt\target\i686-pc-windows-msvc\release\openzt.dll`
→ copy as `res-openzt.dll`.

## Lab

- `scripts\setup-lab.ps1`, then `python scripts\lab_all.py` runs everything (normal runs plus each
  mutant: `nojoin`, `drop_spend`, `no_date`, `no_cursor`, `no_place`, `no_remove`, `no_admission`)
  one copy pair at a
  time and writes `private\lab-results\<time>-summary.md`. `python scripts\lab_coop.py [--mutant X]
  [--shots] [--keep]` runs one. Window captures and `build_drawn` need Pillow in `private\pylib`
  (`pip install --target private\pylib pillow`). Copies run
  below-normal priority, windowed 800x600 (the game's minimum mode; 640x360 isn't available), no intro
  movies, no openzt console window, **parked off-screen at (-4000,-4000) without focus, not
  minimized**: a minimized Zoo Tycoon window stops its whole game loop (no `updateSim`, so the console
  and the co-op tick freeze; loads hang). Measured 2026-10-30.
- **One instance check**: zoo.exe's function at 0x5337e6 does `FindWindowA(appClass)` and refuses to
  start if another Zoo Tycoon window exists. `zt_launch.py` starts the copy suspended and patches that
  function to `xor eax,eax; ret` in memory only. Real players run one copy per PC and don't need it.

- **Clicks**: `zt_launch.click` posts mouse messages to the parked window. Zoo Tycoon ignores the
  mouse while it thinks another app is active (with two copies, the one started last is), so `click`
  first posts `WM_ACTIVATEAPP`/`WM_ACTIVATE`. Buying works this way (Buildings button at (25,125), the
  first item is the $50 Snack Machine, then a map click). Selling through the bulldozer (the Delete key
  turns it on) did not work with posted clicks; it seems to pick the object under the *real* mouse,
  not checked. The lab sells through the game's sell path from Lua instead (`coop_test_sell`).

### Results, protocol 6 (2026-10-30, private\lab-results\*-summary.md)

New checks: `hire_c2h` (the client hires a zookeeper with posted clicks: Staff button (25,170), map
(500,150); the host places the same `keeper/m` with no error; a host capture shows the keeper) and
`admission_c2h`/`admission_h2c` (client sets 37 through the setter, both copies show 37.00; host sets
62, both show 62.00).

The protocol-5 DLL with `hire_c2h` passed the full suite at 07:06-07:15 (two normal runs 19/19, all six
mutants caught, `no_place` also fails `hire_c2h` as expected). The protocol-6 DLL: normal 07:16 21/21,
`no_admission` 07:17 caught (only `admission_c2h` fails); see the latest summary file for the full
suite run after that.

### Results, protocol 5 (2026-10-30 06:51-07:01)

New checks: the client buys a snack machine with posted clicks and the host builds it, with both
`coop_layout` hashes equal (`build_c2h`); the host's screen changes where it was built (`build_drawn`,
1166 pixels in an 80x80 box); the host buys one and the client builds it (`build_h2c`); each side sells
its machine and the other removes it, ending at the map's original layout `count=392 hash=dde9bf88…`
(`remove_c2h`, `remove_h2c`).

| Run | 13 earlier checks | build_c2h | build_drawn | build_h2c | remove_c2h | remove_h2c | Verdict |
|---|---|---|---|---|---|---|---|
| normal 06:51 | 13/13 ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | PASS |
| normal 06:59 | 13/13 ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | PASS |
| mutant `nojoin` | 1/13 (no_double) | ❌ | ❌ | ❌ | ❌ | ❌ | PASS (caught) |
| mutant `drop_spend` | 12/13 (client_spend ❌) | ✅ | ✅ | ✅ | ✅ | ✅ | PASS (caught) |
| mutant `no_date` | 12/13 (date ❌) | ✅ | ✅ | ✅ | ✅ | ✅ | PASS (caught) |
| mutant `no_cursor` | 11/13 (cursor_c2h, cursor_drawn ❌) | ✅ | ✅ | ✅ | ✅ | ✅ | PASS (caught) |
| mutant `no_place` | 13/13 | ❌ | ❌ | ✅ | ❌ (nothing to remove on the host) | ✅ | PASS (caught) |
| mutant `no_remove` | 13/13 | ✅ | ✅ | ✅ | ❌ | ✅ | PASS (caught) |

The first `no_place` run was marked FAIL by the runner because `remove_c2h` also failed; that is a
consequence of the mutant (the host never had the client's machine), so the expectation was widened and
the rerun at 07:00 passed. Captures show both machines on both copies after the builds.

### Results, protocol 3 (2026-10-30 05:10-05:15, private\lab-results\)

All protocol-2 checks plus four cursor checks: client cursor faked at client pixel (400, 300) reaches
the host as the same world position (`cursor_c2h`); projecting it back on the client lands within 8 px
(`cursor_projection`, measured 400,304: the world position carries no terrain height); the host's
`FLIP` detour draws it on its frames (`cursor_drawn`); the host cursor reaches the client
(`cursor_h2c`).

| Run | protocol-2 checks (9) | cursor_c2h | cursor_projection | cursor_drawn | cursor_h2c | Verdict |
|---|---|---|---|---|---|---|
| normal 05:10 | 9/9 ✅ | ✅ | ✅ | ✅ | ✅ | PASS |
| normal 05:13 | 9/9 ✅ | ✅ | ✅ | ✅ | ✅ | PASS |
| mutant `no_cursor` | 9/9 ✅ | ❌ | ✅ | ❌ | ✅ | PASS (caught) |
| mutant `nojoin` | 1/9 (no_double) | ❌ | ❌ | ❌ | ❌ | PASS (caught) |
| mutant `drop_spend` | 8/9 (client_spend ❌) | ✅ | ✅ | ✅ | ✅ | PASS (caught) |
| mutant `no_date` | 8/9 (date ❌) | ✅ | ✅ | ✅ | ✅ | PASS (caught) |

A capture of the host during the smoke test shows the yellow "Player 2" crosshair over the zoo
entrance where the client's cursor was.

### Results, protocol 2 (2026-10-30 03:23-03:29)

The host loads `maps\default.zoo`, hosts, and gets +$5000; the client joins **from the main menu**.

| Run | zoo_transfer | layout | cash_join | host_change | client_spend | no_double | date | host_pause | client_pause | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|
| normal 03:23 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | PASS |
| normal 03:25 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | PASS |
| normal 03:27 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | PASS |
| mutant `nojoin` | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ | ❌ | ❌ | ❌ | PASS (caught) |
| mutant `drop_spend` | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | PASS (caught) |
| mutant `no_date` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | PASS (caught) |

Measured: the zoo file is 111,229 bytes; both copies report `count=392` placed entities with the same
layout hash; the host's +30-day date jump shows up on the client within 3 s (host 2001-02-19 16:24,
client 16:57). An earlier normal run failed `client_pause`: a host snapshot handled in the same frame as
the client's toggle undid it before it was sent. Fixed (local toggle checked before snapshots, `on_host`
never overrides an unsent toggle), with a unit test for the race.

### Results, protocol 1 (2026-10-30 01:20, money only)

| Run | join | host_change | client_spend | no_double | Expected | Verdict |
|---|---|---|---|---|---|---|
| normal 01:20 | ✅ | ✅ | ✅ (host −777.00) | ✅ | all pass | PASS |
| mutant `nojoin` | ❌ | ❌ | ❌ (host −0) | ✅ | join/host_change fail | PASS (caught) |
| mutant `drop_spend` | ✅ | ✅ | ❌ (host −0) | ✅ | client_spend fails | PASS (caught) |
| normal 01:21 | ✅ | ✅ | ✅ (host −777.00) | ✅ | all pass | PASS |

Lab bug found and fixed on the way: openzt's console handlers busy-waited on one shared,
last-in-first-out results list. A connection the caller had given up on spun a CPU core forever and
stole the reply meant for the next command. Each request now has its own reply channel
(`command_console.rs`). Worth offering upstream.

## Not proven / known gaps

- Building is tested with one object type (Snack Machine), bought by posted clicks and sold through the
  game's sell path from Lua (the sell dialog skipped). Not tested: fences and paths (drag-placed), tank
  walls, habitats/gates, terraforming, rotation other than the default, the bulldozer with a real mouse,
  undo, and **moving** an object (picking it up and dropping it goes through `placeEntityOnMap` but not
  through `removeEntityFromMap`, so the other copy probably gets a second one instead of a move).
- Two players building on the same tile at the same moment are not reconciled (no host validation).
- Animals can't be bought outside an exhibit ("Animals can only be placed in exhibits"), and exhibits
  need drag-built fences, which are not tested; so animal adoption is not synced or tested. Firing staff
  is not synced (staff aren't in the removal set). Hired staff and animals walk independently on
  each copy.
- The admission price is changed in the lab through the setter, not by clicking the price panel.
- Cursors are only tested with the lab's faked position, never a real mouse, and with both copies
  looking at the same spot (same camera after join); a different camera/zoom/rotation on the two sides
  is untested. The cursor is a world point at ground level (z=0), so on raised terrain it can sit a few
  pixels low. The drawing uses GDI on the back buffer in windowed mode; fullscreen is untested.
  Guests, animals and staff are simulated separately on each copy from the join snapshot on.
- Joining while the client is already inside a zoo is untested (only from the main menu); that path
  skips the in-game load handler's extra UI resets. A second join replaces the first client.
- In-game month names show as garbled text (e.g. "ėðå, Year 1") in the lab copies, with or without
  co-op; probably a language-DLL/encoding mismatch in this install or in openzt's string handling. Not
  investigated.
- The client's own sim still runs. Its income is overwritten by the next snapshot, but any *vanilla*
  `subtractCash` it makes for sim reasons (if any exist: salaries/upkeep may go through Rust ZooStatus
  instead) would be forwarded to the host as a spend. Needs a caller audit.
- Refunds: when the client sells, the host's replay refunds the host, which is what counts; other
  client-side `addCash` calls are not forwarded.
- The lab spends through the vanilla `subtractCash` entry point from Lua and pauses through the same
  functions the pause button uses, not through real mouse clicks.
- One client per host. No reconnect, no host migration, no relay, no in-game UI.
- Not tested on two PCs, over the internet, or under lag/loss (the hub's chaos proxy can do this next).
