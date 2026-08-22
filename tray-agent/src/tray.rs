// Tray shell — the agent's only UI. No window: a tray icon + a native context menu, pumped by a tao event
// loop. Production menu:
//   • "MetaSync Agent · v{VERSION}"  (disabled header)
//   • "🎮 {status}"                  (disabled; reader::status_line(), refreshed on the 1s timer)
//   • "Signed in as {name}"          (disabled; reader::signed_in_name(), "Steam not detected" when none)
//   • "🎛 HOST MODE — …"            (disabled; blank unless HOST_MODE — "don't play on this machine" banner)
//   • ── separator ──
//   • "Open MetaSync"                — opens the web app (config::WEB_APP) in the default browser
//   • "Apply my skins" (✓)          — checkable, PERSISTED pref; gates the painter (painter::SKINS_ENABLED)
//   • "Pause reporting" (✓)          — checkable, session-only; gates the reader's reports (reader::PAUSED)
//   • "Host lobbies (this machine)" (✓) — checkable, PERSISTED; LINUX-ONLY (greyed on Windows); shells out to
//                                     the arcade_hostd.sh daemon (host.rs) to register/unregister this host
//   • ── separator ──
//   • "Check for updates"            — runs updater::check_for_update on a thread; result reflected in the text
//   • "Open logs folder"            — opens runtime_dir() in Explorer
//   • "Start with Windows" (✓)       — checkable; toggles the HKCU Run-key autostart (autostart.rs)
//   • ── separator ──
//   • "Quit"                         — exits the event loop cleanly (process ends)
//
// Integration pattern (canonical for tao + tray-icon on Windows): route tray + menu events through the event
// loop's own user-event channel via set_event_handler → EventLoopProxy, and build the TrayIcon on
// StartCause::Init (some platforms require the tray to be created after the loop is running).
//
// NOTE on the "Check for updates" text update: muda's MenuItem is Rc<RefCell<…>>-backed (NOT Send), so the item
// handle can't cross into the worker thread. The check runs on a background thread and posts its result string
// back through the EventLoopProxy (UserEvent::UpdateResult); the loop — on the main thread, which owns the item —
// applies set_text. This is the proxy path the task allowed, and here it's also the only sound one.

use crate::{autostart, config, host, painter, prefs, reader, updater};
use muda::{CheckMenuItem, Menu, MenuEvent, MenuId, MenuItem, PredefinedMenuItem};
use std::sync::atomic::Ordering;
use std::time::{Duration, Instant};
use tao::event::{Event, StartCause};
use tao::event_loop::{ControlFlow, EventLoopBuilder};
use tray_icon::{Icon, TrayIcon, TrayIconBuilder, TrayIconEvent};

/// Events funneled into the tao loop from the tray + menu global handlers.
enum UserEvent {
    Menu(MenuEvent),
    #[allow(dead_code)] // tray-click handling is a later concern; kept wired so the channel exists now.
    Tray(TrayIconEvent),
    /// The finished "Check for updates" result string, posted back from the worker thread so the main thread
    /// (which owns the Rc-backed menu item) can set its text.
    UpdateResult(String),
}

/// Draw a 32×32 gold square with a dark border and a simple "M" — an in-code RGBA icon so the agent needs no
/// external asset file. Not art; just a recognizable tray mark for the scaffold.
fn build_icon() -> Option<Icon> {
    const N: usize = 32;
    let gold = [212u8, 175, 55, 255];
    let ink = [40u8, 30, 10, 255];
    let mut rgba = vec![0u8; N * N * 4];
    let put = |rgba: &mut [u8], x: usize, y: usize, c: [u8; 4]| {
        let i = (y * N + x) * 4;
        rgba[i..i + 4].copy_from_slice(&c);
    };
    for y in 0..N {
        for x in 0..N {
            // 2px dark border, gold fill inside.
            let border = !(2..N - 2).contains(&x) || !(2..N - 2).contains(&y);
            put(&mut rgba, x, y, if border { ink } else { gold });
        }
    }
    // A crude "M": two vertical legs + two inner diagonals, in ink over the gold.
    for y in 8..24 {
        put(&mut rgba, 8, y, ink);
        put(&mut rgba, 9, y, ink);
        put(&mut rgba, 22, y, ink);
        put(&mut rgba, 23, y, ink);
    }
    for k in 0..8 {
        put(&mut rgba, 10 + k, 8 + k, ink);
        put(&mut rgba, 21 - k, 8 + k, ink);
    }
    Icon::from_rgba(rgba, N as u32, N as u32).ok()
}

