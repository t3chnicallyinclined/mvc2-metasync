# MetaSync — Linux / Bazzite full-parity port (workstream)

**Goal:** a double-clickable **Linux x86_64 AppImage** of MetaSync with **full parity** — tournaments/leaderboards/profiles (already cross-platform) **and** the skin engine + live match detection working on **Bazzite via Proton**. Direct, simple port — no architecture rewrite.

**Hard rule:** the shipped **Windows build must stay green** at every step (it's live for real users at 0.1.75). All Linux code is additive + `cfg`-gated; no Windows behavior changes.

**Why this is a port, not a recompile:** `src-tauri/src/sync.rs` reads/writes the game's process memory through the Windows API (`OpenProcess`/`ReadProcessMemory`/`WriteProcessMemory`/`VirtualQueryEx`/Toolhelp), and the `windows` crate is an **unconditional dependency** with ~7 ungated `windows::Win32` imports threaded through ~40 functions via a `HANDLE`. Linux has no `HANDLE`; it uses `/proc/<pid>/mem` + `/proc/<pid>/maps` + `process_vm_readv/writev`.

**What we already proved (on the Beelink, Bazzite, in Python):** memory reading works 1:1 under Proton — `exe_base = 0x140000000` (Wine maps the PE at its preferred base; **no ASLR** under Proton, MZ magic at base), read via `/proc/<pid>/mem`, regions via `/proc/<pid>/maps`, `ptrace_scope=0` set so a same-user process can read/write another process's memory. Offsets are identical to Windows (same game). See `docs/DISTRIBUTED-TOURNAMENT-SPECTATOR-TAPE.md`.

---

## Stage 1 — cross-platform memory abstraction (owner: memory-port agent)

Introduce a thin `Proc` handle + primitive ops; keep every existing algorithm (sig scan, palette read/write, lobby read, match detection) **byte-identical** — only the primitives change.

**New file `src-tauri/src/mem.rs`** — one public surface, two `cfg` impls:
```
pub struct Proc { /* win: HANDLE ; linux: pid + mem File/fd */ }
pub struct Region { pub base: usize, pub size: usize, pub readable: bool, pub writable: bool }
impl Proc {
    pub fn open_read(pid: u32) -> Option<Proc>;    // win: OpenProcess(VM_READ|QUERY) ; linux: open /proc/pid/mem O_RDONLY
    pub fn open_rw(pid: u32) -> Option<Proc>;       // win: + VM_WRITE|VM_OPERATION ; linux: O_RDWR (or process_vm_writev, no fd)
    pub fn read(&self, addr: usize, len: usize) -> Option<Vec<u8>>;   // win: ReadProcessMemory ; linux: process_vm_readv (fallback pread /proc/pid/mem)
    pub fn write(&self, addr: usize, buf: &[u8]) -> bool;             // win: WriteProcessMemory ; linux: process_vm_writev (fallback pwrite)
    pub fn region_at(&self, addr: usize) -> Option<Region>;           // win: VirtualQueryEx→MBI ; linux: lookup in a cached /proc/pid/maps parse
    pub fn regions(&self) -> &[Region];                               // linux: parsed once from /proc/pid/maps; win: lazily walked
}
pub fn find_game_pid() -> Option<u32>;   // win: Toolhelp Process32 ; linux: scan /proc/*/cmdline for the MvC2 exe basename (Proton child)
pub fn exe_base(pid: u32) -> usize;      // win: Toolhelp module base ; linux: first r-xp mapping of the exe in /proc/pid/maps (expect 0x140000000)
```
- **Linux reads:** `process_vm_readv` (libc) — no seek races, fast; fall back to `pread` on `/proc/<pid>/mem` if `ENOSYS`.
- **Linux writes (skin injection):** `process_vm_writev` (libc). With `ptrace_scope=0` + same uid this needs **no explicit ptrace attach**. Fall back to `pwrite` on `/proc/<pid>/mem` opened `O_RDWR`.
- **Linux regions:** parse `/proc/<pid>/maps` once per `Proc` (lines `start-end perms off dev inode path`; `readable = perms[0]=='r'`, `writable = perms[1]=='w'`). This replaces every `VirtualQueryEx` committed-region walk — the walk loops become `for r in proc.regions()`.
- **Linux find_pid:** scan `/proc/*/cmdline` (NUL-separated) for the game exe basename (the Windows `.exe` Proton launches) and/or appid `2634890`; skip the Proton/wine helper processes. Return the pid whose maps contain the PE at `0x140000000`.

**`Cargo.toml`:** make `windows` target-conditional and add `libc` for unix:
```
[target.'cfg(windows)'.dependencies]
windows = { version = "0.58", features = [ ...unchanged... ] }
[target.'cfg(unix)'.dependencies]
libc = "0.2"
```

**Refactor `sync.rs` (mechanical):** replace `HANDLE` params with `&Proc`; `ReadProcessMemory(...)`→`proc.read(...)`; `WriteProcessMemory(...)`→`proc.write(...)`; the `VirtualQueryEx` MBI walks →`proc.regions()`; `OpenProcess(...)`→`Proc::open_read/open_rw`; `find_game_pid`/module-base →`mem::`. Keep all offsets, sig tables, and logic identical. Gate any residual Windows-only bits with `#[cfg(windows)]` and provide the Linux equivalent.

**Exit:** `cargo build` on **Windows** still succeeds unchanged; `cargo build --target x86_64-unknown-linux-gnu` (on the Beelink, Stage 2 env) compiles.

## Stage 2 — Bazzite build environment (owner: build-env agent, on the Beelink)

Bazzite is Fedora Atomic (immutable) → build inside a **distrobox** container (matches host libs, has webkit2gtk 4.1).
```
distrobox create --image registry.fedoraproject.org/fedora:40 --name tauri
distrobox enter tauri
sudo dnf install -y webkit2gtk4.1-devel gtk3-devel libsoup3-devel openssl-devel \
     libappindicator-gtk3-devel librsvg2-devel patchelf file @development-tools curl wget
# rust (rustup) + node (already?) + tauri-cli
curl https://sh.rustup.rs -sSf | sh -s -- -y ; cargo install tauri-cli --version '^2'
```
- **Bundle targets:** `src-tauri/tauri.conf.json` `bundle.targets` is `["msi","nsis"]` (Windows-only). Set it to **`"all"`** (Tauri builds only the targets valid for the current OS — msi/nsis on Windows, deb/rpm/appimage on Linux), OR keep a Linux override. Confirm AppImage is produced.
- **Prove the env** with a throwaway `create-tauri-app` build to AppImage before the real app lands.
- **Exit:** the container builds *some* Tauri app to a runnable `.AppImage`; exact `cargo tauri build` command documented.

### ✅ Stage 2 DONE + PROVEN (2026-08-16) — exact recipe
Container `tauri` = `registry.fedoraproject.org/fedora:40` on the Beelink; produced a runnable `throwaway_0.1.0_amd64.AppImage` (99.8MB, launches under Xvfb). Versions: cargo-tauri 2.11.4, rustc 1.97.1, node v20.19.1, webkit2gtk-4.1 2.48.1.
```bash
distrobox create --image registry.fedoraproject.org/fedora:40 --name tauri --yes
distrobox enter tauri
# ⚠ TWO ADDITIONS to the dnf list above: `xdg-utils` (else AppImage bundling fails — tauri-plugin-opener embeds xdg-open) + nodejs/npm (for MetaSync's beforeBuildCommand stage-frontend.mjs):
sudo dnf install -y webkit2gtk4.1-devel gtk3-devel libsoup3-devel openssl-devel \
     libappindicator-gtk3-devel librsvg2-devel patchelf file @development-tools curl wget nodejs npm xdg-utils
curl --proto =https --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --default-toolchain stable --profile minimal
source $HOME/.cargo/env ; cargo install tauri-cli --version '^2' --locked
# ⚠ BUILD COMMAND: APPIMAGE_EXTRACT_AND_RUN=1 is REQUIRED in a container (linuxdeploy/appimagetool are FUSE AppImages; no fuse-libs):
APPIMAGE_EXTRACT_AND_RUN=1 cargo tauri build
```
AppImage output: `src-tauri/target/release/bundle/appimage/<name>_amd64.AppImage`. `bundle.targets:"all"` yields deb+rpm+appimage on Linux (msi/nsis on Windows).

## Stage 3 — build + verify the real app (integration)
- Sync the Stage-1 source to the Beelink; `cargo tauri build` in the distrobox → `MetaSync_x.y.z_amd64.AppImage`.
- Run it on Bazzite; verify **tournaments/leaderboards/profiles** (network) AND **skins + live detection** against a running MvC2 under Proton (needs `ptrace_scope=0`, already set; document `sudo sysctl kernel.yama.ptrace_scope=0` if a fresh box).
- Confirm `exe_base=0x140000000`, roster/side/lobby reads match the Windows behavior using the proven offsets.

## Stage 4 — release (after verification)
- Reuse the minisign key; add a **`linux-x86_64`** platform entry to `latest.json` (updater), or ship the AppImage as a direct download first for testing.
- `gh release` the AppImage asset.

## Gotchas
- **Never break Windows** — verify `cargo build` on Windows after Stage 1.
- **Writes need ptrace perms** — `process_vm_writev` requires same-uid + `ptrace_scope=0` (Beelink OK); document for other machines.
- **Proton pid discovery** — match the game exe in `/proc/*/cmdline`, not `comm` (truncated); the real target is the mapping at `0x140000000`.
- **webkit2gtk 4.1** (not 4.0) for Tauri v2 — Fedora 40 distrobox has it; Ubuntu needs 24.04.
- **AppImage + immutable host** — AppImage is self-contained; no install needed on Bazzite.
- **`NO_STRIP=1`** is required alongside `APPIMAGE_EXTRACT_AND_RUN=1` or `linuxdeploy` fails to bundle the AppImage in a container.
- **⚠ MATCH THE HOST DISTRO VERSION.** Building in Fedora **40** for a Bazzite **44** host produced a runnable AppImage that opened a BLANK window then aborted: `undefined symbol: g_variant_builder_init_static` (host F44 GTK/gvfs modules need a newer glib than the bundled F40 one) + `could not create default egl display: EGL_BAD_PARAMETER` (bundled Mesa/EGL vs host GPU stack). FIX: build in a **Fedora 44** distrobox (`registry.fedoraproject.org/fedora:44`) so bundled libs match the host. cargo/rustup/tauri-cli live in the shared `$HOME/.cargo` so a new distrobox only needs the `dnf` system deps. Do a `cargo clean` before rebuilding so the binary is relinked against the matched libs.
- **The app MUST run on the host, NOT in a container** — it reads the game's `/proc` memory, and the game (Steam/Proton) runs on the host; a container's separate PID namespace can't see host process memory. So the AppImage-on-host path is required (can't sidestep via distrobox-export).
- **In-app WebKit fix** — the app sets `WEBKIT_DISABLE_DMABUF_RENDERER=1` on Linux at startup (keeps GPU compositing; standard Tauri-Linux blank/crash fix).
