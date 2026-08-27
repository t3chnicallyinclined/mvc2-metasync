#!/usr/bin/env python3
"""lobbyprobe.py [seconds] [--hex] [--once] - READ-ONLY. Writes NOTHING to the game, ever.

WHAT THIS ANSWERS
-----------------
In a 3-seat arcade lobby (a spectating cabinet that OWNS the lobby + two players who actually
fight) the tray currently resolves the LOBBY OWNER as the opponent. This probe prints the two
structures that can answer "who are the two FIGHTERS" without any heuristic, side by side, so one
live run says which is right:

  VIEW A - GGPO PLAYER TABLE.  The game builds a fighters-only list in `FUN_14003a520`:
           for each present slot whose SEAT index is in [0, numSeats) it appends
           `G+0x258+k*4 = seat` and `G+0x268+k*4 = slot`, then calls ggpo_start_session.
           A participant with no seat is NEVER appended - it becomes a GGPO *spectator*
           (or, on its own machine, calls ggpo_start_spectating). So this list structurally
           cannot contain the spectating cabinet.

  VIEW B - SESSION PARTICIPANT SLOTS.  The same 16-slot index, but read straight from the
           netplay session: seat index, CSteamID, persona, is-host. This is VIEW A's raw
           input, and it exists whether or not a GGPO session is running.

  VIEW C - COORDINATOR LOBBY MEMBERS.  The Steam-lobby member array (16 x 0x12a8) with a
           per-member CSteamID and an explicit IS_OWNER byte. This is the documented FALLBACK:
           enumerate + exclude the owner, instead of "the list already excludes them".

  VIEW D - CROSS-CHECKS. Three independent copies of each CSteamID must agree; the CSteamID
           tag bits must be sane; and the tray's current `A + 0x148` assumption is tested
           directly against every id we find.

HOW TO READ IT
--------------
Every value is printed RAW (hex, at its absolute address) next to the interpretation. A wrong
offset shows up as `??` / `BAD` / a CSteamID whose high dword is not 0x01100001, not as a
plausible-looking number. If a whole view prints `not resolved`, say so - a cited blank is the
finding, a guess is not.

RUN IT: sit in the 3-seat arcade lobby with the spectator + both players, then start a match and
leave this running across lobby -> character select -> fight -> results. Press any key to stop.

  python lobbyprobe.py            # watch until you press a key
  python lobbyprobe.py 120        # watch for 120 s
  python lobbyprobe.py --once     # single snapshot, then exit
  python lobbyprobe.py --hex      # also dump raw record bytes (for diagnosing a bad offset)

PROVENANCE OF EVERY OFFSET IS IN THE TABLE AT THE BOTTOM OF THIS FILE (CONFIRMED vs INFERRED).
"""
import os
import struct
import sys
import time

try:
    import msvcrt
except ImportError:
    msvcrt = None

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mvcmem import Mem, EXE

# ---------------------------------------------------------------- root pointers (image base rel)
MANAGER_PTR    = EXE + 0x2ebccb8   # -> netplay MANAGER            CONFIRMED
GAMESTATE_PTR  = EXE + 0xacd3a0    # -> G (expect 0x140ac6d40)     CONFIRMED
SESSION_PTR    = EXE + 0xacd3a8    # -> online SESSION object      CONFIRMED (already used by tray)
PLAYERLIST_PTR = EXE + 0xbd3bb8    # -> PLAYER-SLOT manager (PL)   CONFIRMED
LOCALPLAYER    = EXE + 0xac7230    # flycast localPlayerNum        (tray's existing constant)

# GGPO staging globals written by FUN_14003a520 (absolute, not pointers)
GG_STARTED   = EXE + 0x2d10960     # 1 once the session has been started
GG_MYIDX     = EXE + 0x2d10964     # our index into the GGPO player list; <0 => WE SPECTATE
GG_LOCALSLOT = EXE + 0x2d10968     # local slot passed as ggpo localport
GG_NPLAYERS  = EXE + 0x2d1096c     # number of real players added
GG_NSPECT    = EXE + 0x2d10970     # number of GGPO spectator entries (host only)
GG_PLAYERS   = EXE + 0x2d10974     # GGPOPlayer[], stride 0x30
GG_HOSTSLOT  = EXE + 0x2d10b64     # = session+0x1d0, the slot a spectator connects to
GG_ENTRYSLOT = EXE + 0x2d10b24     # entry k -> slot, stride 4
GG_NENTRIES  = EXE + 0x2d10b48     # number of GGPOPlayer entries emitted
GG_SESSION   = EXE + 0x2e10b98     # GGPOSession*
GG_LOCALHNDL = EXE + 0x2e10ba0     # local GGPOPlayerHandle
GG_HANDLES   = EXE + 0x2e10ba4     # stride 0x18: +0x00 type, +0x04 handle

GGP_STRIDE = 0x30                  # GGPOPlayer: +0 size, +4 type, +8 player_num, +0xc ip[32], +0x2c port
GGPTYPE = {0: "LOCAL", 1: "REMOTE", 2: "SPECTATOR"}

# G (game state @ 0x140ac6d40) - written ONLY for real players, index k in [0, nplayers)
G_SEAT = 0x258                     # + k*4  i32 seat index
G_SLOT = 0x268                     # + k*4  i32 slot index (0..15)
G_IN0  = 0x218                     # + s*4  raw per-seat input word

