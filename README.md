# Zoo Tycoon co-op (ZooTogether)

Co-op for **Zoo Tycoon (2001)**: two players share one zoo budget. One player hosts, the other joins by IP.

**Status: 0.1.0-dev, early prototype.** Only the budget is shared so far: purchases on either side
come out of the host's money, and both players see the same number. Animals, buildings, guests and
the date are not synced yet. See [handoff.md](handoff.md) for the plan, what is proven and what isn't.

## How it works

- Built on **[openzt](https://github.com/openzt1/openzt)** by the openzt authors, a Rust DLL the
  game loads as `res-openzt.dll`. This repo carries a patch on openzt (`patches/`), not a copy of it.
- Host-authoritative: the host's game is the real one. The host sends its budget 5 times a second;
  money the client spends is sent to the host as a request and applied there.
- Network: direct TCP, port **27150** (LAN, or forward the port / use a VPN such as Tailscale over
  the internet). The game has no Steamworks.

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

Set an environment variable before starting `zoo.exe`, then load the same zoo on both PCs:

- host: `ZT_COOP_HOST=27150`
- client: `ZT_COOP_JOIN=<host ip>`

Or use openzt's Lua console (`127.0.0.1:8080`): `coop_host()`, `coop_join("ip")`, `coop_status()`.

## Testing

`scripts/setup-lab.ps1` makes two hardlinked copies of the game, and `python scripts/lab_money.py`
runs them side by side and checks that the budget stays in sync (plus `--mutant nojoin` and
`--mutant drop_spend`, which must fail).

## Credits and license

- [openzt](https://github.com/openzt1/openzt) by the openzt contributors. Its repo ships a GPL-3.0
  `LICENSE` file (its Cargo metadata and README say MIT / Apache-2.0); to respect all of them this
  repo, including our patch to openzt, is released under **GPL-3.0**, see [LICENSE](LICENSE).
- Zoo Tycoon is a trademark of Microsoft. No game files are included; you need your own copy.
