// Cross-platform process-memory layer for the MvC2 skin engine + live detection.
//
// This is the ONE place that touches the OS's read/write-another-process APIs. Everything in sync.rs
// (sig scan, palette read/write, lobby read, match detection) is expressed against the platform-neutral
// `Proc` handle + `Region` view below, so the exact same RE logic + offsets run on:
//   • Windows  — the shipped app: OpenProcess / ReadProcessMemory / WriteProcessMemory / VirtualQueryEx /
//                Toolhelp (behaviour byte-for-byte identical to the original inline calls).
//   • Linux    — the game under Proton/Wine (same Windows PE, same offsets, exe_base = 0x140000000, no ASLR):
//                process_vm_readv / process_vm_writev (fallback pread/pwrite on /proc/<pid>/mem) +
//                /proc/<pid>/maps for regions + /proc/*/cmdline to find the game pid.
//
// Ground truth for the Linux backend: docs/DISTRIBUTED-TOURNAMENT-SPECTATOR-TAPE.md (live-validated on the
// Beelink / Bazzite TO node; ptrace_scope=0 lets a same-user process read/write without an explicit attach).

/// A committed memory region. `readable`/`writable` map to the OS view:
///   • Windows: computed from MEMORY_BASIC_INFORMATION (State/Protect/Type) — see `mbi_to_region`.
///   • Linux:   the perms column of /proc/<pid>/maps ("rwxp").
/// `executable`/`private` are exposed too so sync.rs can reproduce the two special Windows region
/// predicates EXACTLY (flycast reservation = a committed PRIVATE PAGE_READWRITE block; the read_my_lobby
/// heap sweep = committed PRIVATE readable pages) without leaking any platform-specific protection bits.
#[derive(Clone, Copy, Debug)]
pub struct Region {
    pub base: usize,
    pub size: usize,
    pub readable: bool,
    pub writable: bool,
    pub executable: bool,
    pub private: bool,
}

// ════════════════════════════════════════════════════════════════════════════════════════════════════
// Windows backend — wraps the EXACT calls sync.rs used before, so nothing about the shipped app changes.
// ════════════════════════════════════════════════════════════════════════════════════════════════════
#[cfg(windows)]
mod platform {
    use super::Region;
    use std::ffi::c_void;
    use windows::Win32::Foundation::{CloseHandle, FALSE, HANDLE};
    use windows::Win32::System::Threading::{
        OpenProcess, PROCESS_QUERY_INFORMATION, PROCESS_VM_OPERATION, PROCESS_VM_READ, PROCESS_VM_WRITE,
    };
    use windows::Win32::System::Memory::{
        VirtualQueryEx, MEMORY_BASIC_INFORMATION, MEM_COMMIT, MEM_PRIVATE, PAGE_GUARD, PAGE_NOACCESS,
    };
    use windows::Win32::System::Diagnostics::Debug::{ReadProcessMemory, WriteProcessMemory};
    use windows::Win32::System::Diagnostics::ToolHelp::{
        CreateToolhelp32Snapshot, Module32FirstW, Process32FirstW, Process32NextW, MODULEENTRY32W,
        PROCESSENTRY32W, TH32CS_SNAPMODULE, TH32CS_SNAPPROCESS,
    };

    /// Owns the process HANDLE and closes it on drop (replaces the scattered explicit `CloseHandle` calls).
    pub struct Proc {
        handle: HANDLE,
    }

    impl Drop for Proc {
        fn drop(&mut self) {
            unsafe {
                let _ = CloseHandle(self.handle);
            }
        }
    }

    impl Proc {
        /// VM_READ | QUERY — exactly the access the read-only paths used.
        pub fn open_read(pid: u32) -> Option<Proc> {
            unsafe {
                OpenProcess(PROCESS_VM_READ | PROCESS_QUERY_INFORMATION, FALSE, pid)
                    .ok()
                    .map(|handle| Proc { handle })
            }
        }

        /// + VM_WRITE | VM_OPERATION — exactly the access the paint (write) paths used.
        pub fn open_rw(pid: u32) -> Option<Proc> {
            unsafe {
                OpenProcess(
                    PROCESS_VM_READ | PROCESS_VM_WRITE | PROCESS_VM_OPERATION | PROCESS_QUERY_INFORMATION,
                    FALSE,
                    pid,
                )
                .ok()
                .map(|handle| Proc { handle })
            }
        }