# PL - player-slot manager
PL_BASE, PL_STRIDE, PL_N = 0x11c0, 0x128, 16
PL_PRESENT_A = 0x00                # u8
PL_INMATCH   = 0x02                # u8   set by the seat-assign packet (case 0x11)
PL_PRESENT_B = 0x04                # u8
PL_SEAT      = 0x0c                # i32  -1 = no seat
PL_NAME      = 0x28                # char[0x100] mirrored from the session
PL_NUMSEATS  = 0x2552              # u8, on PL itself (set to 2 by the seat-assign packet)

# MS - match/netplay state = *( *(manager+0x250) + 0x10 )
MS_HOSTSLOT  = 0xcd60              # i32  slot of the session HOST
MS_MYSLOT    = 0xcd64              # i32  our slot
MS_FLAGS     = 0xcd68              # u8   bit0 = multi-peer session live
MS_NPEERS    = 0x6d74              # i32
MS_PEER_STRIDE = 0x170
MS_PEER_SEQ    = 0x6e6c            # + slot*0x170  i32
MS_PEER_CONN   = 0x6e70            # + slot*0x170  i32 index into the connection array
MS_PEER_FLAGS  = 0x6e74            # + slot*0x170  u16
MS_INFO        = 0x6ec8            # + slot*0x170  PlayerInfo, 0x104 bytes
MS_INFO_VALID  = 0x6ec8            #   PlayerInfo +0x000  u8
MS_INFO_TAG    = 0x6f28            #   PlayerInfo +0x058  u8  identity-variant tag
MS_INFO_SID    = 0x6f2c            #   PlayerInfo +0x05c  u64 CSteamID  (4-aligned, NOT 8-aligned)
MS_INFO_NAME   = 0x6f68            #   PlayerInfo +0x0a0  char[0x61]
MS_INFO_HOST   = 0x6fca            #   PlayerInfo +0x102  u8  IS HOST
MS_INFO_PRIV   = 0x6fcb            #   PlayerInfo +0x103  u8  private slot

MS_CONN_STRIDE = 0x480
MS_CONN_SID    = 0x860c            # + c*0x480  u64 CSteamID (conn idobj +0x5c)
MS_CONN_SLOT   = 0x867c            # + c*0x480  i32 slot this connection is bound to
MS_CONN_PING   = 0x8918            # + c*0x480  i32

# CO - Steam-lobby coordinator = *( *(manager+0x250) + 0x180 )
CO_LOBBYID   = 0x340
CO_OWNERCACHE= 0x348
CO_HOSTNAME  = 0x358               # char[0x61]
CO_IAMOWNER  = 0x3c0               # u8
CO_INLOBBY   = 0x3c1               # u8
CO_NMEMBERS  = 0x31c               # i32
CO_MAXMEMBERS= 0x320               # i32
CO_PRIV_USED, CO_PRIV_MAX = 0x324, 0x328
CO_PUB_USED,  CO_PUB_MAX  = 0x32c, 0x330
CO_LOCALREC  = 0x13fb0             # ptr -> OUR member record
CO_HOSTREC   = 0x13fb8             # ptr -> the host's member record
CO_GATE      = 0x13fc0
CO_STATE     = 0x19758             # i32 0..6
CO_MEM_BASE, CO_MEM_STRIDE, CO_MEM_N = 0x1530, 0x12a8, 16
M_ISOWNER_A  = 0x0005              # u8  MemberInfo copy: owner flag
M_SID_A      = 0x006c              # u64 MemberInfo idobj payload
M_NAME_A     = 0x00a8              # char[0x61]
M_LOBBYID    = 0x0110              # u64
M_OWNERID    = 0x0118              # u64
M_FLAG_1158  = 0x1158              # u8
M_FLAG_1161  = 0x1161              # u8  the flag the host state machine tests
M_INFO_VALID = 0x1168              # u8  PlayerInfo +0x000
M_SID_B      = 0x11cc              # u64 PlayerInfo idobj payload (+0x08+0x5c)
M_NAME_B     = 0x1208              # char[0x61] PlayerInfo +0x0a0
M_ISOWNER_B  = 0x126a              # u8  PlayerInfo +0x102  <-- THE OWNER BYTE
M_PRIVSLOT   = 0x126b              # u8  PlayerInfo +0x103
M_LOBBYID_LO = 0x1284              # i32
M_SID_C      = 0x1288              # u64 raw CSteamID copy
M_CONNID     = 0x129c              # i32
M_CONNSTATE  = 0x12a0              # u8  0 = us / 1 = pending / 2 = connected

# session object fields already known to the tray
S_NETSESS   = 0x1b8
S_GGPOHOST  = 0x1d0
S_HOSTED    = 0xd0320
S_MODE      = 0xd0328              # 1 ranked / 2 custom / 4 spectator
S_D0374     = 0xd0374
S_MYSEATX   = 0xd03f0

STEAMID_HI = 0x01100001            # universe 1 / type 1 individual / instance 1
TRAY_GAP   = 0x148                 # what find_opponent_lobby() assumes today


# --------------------------------------------------------------------------------- tiny helpers
def sid_ok(v):
    return v is not None and (v >> 32) == STEAMID_HI


def is_lobby_id(v):
    """CSteamID of a Steam LOBBY: universe 1, type 8 (chat), instance & 0x60000."""
    return (v is not None and (v >> 56) & 0xFF == 1 and (v >> 52) & 0xF == 8
            and (((v >> 32) & 0xFFFFF) & 0x60000) != 0)


