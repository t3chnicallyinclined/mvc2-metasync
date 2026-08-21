#!/usr/bin/env bash
# MetaSync tray agent — one-shot installer for Bazzite / Fedora Atomic (KDE Plasma or GNOME).
#
# Installs a native binary to ~/.local/bin (writable on an immutable OS — $HOME is not read-only), then
# launches it. On first run the agent writes its OWN XDG autostart entry (~/.config/autostart/…) so it starts
# at login, and shows a tray icon via the desktop's native StatusNotifier host (KDE Plasma hosts it out of the
# box; Bazzite's GNOME ships the AppIndicator extension). It self-updates thereafter from the signed Linux
# manifest (minisign-verified, atomic-rename replace) — no reinstall needed.
#
# Run it on your Bazzite box (in your desktop session so the tray can appear):
#   curl -fsSL https://nobd.net/skinsync/update/install-bazzite.sh | bash
set -euo pipefail

BIN_URL="https://github.com/t3chnicallyinclined/mvc2-metasync/releases/download/v0.3.0/metasync-agent-linux"
DEST="$HOME/.local/bin/metasync-agent"

echo "▶ MetaSync agent — Bazzite install"
mkdir -p "$HOME/.local/bin"

echo "  downloading…"
tmp="$(mktemp)"
curl -fL --progress-bar -o "$tmp" "$BIN_URL"
chmod +x "$tmp"

# Library sanity check — on a default KDE Bazzite desktop everything should resolve (gtk3 from the base,
# libxdo present, appindicator via the dlopen fallback to the host's libappindicator3). Warn if not.
if command -v ldd >/dev/null; then
  missing="$(ldd "$tmp" 2>/dev/null | grep 'not found' || true)"
  if [ -n "$missing" ]; then
    echo "  ⚠ missing libraries on this system — the tray may not appear:"
    echo "$missing" | sed 's/^/     /'
  fi
fi

# The agent reads the game's memory via process_vm_readv, which needs Yama ptrace_scope = 0 (Fedora's current
# default). If it's tightened, reading the game is blocked — tell the user how to relax it (needs sudo).
scope="$(cat /proc/sys/kernel/yama/ptrace_scope 2>/dev/null || echo 0)"
if [ "$scope" != "0" ]; then
  echo "  ⚠ kernel.yama.ptrace_scope=$scope — the agent needs 0 to read MvC2's memory. Set it (persists):"
  echo "      echo 'kernel.yama.ptrace_scope = 0' | sudo tee /etc/sysctl.d/10-ptrace.conf >/dev/null && sudo sysctl -w kernel.yama.ptrace_scope=0"
fi

# Atomic install into place (fresh inode — safe even if an old copy is running).
mv -f "$tmp" "$DEST"
echo "  installed → $DEST"

# Restart cleanly: stop any prior instance, then launch detached (first run registers autostart + tray icon).
pkill -x metasync-agent 2>/dev/null || true
sleep 0.5
nohup "$DEST" >/dev/null 2>&1 &
disown 2>/dev/null || true

sleep 1.5
if pgrep -x metasync-agent >/dev/null; then
  echo "✅ MetaSync is running — look for its icon in your system tray."
  echo "   It starts automatically at login now. Sign in at https://nobd.net/app to link your account."
else
  echo "❌ it didn't stay running. Launch it in a terminal to see the error:  $DEST"
fi