        /// ReadProcessMemory — mirrors the old `read_at`: partial reads are truncated to the bytes actually
        /// read; Some only when >0 bytes came back and the call succeeded, else None.
        pub fn read(&self, addr: usize, len: usize) -> Option<Vec<u8>> {
            let mut buf = vec![0u8; len];
            let mut read: usize = 0;
            if unsafe {
                ReadProcessMemory(
                    self.handle,
                    addr as *const c_void,
                    buf.as_mut_ptr() as *mut c_void,
                    len,
                    Some(&mut read),
                )
            }
            .is_ok()
                && read > 0
            {
                buf.truncate(read);
                Some(buf)
            } else {
                None
            }
        }

        /// WriteProcessMemory — true iff the FULL buffer was written (the old sites all checked `w == 32`).
        pub fn write(&self, addr: usize, buf: &[u8]) -> bool {
            let mut w: usize = 0;
            let ok = unsafe {
                WriteProcessMemory(
                    self.handle,
                    addr as *const c_void,
                    buf.as_ptr() as *const c_void,
                    buf.len(),
                    Some(&mut w),
                )
            }
            .is_ok();
            ok && w == buf.len()
        }

        /// VirtualQueryEx on a single address → the region containing it. None when the query fails or the
        /// region is zero-sized (matches the old `!= 0 && RegionSize != 0` guards in finish_opp / hunt).
        pub fn region_at(&self, addr: usize) -> Option<Region> {
            let mut mbi = MEMORY_BASIC_INFORMATION::default();
            let got = unsafe {
                VirtualQueryEx(
                    self.handle,
                    Some(addr as *const c_void),
                    &mut mbi,
                    std::mem::size_of::<MEMORY_BASIC_INFORMATION>(),
                )
            };
            if got == 0 || mbi.RegionSize == 0 {
                return None;
            }
            Some(mbi_to_region(&mbi))
        }

        /// Walk the whole address space via VirtualQueryEx — the same forward committed-region walk the old
        /// loops did, returned as a fresh Vec each call (the reader reuses one Proc across cycles, so a
        /// re-walk every call preserves the original's always-fresh view of a changing memory map).
        pub fn regions(&self) -> Vec<Region> {
            let mut out = Vec::new();
            let mut addr = 0usize;
            loop {
                let mut mbi = MEMORY_BASIC_INFORMATION::default();
                if unsafe {
                    VirtualQueryEx(
                        self.handle,
                        Some(addr as *const c_void),
                        &mut mbi,
                        std::mem::size_of::<MEMORY_BASIC_INFORMATION>(),
                    )
                } == 0
                {
                    break;
                }
                let base = mbi.BaseAddress as usize;
                let size = mbi.RegionSize;
                if size == 0 {
                    break;
                }
                out.push(mbi_to_region(&mbi));
                let nx = base + size;
                if nx <= base {
                    break;
                }
                addr = nx;
            }
            out
        }
    }

    // Protection-bit masks (matches the original inline predicates exactly):
    //   readable   : committed, not guard/no-access, any of READONLY|READWRITE|WRITECOPY|EXEC_READ|EXEC_RW|EXEC_WC
    //   writable   : + any of READWRITE|WRITECOPY|EXEC_RW|EXEC_WC
    //   executable : + any of EXECUTE|EXEC_READ|EXEC_RW|EXEC_WC
    // 0xEE was the exact "readable" mask the old walks used (`prot & 0xEE != 0`).
    fn mbi_to_region(mbi: &MEMORY_BASIC_INFORMATION) -> Region {
        let prot = mbi.Protect.0;
        let gate =
            mbi.State == MEM_COMMIT && (prot & PAGE_GUARD.0) == 0 && (prot & PAGE_NOACCESS.0) == 0;
        Region {
            base: mbi.BaseAddress as usize,
            size: mbi.RegionSize,
            readable: gate && (prot & 0xEE) != 0,
            writable: gate && (prot & 0xCC) != 0,
            executable: gate && (prot & 0xF0) != 0,
            private: mbi.Type == MEM_PRIVATE,
        }
    }