def sid_str(v, want="user"):
    if v is None:
        return "??            (unreadable)"
    if v == 0:
        return "0             (empty)"
    uni, typ, inst = (v >> 56) & 0xFF, (v >> 52) & 0xF, (v >> 32) & 0xFFFFF
    if want == "lobby":
        tag = "LOBBY-OK" if is_lobby_id(v) else "NOT-A-LOBBY-ID"
    else:
        tag = "OK " if sid_ok(v) else ("(that is a LOBBY id, not a user)" if is_lobby_id(v) else "BAD")
    return "%-20d %-8s uni=%d type=%d inst=%d raw=0x%016x" % (v, tag, uni, typ, inst, v)


def cstr(m, addr, n):
    b = m.read(addr, n)
    if b is None:
        return None
    b = b.split(b"\0")[0]
    try:
        return b.decode("utf-8")
    except UnicodeDecodeError:
        return repr(b)


def i32(m, a):
    v = m.i32(a)
    return v


def show_ptr(label, addr, val, expect=None):
    if val is None:
        print("  %-34s @0x%010x = UNREADABLE" % (label, addr))
        return False
    note = ""
    if expect is not None:
        note = "  (expected 0x%x -> %s)" % (expect, "MATCH" if val == expect else "MISMATCH")
    elif val == 0:
        note = "  <- NULL: this branch is not live right now"
    elif val < 0x10000:
        note = "  <- not a pointer"
    print("  %-34s @0x%010x = 0x%016x%s" % (label, addr, val, note))
    return val > 0x10000 or (expect is not None and val == expect)


def hexdump(m, addr, n, indent="      "):
    b = m.read(addr, n)
    if b is None:
        print(indent + "unreadable")
        return
    for off in range(0, n, 16):
        row = b[off:off + 16]
        print("%s+%04x  %-47s  %s" % (
            indent, off, " ".join("%02x" % c for c in row),
            "".join(chr(c) if 32 <= c < 127 else "." for c in row)))


# ------------------------------------------------------------------------------------ the views
def resolve(m):
    """Every pointer hop, printed. Returns a dict; missing keys mean 'not resolved'."""
    r = {}
    print("=== 0. POINTER CHAIN (every hop shown so a dead chain is obvious) ===")

    mz = m.read(EXE, 2)
    print("  image base 0x%x header = %s%s" % (
        EXE, mz, "" if mz == b"MZ" else "   <-- NOT 'MZ': image base assumption is WRONG"))

    g = m.u64(GAMESTATE_PTR)
    show_ptr("G  = *(exe+0xacd3a0)", GAMESTATE_PTR, g, expect=EXE + 0xac6d40)
    if g and g > 0x10000:
        r["G"] = g

    s = m.u64(SESSION_PTR)
    if show_ptr("SESSION = *(exe+0xacd3a8)", SESSION_PTR, s):
        r["S"] = s

    pl = m.u64(PLAYERLIST_PTR)
    if show_ptr("PL = *(exe+0xbd3bb8)", PLAYERLIST_PTR, pl):
        r["PL"] = pl

    mgr = m.u64(MANAGER_PTR)
    if show_ptr("MANAGER = *(exe+0x2ebccb8)", MANAGER_PTR, mgr):
        r["MGR"] = mgr
        s0 = m.u64(mgr + 0x250)
        if show_ptr("session0 = *(MANAGER+0x250)", mgr + 0x250, s0):
            r["S0"] = s0
            ms = m.u64(s0 + 0x10)
            if show_ptr("matchState = *(session0+0x10)", s0 + 0x10, ms):
                r["MS"] = ms
            co = m.u64(s0 + 0x180)
            if show_ptr("coordinator = *(session0+0x180)", s0 + 0x180, co):
                r["CO"] = co
    print()
    return r


def view_session(m, r):
    """VIEW B first: it feeds VIEW A and it exists even with no GGPO session."""
    print("=== B. SESSION PARTICIPANT SLOTS  (16 x 0x128 in PL, 16 x 0x170 in matchState) ===")
    pl, ms = r.get("PL"), r.get("MS")
    if not pl or not ms:
        print("  not resolved (PL=%s matchState=%s) -> no participant view this sample" % (
            hex(pl) if pl else None, hex(ms) if ms else None))
        print()
        return []

    nseats = m.u8(pl + PL_NUMSEATS)
    myslot = i32(m, ms + MS_MYSLOT)
    hostslot = i32(m, ms + MS_HOSTSLOT)
    flags = m.u8(ms + MS_FLAGS)
    npeers = i32(m, ms + MS_NPEERS)
    print("  PL+0x2552 numSeats = %s     matchState+0xcd64 mySlot = %s     "
          "+0xcd60 hostSlot = %s" % (nseats, myslot, hostslot))
    print("  matchState+0xcd68 flags = %s (bit0 session-live = %s)   +0x6d74 peers = %s" % (
        flags, (flags & 1) if flags is not None else "?", npeers))
    if not nseats:
        print("  !! numSeats is 0/unreadable - the FIGHTER test below cannot be evaluated")
    print()
    print("  slot | presA presB inM | seat | FIGHTER? | host | conn | CSteamID                       | persona")
    print("  -----+-----------------+------+----------+------+------+--------------------------------+--------")

    out = []
    for s in range(PL_N):
        p = pl + PL_BASE + s * PL_STRIDE
        a, b_, inm = m.u8(p + PL_PRESENT_A), m.u8(p + PL_PRESENT_B), m.u8(p + PL_INMATCH)
        if not a and not b_:
            continue
        seat = i32(m, p + PL_SEAT)
        q = ms + s * MS_PEER_STRIDE
        valid = m.u8(q + MS_INFO_VALID)
        sid = m.u64(q + MS_INFO_SID)
        tag = m.u8(q + MS_INFO_TAG)
        name = cstr(m, q + MS_INFO_NAME, 0x61)
        ishost = m.u8(q + MS_INFO_HOST)
        conn = i32(m, q + MS_PEER_CONN)
        fighter = (nseats is not None and seat is not None and 0 <= seat < nseats)
        out.append(dict(slot=s, seat=seat, sid=sid, sid_addr=q + MS_INFO_SID, name=name,
                        host=ishost, conn=conn, fighter=fighter, valid=valid, tag=tag))
        print("  %4d | %5s %5s %3s | %4s | %-8s | %4s | %4s | %-30s | %s%s" % (
            s, a, b_, inm, seat,
            "FIGHTER" if fighter else "spectator",
            ishost, conn,
            ("%d" % sid) if sid else ("??" if sid is None else "0"),
            name,
            "   <== US" if s == myslot else ""))
    if not out:
        print("  (no present slots - not in a netplay session right now)")
    print()
    print("  raw CSteamID check (a wrong offset shows up HERE, not as a plausible number):")
    for e in out:
        print("    slot %2d  @0x%010x  %s   idobj tag=%s valid=%s" % (
            e["slot"], e["sid_addr"], sid_str(e["sid"]), e["tag"], e["valid"]))
    print()
    return out


