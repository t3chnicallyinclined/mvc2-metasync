# MvC Fighting Collection — Netplay Matchmaker Handshake Protocol (RE)

Goal: reconstruct the **coordination handshake** a lobby host runs so a joined player is handed off to a
direct P2P match. The **fight itself (rollback + inputs) is P2P between the two players** — host-independent
(proven) — so we only need the *matchmaker* side. Target: reimplement on a `steam_api`-based bot (which HAS the
`ISteamNetworking` P2P transport SteamKit2 lacks). All RE below is **static (Ghidra) — zero anti-cheat risk**.
⚠ Game is **VAC-protected**: never in-process-hook the live game on a real account.

## Two layers (tied together)
- **Transport = Steam** (`steamclient64.dll`, `ISteamNetworking`): `SendP2PPacket(steamID, bytes, len, channel)` /
  `ReadP2PPacket` / `AcceptP2PSessionWithUser`. Session-less, addressed by SteamID, auto NAT-traverse + Valve relay.
  Available to any process via `steam_api64.dll` (the CreateLobby probe already used this DLL).
- **Protocol = game** (the `.exe`, Capcom): builds/parses the mesh messages below and calls `SendP2PPacket`.

## Connection bring-up — the "Steam" handshake  (`FUN_14016e8c0`)
P2P session state machine per peer (state via `FUN_140157dd0`, slots in obj+0x39 stride 3 ×16):
1. **NEW**: `GetP2PSessionState` (ISteamNetworking vt+0x30); if no session →
   **`SendP2PPacket(peerID, "Steam", 6, 0, channel=obj[0xff])`** (ISteamNetworking vt+0x00). Arms a **20 000 ms timeout**
   (`FUN_140158550(...,20000)`) → this is the exact "not responding" timeout our bot hit (it never accepted/answered).
2. **CONNECTED**: session state shows connected → `FUN_140173590` (established).
3. **CLOSE**: `CloseP2PSessionWithUser` (net-wrapper vt+0x60).
⟹ Bot must **AcceptP2PSessionWithUser** on the incoming request and answer, or the joiner times out.

## Message send path  (`FUN_14015a9a0`)
`FUN_14015a9a0(obj, target, dataPtr, len)` → `obj[0x37]->vt+0x68 (target, dataPtr, len)` → net object → `SendP2PPacket`.

## Message wire format (custom serialization) — CONFIRMED
**Wire is BIG-ENDIAN** (`FUN_1401281d0`=byteswap16, `FUN_1401281e0`=byteswap32).
Reader init `FUN_14012bf00(rdr, dataPtr, len)`: rdr+0x48=data, +0x50=len(cap), +0x54=cursor.
Writer init `FUN_14012bfc0(wtr, buf, size)`. All writers bounds-check `cursor+n <= cap`.
Field primitives (CONFIRMED sizes):
- write: `bb00`=**u8** · `bb20`=**u16 BE** · `bb60`=**u32 BE** · `ba30`=**[u16 BE len][bytes]** · `bac0`=fixed blob
- read (mirror): `b9e0`=u8 · (u16)/`b820`=u32 · `b980`=u64/SteamID · `b930`/`b870`=len-blob · `b760`=header multi-read
- checksum `FUN_14012c320`(key,off,len); length patch `FUN_14012c540`; endian-swap on header when `flag==1`.
**Header** (read by `b760` in dispatcher) = `[id:u16][?:u8][type:u16][sub:u16]` then body; validated per-type below.

## CONFIRMED CONSTANTS (read live 2026-08-16)
- **Protocol version** `DAT_142ebb840` = **0x15804ECA** (u32) → HELLO must carry this or reject `0x8005038c`.
- Per-type header (id / sub / flag=`>=`-mode):
  | type | id | sub | flag | | type | id | sub | flag |
  |--|--|--|--|--|--|--|--|--|
  | 1 HELLO | 86 | 12105 | 0 | | 6 ready | 8 | 6 | 0 |
  | 2 ACK/auth | 94 | 13761 | 1 | | 7 | 9 | 260 | 0 |
  | 3 member | 82 | 28626 | 0 | | 8 | 9 | 311 | 0 |
  | 4 | 80 | 21515 | 0 | | 9 P2P-setup | 16 | 13386 | 1 |
  | 5 member-data | 27 | 7346 | 0 | | 10 leave | 12 | 388 | 0 |
  (const addrs: t1 `exe+0xa64ff0`, t2 `+0xa65010`, t3 `+0xa65040`, t4 `+0xa65060`, t5 `+0xa65078`, t6 `+0xa65090`,
   t7 `+0xa650a0`, t8 `+0xa650b0`, t9 `+0xa650c0`, t10 `+0xa650d8`; id@+0x0 u16, sub@+0x4 u16, flag@+0x6 u8.)