/// Handles to the menu items whose IDs we react to / whose state we mutate.
struct MenuHandles {
    // Clickable / checkable item IDs (matched against incoming MenuEvents).
    open_id: MenuId,
    apply_skins_id: MenuId,
    pause_id: MenuId,
    host_id: MenuId,
    updates_id: MenuId,
    logs_id: MenuId,
    autostart_id: MenuId,
    quit_id: MenuId,
    // Item handles whose state/text we mutate at runtime.
    apply_skins_item: CheckMenuItem,
    pause_item: CheckMenuItem,
    host_item: CheckMenuItem,
    autostart_item: CheckMenuItem,
    updates_item: MenuItem,
    // Disabled rows refreshed each second from the reader.
    status_item: MenuItem,
    signed_item: MenuItem,
    // Disabled banner row: shows the "don't play on this machine" warning while HOST_MODE is on, else blank.
    host_indicator: MenuItem,
}

/// "Signed in as {name}" / "Steam not detected" — the identity row text, sourced from the reader.
fn signed_in_text() -> String {
    match reader::signed_in_name() {
        Some(n) => format!("Signed in as {}", n),
        None => "Steam not detected".into(),
    }
}

/// The HOST MODE banner text: a loud "don't play here" warning while hosting is active, else "" (blank row).
/// A host box must NOT be played on (same Steam account can't host AND play), so this stays prominent.
fn host_indicator_text() -> String {
    if host::HOST_MODE.load(Ordering::Relaxed) {
        "🎛 HOST MODE — don't play on this machine".into()
    } else {
        String::new()
    }
}

/// Build the context menu and return it alongside the handles the event loop needs. The status + "signed in"
/// rows are disabled MenuItems whose text the event loop refreshes from the reader on a 1s timer.
fn build_menu() -> (Menu, MenuHandles) {
    let menu = Menu::new();

    let header = MenuItem::new(format!("MetaSync Agent · v{}", config::VERSION), false, None);
    let status = MenuItem::new(reader::status_line(), false, None);
    let signed = MenuItem::new(signed_in_text(), false, None);
    // Prominent, disabled banner shown only while this box is a host. Blank (empty row) otherwise; text is
    // (re)set by refresh_dynamic. HOST_MODE was reconciled from the live service in main() before this runs.
    let host_indicator = MenuItem::new(host_indicator_text(), false, None);
    let sep1 = PredefinedMenuItem::separator();

    let open = MenuItem::new("Open MetaSync", true, None);
    // Initial check states read the flags main.rs already restored (skins) / the process default (pause).
    let apply_skins = CheckMenuItem::new(
        "Apply my skins",
        true,
        painter::SKINS_ENABLED.load(Ordering::Relaxed),
        None,
    );
    let pause = CheckMenuItem::new("Pause reporting", true, reader::PAUSED.load(Ordering::Relaxed), None);
    // "Host lobbies (this machine)" — makes this box an arcade/tournament host node. LINUX-ONLY: on Windows
    // it's created DISABLED (greyed) with a "Linux only" label, since auto-hosting isn't supported there yet.
    // Initial check state = HOST_MODE, which main() reconciled from the live systemd --user service at startup.
    #[cfg(target_os = "linux")]
    let host_toggle = CheckMenuItem::new(
        "Host lobbies (this machine)",
        true,
        host::HOST_MODE.load(Ordering::Relaxed),
        None,
    );
    #[cfg(not(target_os = "linux"))]
    let host_toggle = CheckMenuItem::new("Host lobbies — Linux only (Windows soon)", false, false, None);
    let sep2 = PredefinedMenuItem::separator();

    let updates = MenuItem::new("Check for updates", true, None);
    let logs = MenuItem::new("Open logs folder", true, None);
    let autostart_item = CheckMenuItem::new("Start with Windows", true, autostart::is_enabled(), None);
    let sep3 = PredefinedMenuItem::separator();

    let quit = MenuItem::new("Quit", true, None);

    // append_items keeps the ordering explicit; ignore the (infallible-in-practice) result. The menu holds an
    // Rc clone of each item, so the un-kept locals (header/separators) stay alive after this fn returns.
    let _ = menu.append_items(&[
        &header,
        &status,
        &signed,
        &host_indicator,
        &sep1,
        &open,
        &apply_skins,
        &pause,
        &host_toggle,
        &sep2,
        &updates,
        &logs,
        &autostart_item,
        &sep3,
        &quit,
    ]);

    let handles = MenuHandles {
        open_id: open.id().clone(),
        apply_skins_id: apply_skins.id().clone(),
        pause_id: pause.id().clone(),
        host_id: host_toggle.id().clone(),
        updates_id: updates.id().clone(),
        logs_id: logs.id().clone(),
        autostart_id: autostart_item.id().clone(),
        quit_id: quit.id().clone(),
        apply_skins_item: apply_skins,
        pause_item: pause,
        host_item: host_toggle,
        autostart_item,
        updates_item: updates,
        status_item: status,
        signed_item: signed,
        host_indicator,
    };
    (menu, handles)
}

