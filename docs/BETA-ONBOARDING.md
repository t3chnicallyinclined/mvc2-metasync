# MvC Skin Suite — Beta Tester Guide

Thanks for testing! **MvC Skin Suite** is a companion app for the Steam **MARVEL vs CAPCOM Fighting Collection** (MvC2). It gives your characters custom color skins that apply **live, in real matches** — no ROM edits, no relaunching. It also tracks a live leaderboard and your match stats automatically.

---

## 1. What you need

- **Windows 10/11**
- The **MARVEL vs CAPCOM Fighting Collection** on Steam (you play MvC2 from inside it)
- That's it — no accounts, no ROM files, no setup. (WebView2 auto-installs if you don't have it.)

## 2. Install (2 minutes)

1. Download the installer: **https://nobd.net/skinsync/update/MvC-Skin-Suite_0.1.2_x64-setup.exe**
2. Run it. Windows SmartScreen may warn on a new app — **More info → Run anyway**.
3. Launch **MvC Skin Suite** from the Start menu.

> **Updates are automatic.** When a new build ships, the app tells you on launch — click **Install & restart**. You can also check any time by clicking the **build tag** (top-left, e.g. `build gs-78`).

## 3. Using it (the fun part)

1. Launch **MvC Skin Suite**, then launch the game and start a match (ranked or a lobby).
2. The app detects **your team** and **your opponent** automatically and shows a card for each character.
3. Click a character card → pick a skin (or hit the 🎲 to roll a random one). Your pick applies **live** and re-applies every round.
4. Preview an opponent skin the same way — it's a local preview until you confirm it.
5. After games, your **stats post to the leaderboard** automatically. Open the **Ranks** tab; click any name to see their profile, team comps, and recent matches.

## 4. What we most want you to test

- **Skins apply correctly** — right character, right side (your P1/P2), and they hold across rounds.
- **Opponent + side detection** — does the app lock onto the correct opponent, and put *you* on the correct side, from the start of the match?
- **Auto-update** — did you get the 0.1.2 update prompt, and did **Install & restart** work? Try clicking the build tag to check on demand.
- **Leaderboard & profiles** — do your wins/stats show up after a set? Do profiles look right?
- **Anything that looks broken** — blank cards, wrong/missing colors, freezes, crashes.

## 5. Good to know (so it's not surprising)

- Skins are **purely cosmetic** — they never affect gameplay.
- An opponent only sees **your** skins if they're **also running the app**. Otherwise you see your skins locally and can preview theirs.
- Skins lock in at **round start**; if the very first moment of a round looks stock for a frame, that's normal.
- Identity is your **Steam ID** — no login. Your profile, skins, and match history are saved to it.

## 6. Reporting a bug (this helps a ton)

Post in **`<< your beta feedback channel — e.g. #beta-feedback in the NOBD Discord >>`** with:

1. **What you did** and **what happened vs. what you expected** (one or two lines is fine).
2. A **screenshot** if it's visual (wrong colors, a blank card, the leaderboard).
3. **The log file** — attach `C:\g\suite_trace.log`. This records exactly what the app saw during your match and is the single most useful thing for fixing an issue.
4. Your **build tag** (from the header, e.g. `gs-78`).

## 7. Privacy & safety

- The app reads game memory **read-only** to know the live match state (who's fighting, health, round score).
- The **only** thing it writes is your chosen character **color palette**, in the game's render buffer — nothing on disk, no game files touched.
- To paint skins at round start it loads a small render hook into the game (its own component, shipped inside the app).
- No login and no personal data — just your public Steam ID and the cosmetic/stat data above.

---

*Beta build — expect rough edges, and thank you for helping shape it. 🎮*