## Mesh dispatcher — 10 message types  (`FUN_14013d520(obj, senderConnId, dataPtr, len)`)
Each case validates `DAT_140a650XX` header consts + a checksum (`sVar2!=sVar3` bails). Handlers:
| type | handler | meaning |
|---|---|---|
| 1 | `FUN_14013e3d0` | **HELLO/JOIN** (below) |
| 2 | `FUN_14013def0` | auth (Begin/EndAuthSession per peer) |
| 3 | inline + `FUN_140138ae0` | member/session info (builds MemberInfo, sets +0x1178) |
| 4 | `FUN_14013e150` | (TBD) |
| 5 | inline | member data → slot (stride 0x12a8, id@member+0x1288) |
| 6 | inline | ready-ack (sets obj+0x3c3=1 if from expected peer) |
| 7 | inline + `FUN_14015a7c0` | state toggle (obj+0x3b9) |
| 8 | inline | member state byte |
| 9 | inline | **P2P setup** (reads member SteamID, arms Steam P2P `vt+0x70`, sets 0x800 flag) |
| 10 | `FUN_14013e8e0` | leave/disconnect (may emit err 0x80050083) |

## JOIN handshake (the piece our bot was missing)
1. Joiner P2P-connects (sends `"Steam"` 6B) → host accepts session.
2. Joiner sends **HELLO (type 1)** = `[byte, 152B blob, SteamID(u64), version(int), 2048B player-data]`  (`FUN_14013e3d0`).
3. Host checks: we're host (obj+0x3c1,+0x3c0), lobby-owner id matches (obj+0x348==joiner id), and
   **version** `DAT_142ebb840 == joiner.version` → mismatch = reject **0x8005038c**.  (**read `DAT_142ebb840`**)
4. Host **adds member** `FUN_140138ae0`: finds empty slot (16 ×0x12a8), stores id@+0x1288 / name@+0x1208 / state@+0x126a,
   **decrements `SlotPublicOpen`/`SlotPrivateOpen` and re-`SetLobbyData`s them** (matchmaking vt+0xA0), sets up P2P
   (`FUN_14015aa40` / `FUN_140139ce0`), updates lobby type/joinable (`FUN_14013fb40`).
5. Host sends **ACK (type 2)** `FUN_14013ebf0`: writes header consts `DAT_140a65010/12/14`, result code, member index,
   host fields (obj+0x3c8/0x3d4/0x3d0/0x3d8), + the player-data blob; SEND via `FUN_14015a9a0`.

## THE HANDOFF — peer relay (type 4, `FUN_14013f530`)  ⭐
Host builds type-4 msg `[hdr id=80/sub=21515][peer connId:u32 BE][u32][peer SteamID: 8B fixed blob(bac0)]` + checksum +
len, SEND via `FUN_14015a9a0`. Host state-machine match phase calls this **for every member pair** → each player learns
every other player's (connId, SteamID) → **players then P2P-mesh directly with each other** (the fight is host-independent).
That is the whole "hand players to P2P" mechanism: host = central hub that broadcasts identities; players connect direct.
Reader `FUN_14012b760` = read u16 BE + consume (confirms header = sequence of BE u16 fields).
Member removal (leave) = `FUN_14013e720` (dec SlotPublicOpen, EndAuthSession) — NOT match-start.

## Full handshake sequence (reconstructed)
```
joiner --"Steam"(6B)--> host      ISteamNetworking; host must AcceptP2PSessionWithUser + answer (else 20s timeout)
joiner --HELLO t1-----> host      [id86, SteamID, version 0x15804ECA, playerdata blob]
host: version==0x15804ECA? → add member (FUN_140138ae0: slot, dec SlotPublicOpen, SetLobbyData)
host --ACK t2--------> joiner     FUN_14013ebf0 [member index, host fields, playerdata]
host --t2 auth-------> joiner     per-peer Steam auth (FUN_14013def0 / EndAuth FUN_14013e680)
host --t4 relay------> each peer  FUN_14013f530 [other peer connId + SteamID]  ◀ HANDOFF
players <--P2P mesh--> players    direct; host holds the room
```
⟹ Bot responder MVP: accept "Steam" → parse HELLO(t1) → send ACK(t2) → send relay(t4) with each peer's id.

## Host state machine  (`FUN_14013af30`, driven each tick by `FUN_140139fe0`; state @ obj+0x32eb)
0 init → 1 owner-check (+ **owner-migration** via GetLobbyOwner) → 2 wait → 3 broadcast-to-members (SendP2PPacket per
active slot) → 4 members-ready → 5 **slot-assign + match-coordination** (`FUN_14013f530`, `FUN_14013e720`; sets OwnerId
lobby data) → loop; 6 teardown. Session ptrs: cur@obj+0x27f8, owner-rec@obj+0x27f6, prev@obj+0x27f7.

## Key globals / addresses (exe base 0x140000000)
Steam singleton getter `(*DAT_1408db898)(&PTR_FUN_140a34d90)`; +0x08 User, +0x10 Friends, +0x20 Matchmaking,
**+0x40 Networking (ISteamNetworking)**. Net-wrapper obj `DAT_142ebb9d8` (P2P send helper `FUN_14015be60`),
mesh-obj factory `PTR_PTR_FUN_142ebb958`. Version const **`DAT_142ebb840`**. "Steam" string @ `0x14092468c`.

## NEXT (all safe/static)
- Read the header consts `DAT_140a650{10..de}` + `DAT_142ebb840` (version) — pins the exact wire bytes.
- Confirm each field primitive's size (b9e0/bb20/bb60…) by decompiling them.
- Map type-2 auth (`FUN_14013def0`), type-9 P2P-setup, and the match-start (`FUN_14013e720`/`FUN_14013f530`).
- Then: prototype the bot handshake responder on `steam_api` (accept "Steam" → parse HELLO → ACK → member/slot → start).
