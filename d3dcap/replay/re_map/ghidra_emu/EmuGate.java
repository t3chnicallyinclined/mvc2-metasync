// EmuGate.java -- run one Steam MvC2 function in Ghidra's p-code emulator over a captured memory state.
//
// Driven by d3dcap/replay/emu_gate.py through analyzeHeadless (-process, -noanalysis, -readOnly):
//   analyzeHeadless <projdir> emuproj -process mvc_dump.bin -noanalysis -readOnly
//        -scriptPath <this dir> -postScript EmuGate.java <job.txt>
//
// The program is the raw dump (BinaryLoader @ 0x140000000): every byte of the image -- code, float
// constants, the runtime-built sin/cos tables and the LIVE values of the globals at dump time --
// is the emulator's backing store. Anything the job does not write and the image does not cover is
// an UNINITIALISED read: it is zero-filled AND LOGGED, so the result file lists exactly which
// memory had to be synthesised. That list is a deliverable, not noise.
//
// job.txt -- one command per line, executed IN ORDER (so a job can run a prologue routine, patch
// memory, then run the target):
//   mem   <hexaddr> <file>            write the file's bytes at addr
//   set4  <hexaddr> <hex32>           write a u32 (little endian)
//   set8  <hexaddr> <hex64>           write a u64
//   fill  <hexaddr> <hexlen>          write zeros (marks a region as provided, e.g. the stack)
//   reg   <name> <hex>                set a register
//   stack <hexaddr> <hexsize>         stack region; RSP is placed near the top before each run
//   stub  <hexaddr> <name> <hexrax>   when PC reaches addr: RAX = value, emulate RET (no body executed)
//   stubmap <hexaddr> <name> <file>   like stub but RAX is looked up by RCX (file lines "<rcx-hex> <rax-hex>")
//   mathhook <hexaddr> tanf|atanf|sinf|cosf|sqrtf   replace a CRT float routine by Java Math (only if asked)
//   maxsteps <n>                      step cap per run (default 5,000,000)
//   run   <hexaddr>                   call the function at addr (pushes a sentinel return address) and
//                                     execute until it returns, a stub misfires, an error, or the cap
//   dump  <hexaddr> <hexlen> <file>   read emulator memory to a file
//   out   <file>                      result file (status / steps / error / uninit ranges / stub hits)
import ghidra.app.script.GhidraScript;
import ghidra.app.emulator.EmulatorHelper;
import ghidra.pcode.memstate.MemoryFaultHandler;
import ghidra.program.model.address.Address;
import java.io.*;
import java.math.BigInteger;
import java.nio.file.*;
import java.util.*;

public class EmuGate extends GhidraScript {

    static final long SENTINEL = 0x140000000L;   // the MZ header: never a real return target

    static class Stub { String name; long rax; boolean useMap; Map<Long, Long> map; String math; }

    EmulatorHelper emu;
    TreeMap<Long, Long> uninit = new TreeMap<>();      // start -> end (exclusive), coalesced
    TreeMap<Long, Long> unknown = new TreeMap<>();
    List<String> stubHits = new ArrayList<>();
    List<String> log = new ArrayList<>();
    Map<Long, Stub> stubs = new HashMap<>();
    long maxSteps = 5000000L;
    long stackBase = 0x10000000L, stackSize = 0x100000L;
    String outPath = null;

    Address A(long v) { return currentProgram.getAddressFactory().getDefaultAddressSpace().getAddress(v); }

    void addRange(TreeMap<Long, Long> m, long a, long n) {
        long e = a + n;
        Map.Entry<Long, Long> lo = m.floorEntry(a);
        if (lo != null && lo.getValue() >= a) { a = lo.getKey(); e = Math.max(e, lo.getValue()); m.remove(lo.getKey()); }
        Map.Entry<Long, Long> hi;
        while ((hi = m.ceilingEntry(a)) != null && hi.getKey() <= e) { e = Math.max(e, hi.getValue()); m.remove(hi.getKey()); }
        m.put(a, e);
    }

