# MetaSync — Beta Tester Guide

Thanks for testing! **MetaSync** is a companion app for the Steam **MARVEL vs CAPCOM Fighting Collection** (MvC2). It gives your characters custom color skins that apply **live, in real matches** — no game-file edits, no relaunching. With **Live Sync** on, it also tracks a live leaderboard and your match stats automatically.

---

## 1. What you need

- **Windows 10/11**
- The **MARVEL vs CAPCOM Fighting Collection** on Steam (you play MvC2 from inside it)
- That's it — no accounts, no ROM files, no setup. (WebView2 auto-installs if you don't have it.)

## 2. Install (2 minutes)

1. Go to the **Releases page** and download the latest installer:
   **https://github.com/t3chnicallyinclined/mvc2-metasync/releases/latest**
   (grab the `MetaSync_x.y.z_x64-setup.exe` asset).
2. Run it. Windows SmartScreen may warn on a new app — **More info → Run anyway**.
3. Launch **MetaSync** from the Start menu.

> **Updates are automatic.** When a new build ships, the app tells you on launch — click **Install & restart**. You can also check any time by clicking the **version tag** in the top-left header.

## 3. Live Sync vs. offline

The first time you turn on **Live Sync**, MetaSync asks you to agree once. With it on, you get **leaderboards, player sync, and stats**, and your match data (tied to your Steam ID) syncs to power them. You can use MetaSync **offline** — skins and the live overlay still work — but leaderboards/sync/stats are off. Turn Live Sync off any time to stop syncing.

## 4. Using it (the fun part)

1. Launch **MetaSync**, then launch the game and start a match (ranked or a lobby).
2. The app detects **your team** and **your opponent** automatically and shows a card for each character.
3. Click a character card → pick a skin (or hit the 🎲 to roll a random one). Your pick applies **live** and re-applies every round.
4. Want your own colors? On the **Library** tab, open a character and hit **🎨 Recolor** — click any palette color to change it, then **Apply live**, **Save**, or **Bake**.
5. After games (Live Sync on), your **stats post to the leaderboard** automatically. Open the **Ranks** tab; click any name to see their profile, team comps, and recent matches.

## 5. What we most want you to test

- **Skins apply correctly** — right character, right side (your P1/P2), and they hold across rounds. (In a same-character mirror, your skin should show on **your** side only.)
- **Opponent + side detection** — does the app lock onto the correct opponent and put *you* on the correct side from the start?
- **Auto-update** — did you get an update prompt on a new build, and did **Install & restart** work?
- **Leaderboard & profiles** — do your wins/stats show up after a set? Do profiles look right?
- **Recolor tool** — does changing/saving/applying a palette work as expected?
- **Anything that looks broken** — blank cards, wrong/missing colors, freezes, crashes.

## 6. Good to know (so it's not surprising)

- Skins are **purely cosmetic** — they never affect gameplay.
- An opponent only sees **your** skins if they're **also running the app**. Otherwise you see your skins locally and can preview theirs.
- Skins lock in at **round start**; if the very first moment of a round looks stock for a frame, that's normal.
- Palette **effects** (Rainbow/Strobe/etc.) are **local only** — they animate on your screen, not for other players.
- Identity is your **Steam ID** — no login. Your profile, skins, and match history are saved to it.

## 7. Reporting a bug (this helps a ton)

Post in the beta feedback channel with:

1. **What you did** and **what happened vs. what you expected** (a line or two is fine).
2. A **screenshot** if it's visual (wrong colors, a blank card, the leaderboard).
3. Your **version** (from the header) and roughly when it happened.

## 8. Privacy & safety

- The app reads game memory **read-only** to know the live match state (who's fighting, health, round score).
- The **only** thing it writes to the game is your chosen character **color palette**, in the game's render buffer — nothing on disk, no game files touched (unless *you* choose **Bake**, which patches your local files and makes a `.bak` first).
- To paint skins at round start it loads a small render hook into the game (its own component, shipped inside the app).
- No login. With Live Sync on, your **public Steam ID** and match/stat data sync to the leaderboards — see the in-app **Terms & Privacy**.

---

*Beta build — expect rough edges, and thank you for helping shape it. 🎮*