def view_ggpo(m, r, participants):
    print("=== A. GGPO PLAYER TABLE  (fighters-only by construction) ===")
    g = r.get("G")
    started = i32(m, GG_STARTED)
    nplayers = i32(m, GG_NPLAYERS)
    nspect = i32(m, GG_NSPECT)
    myidx = i32(m, GG_MYIDX)
    hostslot = i32(m, GG_HOSTSLOT)
    nentries = i32(m, GG_NENTRIES)
    sess = m.u64(GG_SESSION)
    print("  started=%s  nPlayers=%s  nSpectatorEntries=%s  ourGgpoIndex=%s  "
          "ggpoHostSlot=%s  entries=%s" % (started, nplayers, nspect, myidx, hostslot, nentries))
    print("  GGPOSession* @0x%010x = 0x%x   localHandle=%s" % (
        GG_SESSION, sess or 0, i32(m, GG_LOCALHNDL)))
    if myidx is not None and myidx < 0:
        print("  ourGgpoIndex < 0  ==>  THIS MACHINE IS THE SPECTATOR (ggpo_start_spectating path)")
    if not started:
        print("  ** no GGPO session started since boot - VIEW A is empty until an online match runs **")

    if g and nplayers and nplayers > 0:
        print()
        print("  k | seat(G+0x258) | slot(G+0x268) | CSteamID              | persona")
        print("  --+---------------+---------------+-----------------------+--------")
        by_slot = {e["slot"]: e for e in participants}
        for k in range(min(nplayers, 16)):
            seat = i32(m, g + G_SEAT + k * 4)
            slot = i32(m, g + G_SLOT + k * 4)
            e = by_slot.get(slot)
            print("  %d | %13s | %13s | %-21s | %s%s" % (
                k, seat, slot,
                (e and e["sid"]) or "-", (e and e["name"]) or "-",
                "   <== US" if k == myidx else ""))
            if e and not e["fighter"]:
                print("      !! this GGPO player's slot does NOT pass the seat test - "
                      "the two views DISAGREE (see D)")
            if e is None and slot is not None and 0 <= slot < 16:
                print("      !! slot %d has no present participant record - offsets disagree" % slot)
    print()

    print("  GGPOPlayer[] staging array @0x%010x (host-only entries include SPECTATORS):" % GG_PLAYERS)
    n = nentries if (nentries and 0 < nentries <= 16) else 4
    for k in range(n):
        a = GG_PLAYERS + k * GGP_STRIDE
        size, typ, num = i32(m, a), i32(m, a + 4), i32(m, a + 8)
        ip = cstr(m, a + 0x0c, 0x20)
        port = m.u16(a + 0x2c)
        eslot = i32(m, GG_ENTRYSLOT + k * 4)
        if not size and not typ and not num and not ip:
            continue
        print("    [%d] size=%s type=%s(%s) player_num=%s ip=%-14r port=%s  entry->slot=%s" % (
            k, size, typ, GGPTYPE.get(typ, "?"), num, ip, port, eslot))
        if size not in (None, 0x30):
            print("        !! GGPOPlayer.size is %s, expected 0x30 - the 0x30 stride is WRONG" % size)
    print()