    /// Toolhelp process walk — the game exe basename starts with "MarvelVsCapcom" (unchanged from the old
    /// `find_game_pid`).
    pub fn find_game_pid() -> Option<u32> {
        unsafe {
            let snap = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0).ok()?;
            let mut pe = PROCESSENTRY32W {
                dwSize: std::mem::size_of::<PROCESSENTRY32W>() as u32,
                ..Default::default()
            };
            let mut pid = None;
            if Process32FirstW(snap, &mut pe).is_ok() {
                loop {
                    let end = pe
                        .szExeFile
                        .iter()
                        .position(|&c| c == 0)
                        .unwrap_or(pe.szExeFile.len());
                    let name = String::from_utf16_lossy(&pe.szExeFile[..end]);
                    if name.starts_with("MarvelVsCapcom") {
                        pid = Some(pe.th32ProcessID);
                        break;
                    }
                    if Process32NextW(snap, &mut pe).is_err() {
                        break;
                    }
                }
            }
            let _ = CloseHandle(snap);
            pid
        }
    }

    /// Toolhelp module base — the game module's load address (unchanged from the old `game_exe_base`).
    pub fn exe_base(pid: u32) -> usize {
        unsafe {
            let snap = match CreateToolhelp32Snapshot(TH32CS_SNAPMODULE, pid) {
                Ok(s) => s,
                Err(_) => return 0,
            };
            let mut me = MODULEENTRY32W {
                dwSize: std::mem::size_of::<MODULEENTRY32W>() as u32,
                ..Default::default()
            };
            let base = if Module32FirstW(snap, &mut me).is_ok() {
                me.modBaseAddr as usize
            } else {
                0
            };
            let _ = CloseHandle(snap);
            base
        }
    }
}

// ════════════════════════════════════════════════════════════════════════════════════════════════════
// Linux backend — the game runs under Proton/Wine (same Windows PE), read/written via /proc + the
// process_vm_* syscalls. Direct port of the proven Python RE (see DISTRIBUTED-TOURNAMENT-SPECTATOR-TAPE.md).
// ════════════════════════════════════════════════════════════════════════════════════════════════════
#[cfg(unix)]
mod platform {
    use super::Region;

    /// pid + an optional /proc/<pid>/mem fd used ONLY as a fallback when process_vm_readv/writev is
    /// unavailable (ENOSYS on ancient kernels). The primary path needs no fd and no ptrace attach —
    /// process_vm_* works same-uid with kernel.yama.ptrace_scope=0 (set on the TO node).
    pub struct Proc {
        pid: libc::pid_t,
        fd: libc::c_int, // -1 when /proc/<pid>/mem could not be opened
        rw: bool,
    }

    impl Drop for Proc {
        fn drop(&mut self) {
            if self.fd >= 0 {
                unsafe {
                    libc::close(self.fd);
                }
            }
        }
    }

    fn open_common(pid: u32, rw: bool) -> Option<Proc> {
        let pid = pid as libc::pid_t;
        // validate the process exists (mirrors OpenProcess failing on a dead pid)
        if !std::path::Path::new(&format!("/proc/{}", pid)).exists() {
            return None;
        }
        // best-effort fallback fd; the primary process_vm_* path does not require it
        let flags = if rw { libc::O_RDWR } else { libc::O_RDONLY };
        let path = std::ffi::CString::new(format!("/proc/{}/mem", pid)).ok();
        let fd = match path {
            Some(p) => unsafe { libc::open(p.as_ptr(), flags) },
            None => -1,
        };
        Some(Proc { pid, fd, rw })
    }

    impl Proc {
        pub fn open_read(pid: u32) -> Option<Proc> {
            open_common(pid, false)
        }

        pub fn open_rw(pid: u32) -> Option<Proc> {
            open_common(pid, true)
        }

