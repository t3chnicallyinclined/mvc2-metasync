// Live memory diagnostic — dumps exactly what read_my_lobby + the session flags see RIGHT NOW, so we can tell
// whether a stale lobby structure is being reported while the user sits on the menu.
//   cargo run --release --bin probe
use mvc_live_skins_lib::sync;

fn main() {
    // `probe watch` = 3-second palette-change watch (run it while triggering an effect); otherwise the normal dump.
    if std::env::args().any(|a| a == "watch") {
        println!("palette_watch = {}", sync::diag_palette_watch());
        return;
    }
    let self_ = sync::sync_self();
    let raw = sync::diag_raw();
    println!("diag_raw      = {}", raw);
    let lob = sync::read_my_lobby();
    let m = sync::tourney_match_read();
    let sess = sync::diag_session();
    println!("=== MvC MetaSync live probe ===");
    println!("self          = {}", self_);
    println!("read_my_lobby = {}", lob);
    println!("match_read    = {}", m);
    println!("diag_session  = {}", sess);
    println!("diag_dump     = {}", sync::diag_dump());
    println!("diag_palette  = {}", sync::diag_palette());
    // One-line verdict
    let in_lobby = lob.get("in_lobby").and_then(|v| v.as_bool()).unwrap_or(false);
    let members = lob.get("members").and_then(|v| v.as_array()).map(|a| a.len()).unwrap_or(0);
    let active = m.get("active").and_then(|v| v.as_i64()).unwrap_or(-1);
    println!("VERDICT: read_my_lobby says in_lobby={} members={} | session_active_flag={}", in_lobby, members, active);
}