def view_lobby(m, r):
    print("=== C. COORDINATOR LOBBY MEMBERS  (16 x 0x12a8) - the FALLBACK view ===")
    co = r.get("CO")
    if not co:
        print("  coordinator not resolved -> no member view this sample")
        print()
        return []
    lob = m.u64(co + CO_LOBBYID)
    own = m.u64(co + CO_OWNERCACHE)
    print("  coord+0x340 lobbyId    = %s" % sid_str(lob, "lobby"))
    print("  coord+0x348 ownerCache = %s" % sid_str(own))
    print("  coord+0x3c0 iAmOwner=%s  +0x3c1 inLobby=%s  +0x19758 state=%s  +0x13fc0 gate=0x%x" % (
        m.u8(co + CO_IAMOWNER), m.u8(co + CO_INLOBBY), i32(m, co + CO_STATE),
        m.u64(co + CO_GATE) or 0))
    print("  members used/max = %s/%s   private %s/%s   public %s/%s   hostName=%r" % (
        i32(m, co + CO_NMEMBERS), i32(m, co + CO_MAXMEMBERS),
        i32(m, co + CO_PRIV_USED), i32(m, co + CO_PRIV_MAX),
        i32(m, co + CO_PUB_USED), i32(m, co + CO_PUB_MAX),
        cstr(m, co + CO_HOSTNAME, 0x61)))
    localrec, hostrec = m.u64(co + CO_LOCALREC), m.u64(co + CO_HOSTREC)
    print("  coord+0x13fb0 ourRecord = 0x%x   +0x13fb8 hostRecord = 0x%x" % (
        localrec or 0, hostrec or 0))
    print()
    print("  idx | f1158 f1161 valid | OWNER | conn/state | CSteamID(+0x1288)     | persona")
    print("  ----+-------------------+-------+------------+-----------------------+--------")
    out = []
    for i in range(CO_MEM_N):
        mm = co + CO_MEM_BASE + i * CO_MEM_STRIDE
        valid = m.u8(mm + M_INFO_VALID)
        f1158, f1161 = m.u8(mm + M_FLAG_1158), m.u8(mm + M_FLAG_1161)
        sid_c = m.u64(mm + M_SID_C)
        if not valid and not f1158 and not sid_c:
            continue
        owner = m.u8(mm + M_ISOWNER_B)
        name = cstr(m, mm + M_NAME_B, 0x61)
        out.append(dict(idx=i, addr=mm, sid_a=m.u64(mm + M_SID_A), sid_b=m.u64(mm + M_SID_B),
                        sid_c=sid_c, sid_c_addr=mm + M_SID_C, name=name, owner=owner,
                        owner_a=m.u8(mm + M_ISOWNER_A), conn=i32(m, mm + M_CONNID),
                        state=m.u8(mm + M_CONNSTATE), lobby=m.u64(mm + M_LOBBYID),
                        ownerid=m.u64(mm + M_OWNERID)))
        print("  %3d | %5s %5s %5s | %5s | %4s / %-3s | %-21s | %s%s" % (
            i, f1158, f1161, valid, owner, i32(m, mm + M_CONNID), m.u8(mm + M_CONNSTATE),
            sid_c or "??", name, "   <== US" if mm == localrec else ""))
    if not out:
        print("  (no populated member records - not in a game lobby right now)")
    print()
    print("  per-member detail (three independent copies of the id MUST agree):")
    for e in out:
        print("    [%2d] @0x%010x" % (e["idx"], e["addr"]))
        print("         +0x006c MemberInfo idobj : %s" % sid_str(e["sid_a"]))
        print("         +0x11cc PlayerInfo idobj : %s" % sid_str(e["sid_b"]))
        print("         +0x1288 raw copy         : %s" % sid_str(e["sid_c"]))
        print("         +0x0110 lobbyId : %s" % sid_str(e["lobby"], "lobby"))
        print("         +0x0118 ownerId : %s" % sid_str(e["ownerid"]))
        print("         +0x0005 ownerFlagA=%s   +0x126a ownerFlagB=%s   name=%r" % (
            e["owner_a"], e["owner"], e["name"]))
        agree = len({x for x in (e["sid_a"], e["sid_b"], e["sid_c"]) if x}) <= 1
        if not agree:
            print("         !! THE THREE COPIES DISAGREE -> at least one offset is wrong")
    print()
    return out


def view_checks(m, r, participants, members):
    print("=== D. CROSS-CHECKS AND FALSIFIERS ===")
    ms = r.get("MS")

    # D1 - exactly one host, and the host is (or is not) a fighter.
    hosts = [e for e in participants if e["host"]]
    print("  D1 host flag: %d participant(s) carry PlayerInfo+0x102=1 -> slots %s" % (
        len(hosts), [e["slot"] for e in hosts]))
    if len(hosts) != 1 and participants:
        print("     !! expected exactly 1 - if 0 or >1, +0x102 is not the host byte")
    for e in hosts:
        print("     host slot %d seat=%s -> %s" % (
            e["slot"], e["seat"], "IS ALSO A FIGHTER" if e["fighter"] else "is NOT a fighter (spectating owner)"))

    # D2 - fighters count vs GGPO nplayers.
    fighters = [e for e in participants if e["fighter"]]
    nplayers = i32(m, GG_NPLAYERS)
    print("  D2 fighters by seat test = %d %s ; GGPO nPlayers = %s" % (
        len(fighters), [e["slot"] for e in fighters], nplayers))
    if nplayers and len(fighters) != nplayers:
        print("     !! MISMATCH - the seat test and the GGPO list disagree; one of the two is wrong")

    # D3 - connection array agrees with the peer array on each id.
    if ms and participants:
        print("  D3 connection array cross-check (matchState+0x85b0 + c*0x480):")
        for e in participants:
            c = e["conn"]
            if c is None or c < 0 or c > 15:
                print("     slot %2d conn=%s  (no connection - normally true only for ourselves)" % (
                    e["slot"], c))
                continue
            csid = m.u64(ms + MS_CONN_SID + c * MS_CONN_STRIDE)
            cslot = i32(m, ms + MS_CONN_SLOT + c * MS_CONN_STRIDE)
            ping = i32(m, ms + MS_CONN_PING + c * MS_CONN_STRIDE)
            ok = (csid == e["sid"]) and (cslot == e["slot"])
            print("     slot %2d conn %2d -> back-slot=%s ping=%s sid=%s   %s" % (
                e["slot"], c, cslot, ping, csid, "agree" if ok else "!! DISAGREE"))

    # D4 - lobby members vs session participants.
    if participants and members:
        pset = {e["sid"] for e in participants if e["sid"]}
        mset = {e["sid_c"] for e in members if e["sid_c"]}
        print("  D4 participants %s  vs  lobby members %s" % (sorted(pset), sorted(mset)))
        if pset and mset and pset != mset:
            print("     note: sets differ - expected if someone is in the lobby but not the session")
        owners = [e for e in members if e["owner"]]
        if owners:
            print("     lobby owner by +0x126a = %s (%r)" % (owners[0]["sid_c"], owners[0]["name"]))
            oid = owners[0]["sid_c"]
            fs = [e["sid"] for e in participants if e["fighter"]]
            if oid in fs:
                print("     ...and the owner IS one of the fighters (a 2-seat lobby, owner plays)")
            elif fs:
                print("     ...and the owner is NOT a fighter -> THIS IS THE 3-SEAT BUG CASE. "
                      "Fighters = %s" % fs)

    # D5 - the tray's current assumption, tested directly.
    print("  D5 tray heuristic `opponent = *(A + 0x148)` where A holds OUR id:")
    hits = 0
    for e in participants + [dict(sid=x["sid_c"], sid_addr=x["sid_c_addr"], slot=-1) for x in members]:
        a = e.get("sid_addr")
        if not a or not sid_ok(e.get("sid")):
            continue
        nxt = m.u64(a + TRAY_GAP)
        prv = m.u64(a - TRAY_GAP)
        if sid_ok(nxt) or sid_ok(prv):
            hits += 1
            print("     id 0x%010x holds %s ; +0x148 -> %s ; -0x148 -> %s" % (
                a, e["sid"], nxt if sid_ok(nxt) else "-", prv if sid_ok(prv) else "-"))
    if hits == 0:
        print("     no +/-0x148 SteamID adjacency in EITHER of the structures above.")
        print("     ==> the record the tray is scanning is a THIRD structure we have NOT identified.")
    print()


