# AGENTS.md — how to work on ZooTogether

Read this before changing anything. [handoff.md](handoff.md) has the plan, the protocol, lab results
and what is not proven yet.

## Coding guidelines (Karpathy guidelines)

From [Andrej Karpathy's notes on LLM coding pitfalls](https://x.com/karpathy/status/2015883857489522876).
They favour caution over speed; for trivial changes, use judgement.

1. **Think before coding.** State assumptions. If there are several readings of a request or several
   ways to hook the game, name them and pick one with a reason; don't choose silently. If something
   is unclear (an address, a calling convention, what a field means), say so and check it in the
   disassembly or the live game before building on it.
2. **Simplicity first.** Write the least code that solves the asked problem. No features, options or
   abstractions nobody asked for; no error handling for cases that can't happen. If 200 lines could
   be 50, rewrite them.
3. **Surgical changes.** Touch only what the task needs. In openzt (`vendor/openzt`) especially: put
   ZooTogether code in `coop.rs` and add the smallest possible call-outs elsewhere; don't reformat,
   rename or "improve" openzt code. Remove only what your own change made unused; mention other dead
   code instead of deleting it.
4. **Goal-driven execution.** Turn each task into a check that can fail, then loop until it passes:
   a unit test for pure logic (wire format, ledgers, ordering), a `lab_coop.py` check for anything
   in the game, and a mutant (`ZT_COOP_MUTANT=...`) that proves the check catches the bug. For
   multi-step work, write the plan as "step → how it's verified" first.

## Project rules

- **Host-authoritative.** The host's game is the only real one. Clients send intents with a sequence
  number; the host applies them and acks them in `State`. Clients never change shared state directly
  without a pending intent the host will confirm or overwrite.
- **Game memory only on the game thread** (`coop::tick`, detours, Lua commands). Network threads only
  move bytes. Never block on the session lock from a detour (`try_lock`; see `on_vanilla_subtract_cash`).
- **Don't hand-edit `openzt-detour/src/generated.rs`.** If an entry is wrong, note the address and
  evidence in handoff.md. Never add a second detour on an address openzt already detours (e.g.
  `PLACE_ENTITY_ON_MAP_1` belongs to `roofs.rs`); call into coop from inside the existing one.
- **Protocol changes** bump `PROTOCOL_VERSION` and get a round-trip unit test.
- **Every claim in handoff.md is measured** (lab JSON in `private/lab-results/`), or listed under
  "Not proven".

## Build, test, lab

- `scripts\get-openzt.ps1` once, then `scripts\build.cmd` (VS x86 env; see handoff "Build" for the two
  LuaJIT traps). Unit tests: `cargo test --manifest-path openzt/Cargo.toml --lib
  --target=i686-pc-windows-msvc --features coop coop::` inside the same environment.
- Lab: `scripts\setup-lab.ps1`, copy the new DLL to `private\lab-*\res-openzt.dll`, then
  `python scripts\lab_coop.py` plus each `--mutant`. One lab at a time across all sessions on this PC.
  Copies run parked off-screen at below-normal priority; **never minimize them** (Zoo Tycoon's loop
  stops when minimized).
- Commit locally. Push to multiplayereverything/zoo-tycoon-coop or publish releases only when the user
  says so. Credit openzt; this repo is GPL-3.0.