    long rd64(long addr) {
        byte[] b = emu.readMemory(A(addr), 8);
        long v = 0;
        for (int i = 7; i >= 0; i--) v = (v << 8) | (b[i] & 0xffL);
        return v;
    }

    void wr64(long addr, long v) {
        byte[] b = new byte[8];
        for (int i = 0; i < 8; i++) { b[i] = (byte) (v & 0xff); v >>>= 8; }
        emu.writeMemory(A(addr), b);
    }

    void wr32(long addr, long v) {
        byte[] b = new byte[4];
        for (int i = 0; i < 4; i++) { b[i] = (byte) (v & 0xff); v >>>= 8; }
        emu.writeMemory(A(addr), b);
    }

    long reg(String n) { return emu.readRegister(n).longValue(); }
    void setReg(String n, long v) { emu.writeRegister(n, new BigInteger(Long.toUnsignedString(v))); }

    float xmm0f() {
        BigInteger v = emu.readRegister("XMM0");
        return Float.intBitsToFloat(v.intValue());
    }
    void setXmm0f(float f) {
        emu.writeRegister("XMM0", BigInteger.valueOf(Float.floatToRawIntBits(f) & 0xffffffffL));
    }

    // emulate RET: pop the return address into RIP
    void doRet() {
        long rsp = reg("RSP");
        long ret = rd64(rsp);
        setReg("RSP", rsp + 8);
        setReg("RIP", ret);
    }