def verdict(m, r, participants, members):
    """The headline. Everything above is the evidence for these four lines."""
    print("=== THE ANSWER (this is what the tray should report) ===")
    g, ms = r.get("G"), r.get("MS")
    nplayers = i32(m, GG_NPLAYERS)
    myidx = i32(m, GG_MYIDX)
    by_slot = {e["slot"]: e for e in participants}

    ggpo = []
    if g and nplayers and nplayers > 0:
        for k in range(min(nplayers, 16)):
            slot = i32(m, g + G_SLOT + k * 4)
            seat = i32(m, g + G_SEAT + k * 4)
            e = by_slot.get(slot)
            ggpo.append((seat, slot, e["sid"] if e else None, e["name"] if e else None))
    seat_only = [(e["seat"], e["slot"], e["sid"], e["name"]) for e in participants if e["fighter"]]
    others = [(e["seat"], e["slot"], e["sid"], e["name"]) for e in participants if not e["fighter"]]

    print("  FIGHTERS via GGPO player list  : %s" % (
        [("seat%s" % s_, sid, nm) for s_, _sl, sid, nm in sorted(ggpo)] or "none (no GGPO session)"))
    print("  FIGHTERS via seat test         : %s" % (
        [("seat%s" % s_, sid, nm) for s_, _sl, sid, nm in sorted(seat_only)] or "none"))
    print("  NON-FIGHTER PARTICIPANTS       : %s   <- the spectating cabinet belongs HERE" % (
        [(sid, nm) for _s, _sl, sid, nm in others] or "none"))
    if ggpo and seat_only:
        a = sorted(x[2] for x in ggpo if x[2])
        b = sorted(x[2] for x in seat_only if x[2])
        print("  the two views %s" % ("AGREE" if a == b else "DISAGREE  <<< investigate before trusting either"))
    owner = next((e for e in members if e["owner"]), None)
    if owner:
        fs = [x[2] for x in seat_only]
        print("  lobby OWNER                    : %s (%r) -> %s" % (
            owner["sid_c"], owner["name"],
            "also a fighter" if owner["sid_c"] in fs else
            "NOT a fighter (owner-exclusion would have been needed; the seat test already excluded them)"))
    myslot = i32(m, ms + MS_MYSLOT) if ms else None
    me = by_slot.get(myslot)
    print("  us: slot=%s seat=%s ggpoIdx=%s localPlayerNum=%s  (pins seat -> P1/P2)" % (
        myslot, me["seat"] if me else "?", myidx, i32(m, LOCALPLAYER)))
    print()


def dump_records(m, r, participants, members):
    print("=== RAW RECORD DUMPS (--hex) ===")
    ms, pl, co = r.get("MS"), r.get("PL"), r.get("CO")
    for e in participants[:3]:
        s = e["slot"]
        if pl:
            print("  PL slot %d record @0x%010x (0x128 bytes)  [+0x00/+0x04 present, +0x0c seat]"
                  % (s, pl + PL_BASE + s * PL_STRIDE))
            hexdump(m, pl + PL_BASE + s * PL_STRIDE, 0x40)
        if ms:
            print("  matchState PlayerInfo slot %d @0x%010x (0x104 bytes)  "
                  "[+0x00 valid, +0x08 idobj(tag@+0x58, id@+0x5c), +0xa0 name, +0x102 host]"
                  % (s, ms + MS_INFO + s * MS_PEER_STRIDE))
            hexdump(m, ms + MS_INFO + s * MS_PEER_STRIDE, 0x110)
        print()
    for e in members[:3]:
        print("  coordinator member %d PlayerInfo @0x%010x  "
              "[member+0x1168 .. +0x126c]" % (e["idx"], e["addr"] + M_INFO_VALID))
        hexdump(m, e["addr"] + M_INFO_VALID, 0x110)
        print("  ...raw id copy @0x%010x (member+0x1288):" % (e["addr"] + M_SID_C))
        hexdump(m, e["addr"] + M_SID_C, 0x20)
        print()


