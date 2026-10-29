# ZooTogether — Zoo Tycoon (2001) co-op: plan and hand-off

Status: **first vertical slice (shared budget) works in a two-copy lab** (see "Lab"), version
0.1.0-dev. Repo: https://github.com/multiplayereverything/zoo-tycoon-coop (no release yet). Built on [openzt](https://github.com/openzt1/openzt) (by the openzt authors; LICENSE file GPL-3.0, Cargo metadata MIT/Apache-2.0, so this repo is GPL-3.0), a Rust DLL
that the game loads as `res-openzt.dll` and that detours game functions at fixed addresses.

## Layout

```
Zoo Tycoon\                      the game install (Complete Collection, zoo.exe 1.0 build 12.4.0.9)
Zoo Tycoon\ZooTogether\          this repo (the game never scans it)
  handoff.md                     this file
  scripts\build.cmd              builds res-openzt.dll with the coop feature (VS x86 env)
  scripts\setup-lab.ps1          makes private\lab-host + private\lab-client (hardlinked copies)
  scripts\zt_launch.py           starts a copy suspended, lifts the one-instance check, parks it off-screen
  scripts\lab_money.py           the two-copy money lab (+ mutants)
  scripts\get-openzt.ps1         clones openzt at df01b96 and applies the patch into vendor\openzt
  patches\openzt-zoo-together.patch   our changes to openzt, as a patch on upstream df01b96
  vendor\openzt\                 openzt checkout, branch zoo-together (its own git repo, ignored here)
  private\                       lab copies and results (ignored)
```

## Game identity