    String runOnce(long entry) {
        long rsp = stackBase + stackSize - 0x1000 - 8;   // entry state: RSP == 8 (mod 16), as after a CALL
        setReg("RSP", rsp);
        wr64(rsp, SENTINEL);
        setReg("RIP", entry);
        long steps = 0;
        long t0 = System.currentTimeMillis();
        while (true) {
            long pc = emu.getExecutionAddress().getOffset();
            if (pc == SENTINEL) return "ok steps=" + steps + " ms=" + (System.currentTimeMillis() - t0);
            Stub s = stubs.get(pc);
            if (s != null) {
                long rcx = reg("RCX");
                if (s.math != null) {
                    float x = xmm0f();
                    double r;
                    switch (s.math) {
                        case "tanf": r = Math.tan(x); break;
                        case "atanf": r = Math.atan(x); break;
                        case "sinf": r = Math.sin(x); break;
                        case "cosf": r = Math.cos(x); break;
                        case "sqrtf": r = Math.sqrt(x); break;
                        default: return "error unknown math hook " + s.math;
                    }
                    setXmm0f((float) r);
                    stubHits.add(String.format("mathhook %x %s in=%.9g out=%.9g", pc, s.name, x, (float) r));
                } else {
                    long rax = s.rax;
                    if (s.useMap) {
                        Long v = s.map.get(rcx);
                        if (v == null) { stubHits.add(String.format("stubmiss %x %s rcx=%x", pc, s.name, rcx)); rax = 0; }
                        else rax = v;
                    }
                    setReg("RAX", rax);
                    stubHits.add(String.format("stubhit %x %s rcx=%x rax=%x", pc, s.name, rcx, rax));
                }
                doRet();
                continue;
            }
            if (steps >= maxSteps) return "error step cap " + maxSteps + " at pc=" + Long.toHexString(pc);
            boolean ok;
            try {
                ok = emu.step(monitor);
            } catch (Exception e) {
                return "error exception at pc=" + Long.toHexString(pc) + " steps=" + steps + " : " + e;
            }
            steps++;
            if (!ok) return "error at pc=" + Long.toHexString(pc) + " steps=" + steps + " : " + emu.getLastError();
        }
    }

    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length < 1) { printerr("usage: EmuGate.java <job.txt>"); return; }
        List<String> lines = Files.readAllLines(Paths.get(args[0]));
        emu = new EmulatorHelper(currentProgram);
        emu.setMemoryFaultHandler(new MemoryFaultHandler() {
            @Override public boolean uninitializedRead(Address address, int size, byte[] buf, int bufOffset) {
                addRange(uninit, address.getOffset(), size);
                return true;      // zero-filled, execution continues
            }
            @Override public boolean unknownAddress(Address address, boolean write) {
                addRange(unknown, address.getOffset(), 1);
                return true;
            }
        });
        List<String> results = new ArrayList<>();
        for (String raw : lines) {                       // pre-scan so an aborted run still reports
            String[] t = raw.trim().split("\s+");
            if (t.length == 2 && t[0].equals("out")) outPath = t[1];
        }
        try {
            for (String raw : lines) {
                String ln = raw.trim();
                if (ln.isEmpty() || ln.startsWith("#")) continue;
                String[] t = ln.split("\\s+");
                switch (t[0]) {
                    case "mem": {
                        byte[] b = Files.readAllBytes(Paths.get(t[2]));
                        emu.writeMemory(A(Long.parseUnsignedLong(t[1], 16)), b);
                        log.add("mem " + t[1] + " " + b.length + " bytes"); break; }
                    case "set4": wr32(Long.parseUnsignedLong(t[1], 16), Long.parseUnsignedLong(t[2], 16)); break;
                    case "set8": wr64(Long.parseUnsignedLong(t[1], 16), Long.parseUnsignedLong(t[2], 16)); break;
                    case "fill": {
                        long a = Long.parseUnsignedLong(t[1], 16); int n = (int) Long.parseUnsignedLong(t[2], 16);
                        emu.writeMemory(A(a), new byte[n]); break; }
                    case "reg": setReg(t[1], Long.parseUnsignedLong(t[2], 16)); break;
                    case "stack": stackBase = Long.parseUnsignedLong(t[1], 16); stackSize = Long.parseUnsignedLong(t[2], 16);
                        emu.writeMemory(A(stackBase), new byte[(int) stackSize]); break;
                    case "stub": { Stub s = new Stub(); s.name = t[2]; s.rax = Long.parseUnsignedLong(t[3], 16);
                        stubs.put(Long.parseUnsignedLong(t[1], 16), s); break; }
                    case "stubmap": { Stub s = new Stub(); s.name = t[2]; s.useMap = true; s.map = new HashMap<>();
                        for (String m : Files.readAllLines(Paths.get(t[3]))) {
                            String[] kv = m.trim().split("\\s+");
                            if (kv.length == 2) s.map.put(Long.parseUnsignedLong(kv[0], 16), Long.parseUnsignedLong(kv[1], 16));
                        }
                        stubs.put(Long.parseUnsignedLong(t[1], 16), s); break; }
                    case "mathhook": { Stub s = new Stub(); s.name = t[2]; s.math = t[2];
                        stubs.put(Long.parseUnsignedLong(t[1], 16), s); break; }
                    case "maxsteps": maxSteps = Long.parseLong(t[1]); break;
                    case "run": {
                        String r = runOnce(Long.parseUnsignedLong(t[1], 16));
                        results.add("run " + t[1] + " " + r);
                        println("run " + t[1] + " -> " + r);
                        if (r.startsWith("error")) { results.add("aborted"); throw new RuntimeException(r); }
                        break; }
                    case "dump": {
                        long a = Long.parseUnsignedLong(t[1], 16); int n = (int) Long.parseUnsignedLong(t[2], 16);
                        byte[] b = emu.readMemory(A(a), n);
                        Files.write(Paths.get(t[3]), b);
                        results.add("dump " + t[1] + " " + t[2] + " " + t[3]); break; }
                    case "out": outPath = t[1]; break;
                    default: results.add("ignored: " + ln);
                }
            }
            results.add("status ok");
        } catch (Exception e) {
            results.add("status error " + e);
        } finally {
            if (outPath != null) {
                try (PrintWriter w = new PrintWriter(new FileWriter(outPath))) {
                    for (String s : results) w.println(s);
                    for (String s : log) w.println(s);
                    for (String s : stubHits) w.println(s);
                    for (Map.Entry<Long, Long> e : uninit.entrySet())
                        w.println(String.format("uninit %x %x", e.getKey(), e.getValue() - e.getKey()));
                    for (Map.Entry<Long, Long> e : unknown.entrySet())
                        w.println(String.format("unknown %x %x", e.getKey(), e.getValue() - e.getKey()));
                }
            }
            emu.dispose();
        }
    }
}