def snapshot(m, do_hex):
    print("#" * 100)
    print("# lobbyprobe snapshot  %s   pid %d" % (time.strftime("%H:%M:%S"), m.pid))
    print("#" * 100)
    r = resolve(m)

    s = r.get("S")
    if s:
        print("=== session object (context) ===")
        print("  session+0x1b8 netSession=%s  +0x1d0 ggpoHostSlot=%s" % (
            i32(m, s + S_NETSESS), i32(m, s + S_GGPOHOST)))
        print("  session+0xd0320 hosted=%s  +0xd0328 mode=%s (1 ranked / 2 custom / 4 spectator)  "
              "+0xd0374=%s  +0xd03f0=%s" % (
                  i32(m, s + S_HOSTED), i32(m, s + S_MODE), i32(m, s + S_D0374),
                  i32(m, s + S_MYSEATX)))
        print("  exe+0xac7230 localPlayerNum = %s  (0 -> P1, 1 -> P2; pair this with our SEAT "
              "to pin seat->side)" % i32(m, LOCALPLAYER))
        print()

    participants = view_session(m, r)
    view_ggpo(m, r, participants)
    members = view_lobby(m, r)
    verdict(m, r, participants, members)
    view_checks(m, r, participants, members)
    if do_hex:
        dump_records(m, r, participants, members)
    return r, participants, members


def digest(participants, members, m, r):
    """A short comparable line so the watch loop can report only CHANGES."""
    g = r.get("G")
    np_ = i32(m, GG_NPLAYERS)
    gg = []
    if g and np_:
        for k in range(min(np_, 16)):
            gg.append((i32(m, g + G_SEAT + k * 4), i32(m, g + G_SLOT + k * 4)))
    return (tuple(sorted(repr((e["slot"], e["seat"], e["sid"], e["host"])) for e in participants)),
            tuple(repr(x) for x in gg),
            tuple(sorted(repr((e["idx"], e["sid_c"], e["owner"])) for e in members)))


def main():
    args = [a for a in sys.argv[1:]]
    do_hex = "--hex" in args
    once = "--once" in args
    secs = float("inf")
    for a in args:
        if not a.startswith("-"):
            try:
                secs = float(a)
            except ValueError:
                pass

    m = Mem()
    print(__doc__.split("PROVENANCE")[0])
    r, p, mem = snapshot(m, do_hex)
    if once:
        return

    print("=== WATCHING for changes (press any key to stop) ===")
    print("    Take the lobby through: everyone seated -> character select -> fight -> results.")
    print("    Every transition below is a data point about WHEN the seat map becomes valid.\n")
    last = digest(p, mem, m, r)
    t0 = time.time()
    while time.time() - t0 < secs:
        if msvcrt and msvcrt.kbhit():
            msvcrt.getch()
            break
        time.sleep(0.5)
        try:
            r = {}
            g = m.u64(GAMESTATE_PTR)
            mgr = m.u64(MANAGER_PTR)
            pl = m.u64(PLAYERLIST_PTR)
            if g and g > 0x10000:
                r["G"] = g
            if pl and pl > 0x10000:
                r["PL"] = pl
            if mgr and mgr > 0x10000:
                s0 = m.u64(mgr + 0x250)
                if s0 and s0 > 0x10000:
                    ms, co = m.u64(s0 + 0x10), m.u64(s0 + 0x180)
                    if ms and ms > 0x10000:
                        r["MS"] = ms
                    if co and co > 0x10000:
                        r["CO"] = co
            if "PL" not in r or "MS" not in r:
                continue
            # quiet re-read of the two lists
            pl, ms = r["PL"], r["MS"]
            nseats = m.u8(pl + PL_NUMSEATS)
            parts = []
            for s in range(PL_N):
                pp = pl + PL_BASE + s * PL_STRIDE
                if not m.u8(pp + PL_PRESENT_A) and not m.u8(pp + PL_PRESENT_B):
                    continue
                seat = i32(m, pp + PL_SEAT)
                q = ms + s * MS_PEER_STRIDE
                parts.append(dict(slot=s, seat=seat, sid=m.u64(q + MS_INFO_SID),
                                  sid_addr=q + MS_INFO_SID,
                                  name=cstr(m, q + MS_INFO_NAME, 0x61),
                                  host=m.u8(q + MS_INFO_HOST), conn=i32(m, q + MS_PEER_CONN),
                                  valid=m.u8(q + MS_INFO_VALID), tag=m.u8(q + MS_INFO_TAG),
                                  fighter=(nseats is not None and seat is not None
                                           and 0 <= seat < nseats)))
            mems = []
            if "CO" in r:
                co = r["CO"]
                for i in range(CO_MEM_N):
                    mm = co + CO_MEM_BASE + i * CO_MEM_STRIDE
                    sc = m.u64(mm + M_SID_C)
                    if not m.u8(mm + M_INFO_VALID) and not sc:
                        continue
                    mems.append(dict(idx=i, addr=mm, sid_a=m.u64(mm + M_SID_A),
                                     sid_b=m.u64(mm + M_SID_B), sid_c=sc, sid_c_addr=mm + M_SID_C,
                                     name=cstr(m, mm + M_NAME_B, 0x61),
                                     owner=m.u8(mm + M_ISOWNER_B),
                                     owner_a=m.u8(mm + M_ISOWNER_A),
                                     conn=i32(m, mm + M_CONNID), state=m.u8(mm + M_CONNSTATE),
                                     lobby=m.u64(mm + M_LOBBYID), ownerid=m.u64(mm + M_OWNERID)))
            d = digest(parts, mems, m, r)
            if d != last:
                last = d
                print("\n>>> CHANGE at %s (+%.0fs)" % (time.strftime("%H:%M:%S"), time.time() - t0))
                snapshot(m, do_hex)
        except OSError:
            time.sleep(0.5)

    print("\n=== FINAL SNAPSHOT ===")
    snapshot(m, do_hex)
    print("""
WHAT WOULD DISPROVE THIS
------------------------
* B shows a participant whose CSteamID prints BAD (hi dword != 0x01100001) while the persona
  next to it is a real name  -> the id offset (+0x6f2c) is wrong even though the record is right.
* D1 reports 0 or >1 hosts   -> PlayerInfo+0x102 is not the host byte.
* D2 fighters != GGPO nPlayers -> the seat test and the GGPO list are not the same partition;
  the "GGPO players are the fighters" claim fails on this build.
* A lists the spectating cabinet's CSteamID among the k in [0, nPlayers) rows -> the central
  claim is refuted and the lobby view (C, owner-exclusion) is the only route.
* C shows the three id copies disagreeing -> at least one member offset is wrong.
* D5 finds a +/-0x148 adjacency inside these structures -> the tray was reading THIS structure
  after all, and the bug is narrower than "wrong structure".
""")