/// Pull the current status + identity from the reader and paint them onto the disabled rows + the tray tooltip.
/// Also reflects a downloaded-and-waiting update (updater::PENDING_UPDATE) on the "Check for updates" row + the
/// tooltip. `updates_busy_until` is the instant a transient manual-check message ("Checking…" / "Up to date" /
/// a result) stays pinned to the row — while it's in the future we leave that row alone so this 1s refresh
/// doesn't stomp the manual feedback.
fn refresh_dynamic(handles: &MenuHandles, tray: &Option<TrayIcon>, updates_busy_until: Option<Instant>) {
    let line = reader::status_line();
    handles.status_item.set_text(&line);
    handles.signed_item.set_text(signed_in_text());
    handles.host_indicator.set_text(host_indicator_text());

    // A newer version that couldn't auto-apply (MvC2 open) surfaces here: the menu row + tooltip tell the user
    // it's waiting and will install when they close the game. When nothing is pending the row keeps its normal
    // "Check for updates" label.
    let pending = updater::PENDING_UPDATE.lock().ok().and_then(|p| p.clone());
    let show_transient = updates_busy_until.map_or(false, |t| Instant::now() < t);
    if !show_transient {
        match &pending {
            Some(v) => handles
                .updates_item
                .set_text(format!("🔔 Update {v} ready — installs when you close the game")),
            None => handles.updates_item.set_text("Check for updates"),
        }
    }

    let tooltip = match &pending {
        Some(v) => format!("🔔 Update {v} ready — installs when you close MvC2\n{line}"),
        None => line,
    };
    if let Some(t) = tray {
        let _ = t.set_tooltip(Some(&tooltip));
    }
}

