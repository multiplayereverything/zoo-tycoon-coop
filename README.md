# Zoo Tycoon co-op (ZooTogether)

Co-op for **Zoo Tycoon (2001)**: one player hosts a zoo, a friend joins by IP and gets the same zoo, budget, date and pause, and each player sees the other's cursor.

**Status: 0.3.0-dev, early prototype.** When a friend joins, they receive the host's zoo. After that
the budget (purchases on either side come out of the host's money), the date and pause stay shared,
and each player's map cursor shows on the other's screen.
Building after joining, animals, staff and guests are not synced yet. See [handoff.md](handoff.md) for the plan, what is proven and what isn't.

## How it works

- Built on **[openzt](https://github.com/openzt1/openzt)** by the openzt authors, a Rust DLL the
  game loads as `res-openzt.dll`. This repo carries a patch on openzt (`patches/`), not a copy of it.
- Host-authoritative: the host's game is the real one. On join the host saves its zoo and sends the
  file; then it sends budget, date and pause 5 times a second. Money the client spends and the client's
  pause button are sent to the host as requests and applied there.
- Network: direct TCP, port **27150** (LAN, or forward the port / use a VPN such as Tailscale over
  the internet). The game has no Steamworks.

How to work on this repo (people and AI agents): [AGENTS.md](AGENTS.md).

## Build

Needs Windows, Visual Studio 2022 Build Tools (C++ x86) and Rust (rustup; the toolchain is pinned by openzt).

```bash
powershell -ExecutionPolicy Bypass -File scripts/get-openzt.ps1
```

```bash
scripts\build.cmd
```

The DLL lands in `vendor\openzt\target\i686-pc-windows-msvc\release\openzt.dll`. Copy it into your
Zoo Tycoon folder as `res-openzt.dll`.

## Play (prototype)

Set an environment variable before starting `zoo.exe`. The host loads a zoo; the client stays on the
main menu and enters the host's zoo when it connects:

- host: `ZT_COOP_HOST=27150`
- client: `ZT_COOP_JOIN=<host ip>`

Or use openzt's Lua console (`127.0.0.1:8080`): `coop_host()`, `coop_join("ip")`, `coop_status()`.

## Testing

`scripts/setup-lab.ps1` makes two hardlinked copies of the game, and `python scripts/lab_coop.py`
runs them side by side: the client joins, receives the zoo, and the budget, date and pause are checked
both ways, and each player's cursor must reach and be drawn on the other side (plus the
`nojoin`, `drop_spend`, `no_date` and `no_cursor` mutants, which must fail).

## Credits and license

- [openzt](https://github.com/openzt1/openzt) by the openzt contributors. Its repo ships a GPL-3.0
  `LICENSE` file (its Cargo metadata and README say MIT / Apache-2.0); to respect all of them this
  repo, including our patch to openzt, is released under **GPL-3.0**, see [LICENSE](LICENSE).
- Zoo Tycoon is a trademark of Microsoft. No game files are included; you need your own copy.