if __name__ == "__main__":
    main()

# ---------------------------------------------------------------------------------------------
# PROVENANCE  (image base 0x140000000; static RE against C:\Users\trist\ghidra_projects\mvc_dump.bin)
#
# CONFIRMED - read directly out of the decompiled/disassembled code named beside it:
#   *(exe+0x2ebccb8) manager, *(manager+0x250) session0, *(session0+0x10) matchState  FUN_14026b660
#   *(session0+0x180) coordinator                                                      ARCADE-CREATE-RE
#   *(exe+0xacd3a0) == 0x140ac6d40 (verified in the dump), *(exe+0xbd3bb8) PL          FUN_14003a520
#   G+0x258+k*4 seat / G+0x268+k*4 slot, written ONLY for real players                 14003a715/14003a72b
#   nPlayers 0x142d1096c, ourIdx 0x142d10964, nSpect 0x142d10970, hostSlot 0x142d10b64 FUN_14003a520
#   GGPOPlayer stride 0x30 (size/type/player_num/ip"192.168.0.%d"/port=slot)           FUN_14003a520
#   ggpo_start_session FUN_140119950 via FUN_140118ae0; ggpo_add_player FUN_1401198c0;
#   ggpo_start_spectating FUN_1401199d0 via FUN_140118cf0                              FUN_140118ae0/cf0
#   PL slot array +0x11c0 stride 0x128, present +0x00/+0x04, seat +0x0c                FUN_140065ed0/1400672d0
#   PL+0x2552 numSeats; fighter test 0 <= seat < numSeats                              FUN_140066b80
#   matchState +0xcd64 our slot, +0xcd60 host slot, +0xcd68 bit0 live, +0x6d74 peers    FUN_14034ba70/b0c0
#   peer stride 0x170; +0x6e70 connIdx; +0x6ec8 PlayerInfo                             FUN_14034b820
#   PlayerInfo = {+0x00 valid, +0x08 idobj, +0xa0 name[0x61], +0x102 isHost, +0x103}   FUN_14015abe0
#   identity object: +0x48 buf, +0x50 cap, +0x54 len, +0x58 tag, +0x5c payload         FUN_14012c500/b540
#   ...so CSteamID = PlayerInfo+0x64  (abs 0x6f2c + slot*0x170)                        FUN_14012c500
#   connection array: idobj @ +0x85b0+c*0x480, slot @ +0x867c, ping @ +0x8918          FUN_14034b820/140066470
#   coordinator member array +0x1530 stride 0x12a8 x16                                 FUN_140138ae0
#   member +0x1288 raw CSteamID, +0x1208 name, +0x126a isHost, +0x129c connId,
#          +0x12a0 conn state, +0x110 lobbyId, +0x118 ownerId, +0x1168 PlayerInfo      FUN_140138ae0/FUN_14013af30
#   coordinator +0x340 lobbyId, +0x348 ownerCache, +0x358 hostName, +0x3c0 iAmOwner,
#               +0x3c1 inLobby, +0x13fb0 ourRec, +0x13fb8 hostRec, +0x19758 state      FUN_14013af30
#
# INFERRED - consistent with the code but not directly named there:
#   peer-array BASE = matchState+0x6e60 (deduced from 0x6e60/0x6e6c/0x6e70/0x6ec8 + stride 0x170)
#   PlayerInfo+0x103 = "private slot" (it selects the +0x6d7c vs +0x6d84 counter; in
#       FUN_140138ae0 the same byte comes from the private/public slot flag) - NOT a spectator flag
#   seat 0 == P1 / seat 1 == P2  (print localPlayerNum next to our seat to settle it live)
#
# UNKNOWN - do not fill in:
#   the structure the tray's find_opponent_lobby() currently scans (our id at rec+0x3c, opp at
#   rec+0x184, persona at rec+0x1c0). It is NOT the coordinator member array and NOT the
#   matchState peer array; D5 tests for it explicitly.