- zoo.exe SHA-256 `9cec15e08b8c0bac1a7418422452ffb22e6d98f397fb8c4e69ec13faa05a43ef`, 2,440,327 bytes,
  PE32 x86, FileVersion 12.4.0.9, PE header at offset 12 (REA can't open it; plain PE parsing works).
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
- Detour framework with a generated table of ~thousands of vanilla function addresses
  (`openzt-detour/src/generated.rs`), plus Rust reimplementations of whole managers.
- **`ZTGameMgr` fully ported to Rust** (`ztgamemgr.rs`): cash, date, add/subtractCash detoured, save/load.
  This is why money was the easiest first sync target.
- Lua console on TCP (default 127.0.0.1:8080, set per copy in `openzt.toml [dev] console_listen`),
  run on the game thread from the `ZTApp::updateSim` detour. Our lab drives the game through it.
- World/entity readers (`ztworldmgr.rs`: entity lists, types, positions), habitats, research,
  marketing, guests (partial), UI helpers, save/load primitives (`ztui_gameopts::LOAD_FILE`).

Missing for multiplayer (what we have to add):
- Networking of any kind (added: `coop.rs`).
- A clean "entity placed / removed" event and a way to place an entity of a given type at a tile
  from code. openzt can *list* entities but has no create-by-type API yet. This is the next big RE job.
- Determinism: the sim uses its own RNG and timing; we will not try lockstep (see authority model).
- In-game UI for host/join (today: env vars or console commands).
- openzt is still WIP upstream (many managers reimplemented, but BFEntity, scripting manager etc. are
  open issues), so we pin to upstream df01b96 and rebase deliberately.

## Authority model

**Host-authoritative, state-sync (not lockstep).** The host runs the only real simulation. Clients
send *intents* (spend, place object, delete, set admission price...) and receive *state*
(budget, date, entity add/remove/move, guests later). Reasons: Zoo Tycoon's sim is not designed to be
deterministic across machines, and a zoo has thousands of guests, which we can stream coarsely or
let each client simulate cosmetically.

Planned phases:
1. **Shared budget** (done in this slice): host streams cash at 5 Hz; client purchases through vanilla
   `subtractCash` become `Spend{seq}` intents; host acks by seq; client shows host cash minus unacked
   spends (no flicker).
2. Shared date/speed/pause; client sim paused or slaved so it stops generating its own income.
3. Object placement: hook the vanilla "place entity" path on the client → `Place{type, tile, rot}`
   intent → host places → host broadcasts `EntityAdded{id,type,pos}`; same for delete/sell. Needs RE of
   `ZTWorldMgr`/`BFMap` placement calls (openzt's generated table has candidates).
4. Join-in-progress: host saves to memory (openzt has `io_redirect` capture for save bytes) and streams
   the .zoo to the client, client loads it via `LOAD_FILE`. That gives both copies the same zoo.
5. Animals/staff/guests positions (interest-managed, low rate), exhibits, research, awards.

## Networking

- No Steamworks in this build → **direct IP / LAN TCP**, default port **27150**. Host: `coop_host()`,
  client: `coop_join("ip[:port]")`, or set `ZT_COOP_HOST=<port>` / `ZT_COOP_JOIN=<ip[:port]>` before
  launching. Over the internet the host must forward TCP 27150, or both use a VPN (Tailscale/ZeroTier).
- Next: global mod relay (tunnel mode) so friends can join by room code without port forwarding.
- Frames: `u32 len | u8 type | payload`, protocol 1: Hello, CashState{seq,cash,acked_spend},
  Spend{seq,amount}, Keepalive (writer thread, 1 s; read timeout 30 s, per Baldi's link-health lesson).

## Our changes to openzt (branch `zoo-together`)

- `openzt/src/coop.rs` (new, feature `coop`): session, wire format, ledgers, Lua commands
  (`coop_host/join/stop/status/cash`, lab helpers `coop_test_spend`, `coop_load_zoo`), unit tests.
- `ztgamemgr.rs`: `set_cash_and_refresh`; the vanilla `subtractCash` detour reports spends to coop.
- `command_console.rs`: `coop::tick()` each frame in the existing `ZTApp::updateSim` detour.
- `logging.rs`: `OPENZT_NO_CONSOLE=1` skips `AllocConsole` (hidden lab copies).
- `command_console.rs`: per-request reply channel, FIFO queue (fixes the busy-spin/stolen-reply bug).
- Cargo features: `coop` in `openzt` and `openzt-dll`.

## Build

`scripts\build.cmd` (needs VS 2022 Build Tools with x86, Rust from `rust-toolchain.toml`). Two traps:
LuaJIT's msvcbuild needs **x86** `cl` on PATH (vcvars32), and fails with "'minilua' is not recognized"
when `NoDefaultCurrentDirectoryInExePath` is set (Claude Code sets it). The script handles both.
Output: `vendor\openzt\target\i686-pc-windows-msvc\release\openzt.dll` → copy as `res-openzt.dll`.

## Lab

- `scripts\setup-lab.ps1` then `python scripts\lab_money.py` (and `--mutant nojoin`,
  `--mutant drop_spend`). Copies run below-normal priority, windowed 800x600 (the game's minimum
  mode; 640x360 isn't available), no intro movies, no openzt console window, **parked off-screen at
  (-4000,-4000) without focus, not minimized**: a minimized Zoo Tycoon window stops its whole game
  loop (no `updateSim`, so the console and the co-op tick freeze; loads hang). Measured 2026-10-30.
- **One instance check**: zoo.exe's function at 0x5337e6 does `FindWindowA(appClass)` and refuses to
  start if another Zoo Tycoon window exists. `zt_launch.py` starts the copy suspended and patches that
  function to `xor eax,eax; ret` in memory only. Real players run one copy per PC and don't need it.

### Results (2026-10-30, private\lab-results\)

| Run | join | host_change | client_spend | no_double | Expected | Verdict |
|---|---|---|---|---|---|---|
| normal 01:20 | ✅ | ✅ | ✅ (host −777.00) | ✅ | all pass | PASS |
| mutant `nojoin` | ❌ | ❌ | ❌ (host −0) | ✅ | join/host_change fail | PASS (caught) |
| mutant `drop_spend` | ✅ | ✅ | ❌ (host −0) | ✅ | client_spend fails | PASS (caught) |
| normal 01:21 | ✅ | ✅ | ✅ (host −777.00) | ✅ | all pass | PASS |

Before join the copies had $51,728.75 (host, +5000 test cash) and $46,728.75 (client); after join both
showed the host value within one 200 ms snapshot. Final status lines: host `snapshots_sent=26
spends_applied=1`, client `snapshots_applied=28 spends_sent=1 pending=0`.

Lab bug found and fixed on the way: openzt's console handlers busy-waited on one shared,
last-in-first-out results list. A connection the caller had given up on spun a CPU core forever and
stole the reply meant for the next command. Each request now has its own reply channel
(`command_console.rs`). Worth offering upstream.

## Not proven / known gaps

- After `coop_load_zoo` the in-game date did not advance in the lab (sim paused or still on the menu
  screen behind the loaded zoo). Money sync doesn't depend on it, but phase 2 needs a real running
  zoo in both copies: find the "enter game screen / unpause" call (`ztui_main::UNPAUSE_GAME` exists).
- Only money is synced. The two zoos are otherwise independent (both load the same map, nothing
  else is mirrored).
- The client's own sim still runs. Its income is overwritten by the next snapshot, but any *vanilla*
  `subtractCash` it makes for sim reasons (if any exist: salaries/upkeep may go through Rust ZooStatus
  instead) would be forwarded to the host as a spend. Needs a caller audit or phase 2 (slaved sim).
- `addCash` refunds on the client (selling objects) are not forwarded yet.
- The lab spends through the vanilla `subtractCash` entry point from Lua, not through a real mouse
  purchase in the build menu.
- One client per host. No reconnect, no host migration, no relay, no in-game UI.
- Not tested on two PCs, over the internet, or under lag/loss (the hub's chaos proxy can do this next).
