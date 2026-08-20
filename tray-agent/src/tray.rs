// Tray shell — the agent's only UI. No window: a tray icon + a native context menu, pumped by a tao event
// loop. Menu:
//   • status line (disabled)   — "MetaSync — starting…" placeholder (T2 will make it live)
//   • "Open MetaSync"          — opens the web app (config::WEB_APP) in the default browser
//   • ── separator ──
//   • "Start with Windows" (✓) — checkable; toggles the HKCU Run-key autostart (autostart.rs)
//   • "Quit"                   — exits the event loop cleanly (process ends)
//
// Integration pattern (canonical for tao + tray-icon on Windows): route tray + menu events through the event
// loop's own user-event channel via set_event_handler → EventLoopProxy, and build the TrayIcon on
// StartCause::Init (some platforms require the tray to be created after the loop is running).

use crate::{autostart, config};
use muda::{CheckMenuItem, Menu, MenuEvent, MenuId, MenuItem, PredefinedMenuItem};
use tao::event::{Event, StartCause};
use tao::event_loop::{ControlFlow, EventLoopBuilder};
use tray_icon::{Icon, TrayIcon, TrayIconBuilder, TrayIconEvent};

/// Events funneled into the tao loop from the tray + menu global handlers.
enum UserEvent {
    Menu(MenuEvent),
    #[allow(dead_code)] // tray-click handling is a T2 concern; kept wired so the channel exists now.
    Tray(TrayIconEvent),
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
    open_id: MenuId,
    autostart_id: MenuId,
    quit_id: MenuId,
    autostart_item: CheckMenuItem,
}

/// Build the context menu and return it alongside the handles the event loop needs. The status line is a
/// disabled MenuItem placeholder (T2 will update its text to live match/skin status).
fn build_menu() -> (Menu, MenuHandles) {
    let menu = Menu::new();

    let status = MenuItem::new("MetaSync — starting…", false, None);
    let open = MenuItem::new("Open MetaSync", true, None);
    let sep = PredefinedMenuItem::separator();
    let autostart_item =
        CheckMenuItem::new("Start with Windows", true, autostart::is_enabled(), None);
    let quit = MenuItem::new("Quit", true, None);

    // append_items keeps the ordering explicit; ignore the (infallible-in-practice) result.
    let _ = menu.append_items(&[&status, &open, &sep, &autostart_item, &quit]);

    let handles = MenuHandles {
        open_id: open.id().clone(),
        autostart_id: autostart_item.id().clone(),
        quit_id: quit.id().clone(),
        autostart_item,
    };
    (menu, handles)
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

    // Built on Init and held for the whole run (dropping a TrayIcon removes it from the tray).
    let mut tray: Option<TrayIcon> = None;
    let (menu, handles) = build_menu();
    // Menu is moved into the tray builder on Init; keep it in an Option until then.
    let mut menu = Some(menu);

    event_loop.run(move |event, _target, control_flow| {
        *control_flow = ControlFlow::Wait;

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
                    }
                }
            }

            Event::UserEvent(UserEvent::Tray(_ev)) => {
                // TODO(T2): left-click could open the web app; right-click already shows the menu natively.
            }

            _ => {}
        }
    })
}