        /// process_vm_readv (no seek races); pread on /proc/<pid>/mem only if the syscall is missing.
        /// Semantics mirror the Windows `read`: partial reads truncate; Some only when >0 bytes read.
        pub fn read(&self, addr: usize, len: usize) -> Option<Vec<u8>> {
            if len == 0 {
                return None;
            }
            let mut buf = vec![0u8; len];
            let local = libc::iovec {
                iov_base: buf.as_mut_ptr() as *mut libc::c_void,
                iov_len: len,
            };
            let remote = libc::iovec {
                iov_base: addr as *mut libc::c_void,
                iov_len: len,
            };
            let n = unsafe {
                libc::process_vm_readv(
                    self.pid,
                    &local as *const libc::iovec,
                    1,
                    &remote as *const libc::iovec,
                    1,
                    0,
                )
            };
            if n > 0 {
                buf.truncate(n as usize);
                return Some(buf);
            }
            if n == 0 {
                return None;
            }
            // n < 0: only fall back on ENOSYS (syscall absent); EFAULT/EPERM are genuine → None.
            let err = std::io::Error::last_os_error().raw_os_error().unwrap_or(0);
            if err == libc::ENOSYS && self.fd >= 0 {
                let got = unsafe {
                    libc::pread(
                        self.fd,
                        buf.as_mut_ptr() as *mut libc::c_void,
                        len,
                        addr as libc::off_t,
                    )
                };
                if got > 0 {
                    buf.truncate(got as usize);
                    return Some(buf);
                }
            }
            None
        }

        /// process_vm_writev; pwrite fallback only on ENOSYS. True iff the FULL buffer was written.
        /// Needs same-uid + ptrace_scope=0 (no explicit attach). Cosmetic palette writes only.
        pub fn write(&self, addr: usize, buf: &[u8]) -> bool {
            if buf.is_empty() {
                return false;
            }
            let local = libc::iovec {
                iov_base: buf.as_ptr() as *mut libc::c_void,
                iov_len: buf.len(),
            };
            let remote = libc::iovec {
                iov_base: addr as *mut libc::c_void,
                iov_len: buf.len(),
            };
            let n = unsafe {
                libc::process_vm_writev(
                    self.pid,
                    &local as *const libc::iovec,
                    1,
                    &remote as *const libc::iovec,
                    1,
                    0,
                )
            };
            if n > 0 && n as usize == buf.len() {
                return true;
            }
            if n < 0 {
                let err = std::io::Error::last_os_error().raw_os_error().unwrap_or(0);
                if err == libc::ENOSYS && self.fd >= 0 && self.rw {
                    let got = unsafe {
                        libc::pwrite(
                            self.fd,
                            buf.as_ptr() as *const libc::c_void,
                            buf.len(),
                            addr as libc::off_t,
                        )
                    };
                    return got > 0 && got as usize == buf.len();
                }
            }
            false
        }

        pub fn region_at(&self, addr: usize) -> Option<Region> {
            self.regions()
                .into_iter()
                .find(|r| addr >= r.base && addr < r.base + r.size)
        }

        /// Parse /proc/<pid>/maps. Fresh each call (the map changes as the game allocates/frees), matching
        /// the Windows re-walk. Lines: `start-end perms offset dev inode pathname`.
        pub fn regions(&self) -> Vec<Region> {
            let data = std::fs::read_to_string(format!("/proc/{}/maps", self.pid)).unwrap_or_default();
            let mut out = Vec::new();
            for line in data.lines() {
                let mut it = line.split_whitespace();
                let range = match it.next() {
                    Some(r) => r,
                    None => continue,
                };
                let perms = match it.next() {
                    Some(p) => p,
                    None => continue,
                };
                let mut rp = range.split('-');
                let start = match rp.next().and_then(|s| usize::from_str_radix(s, 16).ok()) {
                    Some(s) => s,
                    None => continue,
                };
                let end = match rp.next().and_then(|s| usize::from_str_radix(s, 16).ok()) {
                    Some(e) => e,
                    None => continue,
                };
                if end <= start {
                    continue;
                }
                let pb = perms.as_bytes();
                out.push(Region {
                    base: start,
                    size: end - start,
                    readable: pb.first() == Some(&b'r'),
                    writable: pb.get(1) == Some(&b'w'),
                    executable: pb.get(2) == Some(&b'x'),
                    private: pb.get(3) == Some(&b'p'),
                });
            }
            out
        }
    }

    // The Windows PE name the game (and Proton) launches. comm is truncated to 15 chars, so we match
    // against the full argv in /proc/<pid>/cmdline instead.
    const EXE_PREFIX: &str = "MarvelVsCapcom";
    // Wine maps the PE at its preferred ImageBase; under Proton there is no ASLR relocation.
    const PREFERRED_BASE: usize = 0x140000000;