/// Build the event loop, wire tray/menu event routing, and run it. Diverges: returns only when the process
/// exits (Quit → ControlFlow::Exit → tao ends the process).
pub fn run() -> ! {
    let event_loop = EventLoopBuilder::<UserEvent>::with_user_event().build();

    // Route the two global (thread-static) event streams into our loop via the proxy.
    let proxy = event_loop.create_proxy();
    MenuEvent::set_event_handler(Some(move |e| {
        let _ = proxy.send_event(UserEvent::Menu(e));
    }));
    let proxy = event_loop.create_proxy();
    TrayIconEvent::set_event_handler(Some(move |e| {
        let _ = proxy.send_event(UserEvent::Tray(e));
    }));
    // A third proxy, cloned into each "Check for updates" worker so it can post its result back to the loop.
    let update_proxy = event_loop.create_proxy();

    // Built on Init and held for the whole run (dropping a TrayIcon removes it from the tray).
    let mut tray: Option<TrayIcon> = None;
    let (menu, handles) = build_menu();
    // Menu is moved into the tray builder on Init; keep it in an Option until then.
    let mut menu = Some(menu);
    // While in the future, a transient manual-check message ("Checking…" / "Up to date" / a result) is pinned
    // to the "Check for updates" row and the 1s refresh leaves that row alone. Captured (mutably) by the loop
    // closure so it persists across ticks; set by the manual-check arm + UpdateResult below.
    let mut updates_busy_until: Option<Instant> = None;

    event_loop.run(move |event, _target, control_flow| {
        // Wake at least once a second so the status + identity rows + tooltip track the reader's live state,
        // even when there are no window/menu events to process.
        *control_flow = ControlFlow::WaitUntil(Instant::now() + Duration::from_secs(1));

        match event {
            Event::NewEvents(StartCause::Init) => {
                let mut builder = TrayIconBuilder::new()
                    .with_tooltip(format!("MetaSync v{}", config::VERSION));
                if let Some(m) = menu.take() {
                    builder = builder.with_menu(Box::new(m));
                }
                if let Some(icon) = build_icon() {
                    builder = builder.with_icon(icon);
                }
                match builder.build() {
                    Ok(t) => tray = Some(t),
                    Err(e) => {
                        eprintln!("[tray] failed to create tray icon: {e}");
                        // No tray means no UI — nothing to do but exit cleanly.
                        *control_flow = ControlFlow::Exit;
                    }
                }
                refresh_dynamic(&handles, &tray, updates_busy_until);
            }

            // 1s timer tick (from WaitUntil above) — refresh the status + identity rows from the reader.
            Event::NewEvents(StartCause::ResumeTimeReached { .. }) => {
                refresh_dynamic(&handles, &tray, updates_busy_until);
            }

            Event::UserEvent(UserEvent::Menu(ev)) => {
                if ev.id == handles.quit_id {
                    // Drop the tray first so the icon disappears immediately, then exit the loop.
                    tray.take();
                    *control_flow = ControlFlow::Exit;
                } else if ev.id == handles.open_id {
                    if let Err(e) = open::that_detached(config::WEB_APP) {
                        eprintln!("[tray] failed to open {}: {e}", config::WEB_APP);
                    }
                } else if ev.id == handles.apply_skins_id {
                    // muda already flipped the check state; mirror it into the painter's gate + persist the pref.
                    let on = handles.apply_skins_item.is_checked();
                    painter::SKINS_ENABLED.store(on, Ordering::Relaxed);
                    prefs::save_apply_skins(on);
                } else if ev.id == handles.pause_id {
                    // Session-only: mirror the check state into the reader's report gate (not persisted).
                    let paused = handles.pause_item.is_checked();
                    reader::PAUSED.store(paused, Ordering::Relaxed);
                } else if ev.id == handles.host_id {
                    // muda already flipped the check state. ON → make this box a host (shell out to the daemon)
                    // + persist; OFF → stop hosting + persist. A REFUSED enable (Windows, or the host scripts
                    // aren't installed) must NOT leave the item showing ON — revert the checkbox so it never
                    // lies about the real host state, same as the autostart toggle below.
                    let want = handles.host_item.is_checked();
                    if want {
                        match host::host_enable() {
                            Ok(()) => {
                                host::HOST_MODE.store(true, Ordering::Relaxed);
                                prefs::save_host_mode(true);
                            }
                            Err(e) => {
                                eprintln!("[tray] host enable refused: {e}");
                                handles.host_item.set_checked(false);
                                host::HOST_MODE.store(false, Ordering::Relaxed);
                            }
                        }
                    } else {
                        host::HOST_MODE.store(false, Ordering::Relaxed);
                        prefs::save_host_mode(false);
                        host::host_disable();
                    }
                    // Reflect the HOST MODE banner immediately rather than waiting for the 1s tick.
                    refresh_dynamic(&handles, &tray, updates_busy_until);
                } else if ev.id == handles.updates_id {
                    // Check off-thread, then INSTALL if an update is offered and it's safe (no game running).
                    // Feedback comes back via UpdateResult (the menu item is Rc-backed → can't cross threads).
                    handles.updates_item.set_text("Checking…");
                    // Pin "Checking…" (and then the result) so the 1s refresh doesn't stomp it mid-check; the
                    // manifest fetch can take a few seconds. UpdateResult resets this to a shorter window.
                    updates_busy_until = Some(Instant::now() + Duration::from_secs(20));
                    let p = update_proxy.clone();
                    std::thread::spawn(move || {
                        match updater::check_for_update(config::VERSION) {
                            None => {
                                let _ = p.send_event(UserEvent::UpdateResult(format!(
                                    "Up to date (v{})",
                                    config::VERSION
                                )));
                                updater::notify(
                                    "MetaSync",
                                    &format!("You're on the latest version (v{}).", config::VERSION),
                                );
                            }
                            Some(u) if !updater::safe_to_apply() => {
                                // An update is ready but MvC2 is open — never swap mid-session. Raise a
                                // NON-MODAL toast (force=true: the user just asked) + record it as pending so
                                // the tray row/tooltip keep showing it; it auto-applies once the game closes.
                                // NO modal MessageBox here — it must not steal focus from a live match.
                                updater::note_deferred_update(&u.version, true);
                                let _ = p.send_event(UserEvent::UpdateResult(format!(
                                    "🔔 Update {} ready — installs when you close the game",
                                    u.version
                                )));
                            }
                            Some(u) => {
                                let _ = p.send_event(UserEvent::UpdateResult(format!(
                                    "Installing v{}…",
                                    u.version
                                )));
                                updater::notify(
                                    "MetaSync Update",
                                    &format!(
                                        "Installing update v{}…\n\nThe agent will restart when it's done.",
                                        u.version
                                    ),
                                );
                                match updater::apply_update(&u) {
                                    // self-replace done → relaunch the new binary (never returns)
                                    Ok(()) => updater::restart(),
                                    Err(e) => {
                                        let _ = p.send_event(UserEvent::UpdateResult(format!(
                                            "Update failed: {e}"
                                        )));
                                        updater::notify(
                                            "MetaSync Update",
                                            &format!("Update failed:\n\n{e}"),
                                        );
                                    }
                                }
                            }
                        }
                    });
                } else if ev.id == handles.logs_id {
                    if let Err(e) = open::that(crate::runtime_dir()) {
                        eprintln!("[tray] failed to open logs folder: {e}");
                    }
                } else if ev.id == handles.autostart_id {
                    // muda already toggled the check state for us; reconcile the registry to match, and if the
                    // write fails, revert the checkbox so it never lies about the real autostart state.
                    let want = handles.autostart_item.is_checked();
                    let res = if want {
                        autostart::enable()
                    } else {
                        autostart::disable()
                    };
                    if let Err(e) = res {
                        eprintln!("[tray] autostart toggle failed: {e}");
                        handles.autostart_item.set_checked(!want);
                    } else {
                        // record the explicit choice so the launch path honors it (and stops re-asserting the default).
                        prefs::save_autostart_choice(want);
                    }
                }
            }

            // "Check for updates" finished on its worker thread → reflect the result in the item text.
            Event::UserEvent(UserEvent::UpdateResult(text)) => {
                handles.updates_item.set_text(&text);
                // Keep this transient result visible briefly before the 1s refresh reclaims the row (steady
                // "Check for updates", or a pending-update hint if one is now waiting).
                updates_busy_until = Some(Instant::now() + Duration::from_secs(6));
            }

            Event::UserEvent(UserEvent::Tray(_ev)) => {
                // Left-click could open the web app; right-click already shows the menu natively.
            }

            _ => {}
        }
    })
}
