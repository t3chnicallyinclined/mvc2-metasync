#!/usr/bin/env python3
"""play_session.py -- THE PLAYABLE LOOP: a human with a gamepad drives the real MvC2 frame function, and the
session is then rendered to real pixels through the already-gated pipeline.

    python play_session.py [--frames 600] [--run <anchor run>] [--pack <pack dir>]

What it chains, all of it previously gated, with exactly one new thing (the person):

  1. dcram_build.py        DC-RAM from the USER'S OWN arc, no memory dump            (GATE 3 / GATE 4)
  2. rr_runner --play      XInput/keyboard -> 2 pad words -> FUN_140118950, 60 Hz     (NEW: the human)
     --harvest-dump        per-tick blk + gs page + exe page + changed DC-RAM pages   (GATE 2)
  3. rr-tape               that memory -> a v5 tape                                   (GATE 2)
  4. player.html           tape -> WebGPU pixels                                      (L1 / L3, in production)

Pad map (CONFIRMED, docs/CONFIRMED-TAPE-AND-FLYR-REPLAY.md s5): gamepad X=LP Y=HP A=LK B=HK LB=A1 RB=A2,
d-pad or left stick = directions. No gamepad -> keyboard: arrows, Z=LP X=HP C=A1 A=LK S=HK D=A2.

BYOR: reads the user's own arc and exe image; every output is game-derived and lives under %TEMP% or the
gitignored pack dir.
"""
import argparse, json, os, shutil, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
Q = os.path.abspath(os.path.join(HERE, '..', '..'))
RUNNER = os.path.join(HERE, 'runner', 'rr_runner.exe')
RRTAPE = os.path.join(Q, '..', 'RetroReceipts-agent', 'agent', 'target', 'release', 'rr-tape.exe')
DEFAULT_RUN = os.path.join(Q, 'd3dcap', 'ttd', 'runs', 'receipt-20260903-stage9-anchor')
DEFAULT_PACK = os.path.join(Q, 'd3dcap', 'replay', 'packs', 'local_stage9')
SESSION = os.path.join(os.environ.get('TEMP', '.'), 'rr_play', 'session')


def sh(cmd, **kw):
    p = subprocess.run(cmd, capture_output=True, text=True, **kw)
    return p.returncode, p.stdout, p.stderr


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--frames', type=int, default=600, help='60 = 1 second')
    ap.add_argument('--run', default=DEFAULT_RUN)
    ap.add_argument('--pack', default=DEFAULT_PACK)
    ap.add_argument('--rr-tape', default=RRTAPE)
    ap.add_argument('--skip-build', action='store_true')
    ap.add_argument('--record', action='store_true',
                    help='capture a tape as you play. COSTS: the per-tick harvest is inline on the frame thread, '
                         'which takes p99 from 2.0 ms to 34.1 ms and max from 4.7 ms to 58.1 ms (measured, 600 '
                         'frames). Without it the loop holds a clean 60.1 fps but produces no pixels afterwards.')
    a = ap.parse_args()

    src = a.run if os.path.exists(os.path.join(a.run, 'meta.json')) else os.path.join(a.run, 'pre')
    pre = os.path.join(SESSION, 'pre')
    out = os.path.join(SESSION, 'out')
    os.makedirs(pre, exist_ok=True)
    os.makedirs(out, exist_ok=True)

    # 1. session images: everything from the anchor, DC-RAM rebuilt from the arc
    if not a.skip_build:
        for f in ('blk.bin', 'blk2.bin', 'ctx.bin', 'game_state.bin', 'meta.json', 'exe_image.bin'):
            s = os.path.join(src, f)
            d = os.path.join(pre, f)
            if os.path.exists(s) and (not os.path.exists(d) or os.path.getsize(s) != os.path.getsize(d)):
                shutil.copy2(s, d)
        print('[1/4] building DC-RAM from the arc (no memory dump) ...')
        rc, so, se = sh([sys.executable, os.path.join(HERE, 'dcram_build.py'), a.run,
                         '--out', os.path.join(pre, 'dcram.bin')])
        if rc != 0:
            sys.exit('dcram_build failed:\n' + so + se)
        print('      ' + [l for l in so.splitlines() if l.startswith('written')][-1])

    # 2. the human
    print('[2/4] PLAY -- %d frames (%.1f s) at 60 Hz. The window has no picture yet; press buttons.' % (a.frames, a.frames / 60.0))
    t0 = time.time()
    cmd = [RUNNER, '--pre', pre, '--out', out, '--play', '--play-frames', str(a.frames),
           '--dump-every', '0', '--no-dump-end', '--heap-mb', '1024']
    if a.record:
        cmd += ['--play-harvest', 'on', '--harvest-dump', '--dump-every', '1']
    rc = subprocess.call(cmd)
    play_wall = time.time() - t0
    if rc != 0:
        sys.exit('rr_runner --play failed (%d)' % rc)
    log = open(os.path.join(out, 'runner.log'), 'r', errors='replace').read()
    for line in log.splitlines():
        if any(k in line for k in ('PLAY DONE', 'FIRST INPUT', 'FIRST DIRECTION', 'STEERING', 'FIRST HUMAN-CAUSED',
                                   'NO INPUT', 'NO DIRECTION', 'pad: ')):
            print('      ' + line)

    if not a.record:
        print()
        print('[3/4] skipped: --record was not given, so no tape and no pixels. That is the clean-60 Hz mode.')
        print('      re-run with --record to produce something watchable (it costs the frame tail; see --help).')
        return
    # 3. the tape
    print('[3/4] harvesting the session into a tape ...')
    tape = os.path.join(out, 'tape.json.gz')
    t1 = time.time()
    rc, so, se = sh([a.rr_tape, '--pre', pre, '--ticks', out, '--n', str(a.frames), '-o', tape])
    tape_wall = time.time() - t1
    if rc != 0:
        sys.exit('rr-tape failed:\n' + so + se)
    print('      ' + so.strip().splitlines()[-1])

    # 4. hand it to the renderer
    dest = os.path.join(a.pack, 'play_tape.json.gz')
    shutil.copy2(tape, dest)
    rel = os.path.relpath(dest, os.path.join(Q, 'd3dcap', 'replay')).replace(os.sep, '/')
    packrel = os.path.relpath(a.pack, os.path.join(Q, 'd3dcap', 'replay')).replace(os.sep, '/')
    print('[4/4] rendered input ready.')
    print()
    print('  serve:  cd %s && python serve.py 8099' % os.path.join(Q, 'd3dcap', 'replay'))
    print('  watch:  http://127.0.0.1:8099/player.html?tape=%s&pack=%s&auto=1' % (rel, packrel))
    print()
    print('  play wall %.1f s for %d frames (%.1f fps) ; harvest+tape %.1f s' % (play_wall, a.frames, a.frames / play_wall, tape_wall))


if __name__ == '__main__':
    main()