    /// Scan /proc/*/cmdline (NUL-separated argv) for the game. CRITICAL: under Proton, the Wine `steam.exe`
    /// launcher passes the game's path as an ARGUMENT (its argv[0] is steam.exe), so matching "any arg" also
    /// matches the launcher — which has the PE header mapped at 0x140000000 too but NONE of the live game state
    /// (session ptr etc. read null). The REAL game is the process whose **argv[0]** IS the game exe. So we split
    /// candidates: `argv0` = argv[0] basename is the game exe (the real process), `any_arg` = game only appears
    /// in a later arg (launcher/helper). Prefer an argv0 process that mapped the PE at the preferred base.
    pub fn find_game_pid() -> Option<u32> {
        let base_matches = |arg: &[u8]| -> bool {
            let s = String::from_utf8_lossy(arg);
            // rsplit always yields >=1 item (Windows path uses '\', unix uses '/').
            s.rsplit(['/', '\\']).next().unwrap_or("").starts_with(EXE_PREFIX)
        };
        let mut argv0: Vec<u32> = Vec::new();   // argv[0] IS the game exe → the real game process
        let mut any_arg: Vec<u32> = Vec::new(); // game path only in a later arg → Wine launcher / helper
        let rd = std::fs::read_dir("/proc").ok()?;
        for entry in rd.flatten() {
            let pid: u32 = match entry.file_name().to_str().and_then(|s| s.parse().ok()) {
                Some(p) => p,
                None => continue, // non-numeric /proc entry
            };
            let cmdline = match std::fs::read(format!("/proc/{}/cmdline", pid)) {
                Ok(b) => b,
                Err(_) => continue,
            };
            let mut args = cmdline.split(|&b| b == 0).filter(|a| !a.is_empty());
            match args.next() {
                Some(first) if base_matches(first) => argv0.push(pid),
                _ => { if cmdline.split(|&b| b == 0).any(base_matches) { any_arg.push(pid); } }
            }
        }
        // decisive gate: the REAL game is an argv[0] process that mapped the PE at 0x140000000. Fall back through
        // argv[0]-without-the-mapping, then the old "any arg + base" behavior, then any candidate.
        for &pid in &argv0 { if maps_have_base(pid, PREFERRED_BASE) { return Some(pid); } }
        if let Some(&pid) = argv0.first() { return Some(pid); }
        for &pid in &any_arg { if maps_have_base(pid, PREFERRED_BASE) { return Some(pid); } }
        any_arg.into_iter().next()
    }

    fn maps_have_base(pid: u32, want: usize) -> bool {
        let data = match std::fs::read_to_string(format!("/proc/{}/maps", pid)) {
            Ok(d) => d,
            Err(_) => return false,
        };
        for line in data.lines() {
            if let Some(range) = line.split_whitespace().next() {
                if let Some(start) = range.split('-').next() {
                    if usize::from_str_radix(start, 16).ok() == Some(want) {
                        return true;
                    }
                }
            }
        }
        false
    }

    /// The exe base = the lowest readable mapping of the game exe in /proc/<pid>/maps (expect 0x140000000).
    /// Falls back to the preferred base if a mapping at 0x140000000 exists but isn't name-tagged; 0 = unknown
    /// (callers treat exe_base==0 as "skip exe-relative reads", same as the Windows Module32 failure path).
    pub fn exe_base(pid: u32) -> usize {
        let data = match std::fs::read_to_string(format!("/proc/{}/maps", pid)) {
            Ok(d) => d,
            Err(_) => return 0,
        };
        let mut by_name: Option<usize> = None;
        let mut has_preferred = false;
        for line in data.lines() {
            let mut it = line.split_whitespace();
            let range = match it.next() {
                Some(r) => r,
                None => continue,
            };
            let perms = it.next().unwrap_or("");
            let path = line.split_whitespace().nth(5).unwrap_or("");
            let mut rp = range.split('-');
            let start = match rp.next().and_then(|s| usize::from_str_radix(s, 16).ok()) {
                Some(s) => s,
                None => continue,
            };
            if start == PREFERRED_BASE {
                has_preferred = true;
            }
            let readable = perms.as_bytes().first() == Some(&b'r');
            let base = path.rsplit(['/', '\\']).next().unwrap_or("");
            if readable && base.to_ascii_lowercase().contains("marvelvscapcom") {
                by_name = Some(by_name.map_or(start, |b| b.min(start)));
            }
        }
        by_name.unwrap_or(if has_preferred { PREFERRED_BASE } else { 0 })
    }
}

pub use platform::{exe_base, find_game_pid, Proc};
