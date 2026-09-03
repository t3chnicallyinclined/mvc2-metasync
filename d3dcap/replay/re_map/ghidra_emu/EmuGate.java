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
//
// FRAME-TRACE extension (docs/FRAME-READSET.md, 2026-09-03) -- whole-frame runs on the live TTD images:
//   trace <file>                      log EVERY ram access made while executing (after this line) to a binary
//                                     stream: u8 kind {0 read, 1 write, 2 call, 3 extcall, 4 callother, 5 mark}
//                                     u64 pc, u64 addr, u32 size (little endian, 21 B/record). Instruction fetch
//                                     (reads inside [pc, pc+16)) is dropped. kind 2: pc = callee entry, addr = return
//                                     address. kind 3: pc = external target, addr = return address. kind 5: run index.
//   functable <file>                  "<hexaddr> <hexsize> <name>" per line: function starts, used to detect calls
//   image <hexlo> <hexhi>             the executable image range; with `extstub on` any PC outside it (and not the
//                                     sentinel) is an OS/DLL call: logged (target, return, RCX, RDX, R8), RAX = 0, RET
//   extstub on|off
//   callother skip|abort              unimplemented CALLOTHER (vfmadd, rdtsc, cpuid ...): log + skip, or abort the run
//   probe <hexaddr> <name>            log XMM0/XMM1 (low 64 bits) whenever PC reaches addr; execution unchanged
//   nudge <hexaddr> <name>            when PC reaches addr, XMM0.single += 1 ulp (sensitivity test for a float routine's result:
//                                     put it on the instruction AFTER the call, or on the routine's RET)
//   fma on|off                        compute the FMA3 CALLOTHERs (vf[n]m{add,sub}{132,213,231}{ss,sd,ps,pd}) with Java
//                                     Math.fma (one rounding = the hardware result); result line `fmacount N`.
//                                     Lets the tick run with DAT_142eefbd8 = 1 (docs/DETERMINISM-CONTRACT.md s3)
//   note <text>                       copied into the result file (job provenance)
//   heap <hexaddr> <hexsize>          zero-filled bump-allocator arena for `extalloc`
//   extalloc <hexaddr> <reg>          external target with allocator semantics (e.g. RtlAllocateHeap: size in R8):
//                                     RAX = next 16-aligned chunk of the heap arena, RET. Logged like extcall.
//   extret <hexaddr> <hexrax>         external target that returns a fixed value (e.g. HeapFree -> 1)
import ghidra.app.script.GhidraScript;
import ghidra.app.emulator.EmulatorHelper;
import ghidra.pcode.memstate.MemoryFaultHandler;
import ghidra.app.emulator.MemoryAccessFilter;
import ghidra.pcode.emulate.BreakCallBack;
import ghidra.pcode.pcoderaw.PcodeOpRaw;
import ghidra.program.model.address.AddressSpace;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
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
    // frame-trace extension
    BufferedOutputStream trace = null;
    long traceCount = 0, curPc = 0;
    ByteBuffer rec = ByteBuffer.allocate(21).order(ByteOrder.LITTLE_ENDIAN);
    HashSet<Long> funcStarts = new HashSet<>();
    long imgLo = 0, imgHi = 0;
    boolean extStub = false, callotherSkip = false;
    int runIndex = 0;
    LinkedHashMap<String, Integer> extCounts = new LinkedHashMap<>();
    LinkedHashMap<String, Integer> callotherCounts = new LinkedHashMap<>();
    List<String> notes = new ArrayList<>();
    long heapBase = 0, heapSize = 0, heapCur = 0;
    Map<Long, String> extAlloc = new HashMap<>();
    Map<Long, Long> extRet = new HashMap<>();
    Map<Long, String> probes = new HashMap<>();   // `probe <addr> <name>`: log XMM0/XMM1 low 64 bits when PC reaches addr (no effect on execution)
    Map<Long, Integer> ulpNudge = new HashMap<>(); // `ulp <addr> <n>`: when PC reaches the RETURN of a float routine... (see nudge below)
    Map<Long, String> nudgeAt = new HashMap<>();   // `nudge <addr> <name>`: at addr (a RET site or the instruction after a CALL) add 1 ulp to XMM0 single
    boolean fmaEnabled = false;      // `fma on`: compute vf[n]m{add,sub}* CALLOTHERs with Math.fma (else skip/abort as before)
    long fmaCount = 0;

    void traceRec(int kind, long pc, long addr, int size) {
        if (trace == null) return;
        rec.clear();
        rec.put((byte) kind).putLong(pc).putLong(addr).putInt(size);
        try { trace.write(rec.array(), 0, 21); } catch (IOException e) { throw new RuntimeException(e); }
        traceCount++;
    }

    class TraceFilter extends MemoryAccessFilter {
        @Override protected void processRead(AddressSpace spc, long off, int size, byte[] values) {
            if (trace == null || !spc.isMemorySpace()) return;
            if (off >= curPc && off < curPc + 16) return;           // instruction fetch
            traceRec(0, curPc, off, size);
        }
        @Override protected void processWrite(AddressSpace spc, long off, int size, byte[] values) {
            if (trace == null || !spc.isMemorySpace()) return;
            traceRec(1, curPc, off, size);
        }
    }

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
        traceRec(5, entry, 0, runIndex++);
        while (true) {
            long pc = emu.getExecutionAddress().getOffset();
            if (pc == SENTINEL) return "ok steps=" + steps + " ms=" + (System.currentTimeMillis() - t0);
            if (extStub && imgHi != 0 && (pc < imgLo || pc >= imgHi)) {
                long rsp0 = reg("RSP");
                long ret = rd64(rsp0);
                String key = String.format("%x", pc);
                extCounts.merge(key, 1, Integer::sum);
                if (extCounts.get(key) <= 3)
                    stubHits.add(String.format("extcall target=%x ret=%x rcx=%x rdx=%x r8=%x r9=%x step=%d", pc, ret,
                        reg("RCX"), reg("RDX"), reg("R8"), reg("R9"), steps));
                traceRec(3, pc, ret, 0);
                long rax = 0;
                if (extAlloc.containsKey(pc)) {
                    long n = reg(extAlloc.get(pc));
                    if (heapSize == 0) return "error extalloc without a heap arena at pc=" + Long.toHexString(pc);
                    if (heapCur + n + 16 > heapBase + heapSize) return "error heap arena exhausted (" + n + " B) at pc=" + Long.toHexString(pc);
                    rax = heapCur;
                    heapCur = (heapCur + n + 15) & ~15L;
                    if (extCounts.get(key) <= 3) stubHits.add(String.format("extalloc target=%x size=%x -> %x", pc, n, rax));
                } else if (extRet.containsKey(pc)) {
                    rax = extRet.get(pc);
                }
                setReg("RAX", rax);
                doRet();
                continue;
            }
            String pr = probes.get(pc);
            if (pr != null) {
                BigInteger x0 = emu.readRegister("XMM0"), x1 = emu.readRegister("XMM1");
                stubHits.add(String.format("probe %s pc=%x xmm0=%016x xmm1=%016x step=%d", pr, pc,
                    x0.and(new BigInteger("ffffffffffffffff", 16)).longValue(), x1.and(new BigInteger("ffffffffffffffff", 16)).longValue(), steps));
            }
            String nd = nudgeAt.get(pc);
            if (nd != null) {
                float f = xmm0f();
                float g = Float.intBitsToFloat(Float.floatToRawIntBits(f) + 1);
                setXmm0f(g);
                stubHits.add(String.format("nudge %s pc=%x %.9g -> %.9g step=%d", nd, pc, f, g, steps));
            }
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
            curPc = pc;
            long rspBefore = trace != null ? reg("RSP") : 0;
            try {
                ok = emu.step(monitor);
            } catch (Exception e) {
                return "error exception at pc=" + Long.toHexString(pc) + " steps=" + steps + " : " + e;
            }
            steps++;
            if (!ok) return "error at pc=" + Long.toHexString(pc) + " steps=" + steps + " : " + emu.getLastError();
            if (trace != null) {
                long npc = emu.getExecutionAddress().getOffset();
                if (funcStarts.contains(npc)) {
                    long nrsp = reg("RSP");
                    if (nrsp == rspBefore - 8) traceRec(2, npc, rd64(nrsp), 0);
                }
            }
            if ((steps % 1000000) == 0) println("  ... " + steps + " steps, pc=" + Long.toHexString(pc) + ", traced=" + traceCount);
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
        emu.getEmulator().addMemoryAccessFilter(new TraceFilter());
        emu.registerDefaultCallOtherCallback(new BreakCallBack() {
            @Override public boolean pcodeCallback(PcodeOpRaw op) {
                String name;
                try { name = currentProgram.getLanguage().getUserDefinedOpName((int) op.getInput(0).getOffset()); }
                catch (Exception e) { name = "?"; }
                String key = name + "@" + Long.toHexString(curPc);
                callotherCounts.merge(key, 1, Integer::sum);
                traceRec(4, curPc, 0, 0);
                if (fmaEnabled && fmaOp(op, name)) return true;    // computed (DETERMINISM-CONTRACT: FMA3 CRT path)
                if (!callotherSkip) throw new RuntimeException("unimplemented CALLOTHER " + name + " at " + Long.toHexString(curPc));
                return true;      // skipped: outputs left unchanged
            }

            // vf[n]m{add,sub}{132,213,231}{ss,sd,ps,pd}_fma( XmmReg1=dst, vexVVVV=src2, XmmReg2_m = src3 ) -> tmp (output size)
            // 132: dst*src3 + src2   213: src2*dst + src3   231: src2*src3 + dst   (Intel SDM); fnm negates the product,
            // *sub negates the addend. Scalar forms keep the upper lanes of dst. Java Math.fma = one IEEE-754 rounding, the
            // same operation the hardware performs, so the emulated bits equal the FMA3 hardware bits.
            boolean fmaOp(PcodeOpRaw op, String name) {
                java.util.regex.Matcher m = java.util.regex.Pattern.compile("^vf(n?)m(add|sub)(132|213|231)(ss|sd|ps|pd)_").matcher(name);
                if (!m.find() || op.getNumInputs() < 4 || op.getOutput() == null) return false;
                boolean neg = m.group(1).equals("n"), sub = m.group(2).equals("sub");
                String form = m.group(3), type = m.group(4);
                boolean dbl = type.endsWith("d"), scalar = type.startsWith("s");
                int lane = dbl ? 8 : 4;
                ghidra.pcode.memstate.MemoryState ms = emulate.getMemoryState();
                byte[] dst = leBytes(ms.getBigInteger(op.getInput(1), false), op.getInput(1).getSize());
                byte[] s2 = leBytes(ms.getBigInteger(op.getInput(2), false), op.getInput(2).getSize());
                byte[] s3 = leBytes(ms.getBigInteger(op.getInput(3), false), op.getInput(3).getSize());
                int outSize = op.getOutput().getSize();
                byte[] out = new byte[outSize];
                System.arraycopy(dst, 0, out, 0, Math.min(dst.length, outSize));
                int lanes = scalar ? 1 : outSize / lane;
                for (int i = 0; i < lanes; i++) {
                    if (dbl) {
                        double a = ld(dst, i * 8), b = ld(s2, i * 8), c = ld(s3, i * 8), r;
                        if (form.equals("132")) r = fma3(a, c, b, neg, sub);
                        else if (form.equals("213")) r = fma3(b, a, c, neg, sub);
                        else r = fma3(b, c, a, neg, sub);
                        std(out, i * 8, r);
                    } else {
                        float a = lf(dst, i * 4), b = lf(s2, i * 4), c = lf(s3, i * 4), r;
                        if (form.equals("132")) r = fma3f(a, c, b, neg, sub);
                        else if (form.equals("213")) r = fma3f(b, a, c, neg, sub);
                        else r = fma3f(b, c, a, neg, sub);
                        stf(out, i * 4, r);
                    }
                }
                ms.setValue(op.getOutput(), new BigInteger(1, reverse(out)));
                fmaCount++;
                return true;
            }
            double fma3(double x, double y, double z, boolean neg, boolean sub) { return Math.fma(neg ? -x : x, y, sub ? -z : z); }
            float fma3f(float x, float y, float z, boolean neg, boolean sub) { return Math.fma(neg ? -x : x, y, sub ? -z : z); }
            byte[] leBytes(BigInteger v, int size) {
                byte[] be = v.toByteArray(); byte[] le = new byte[size];
                for (int i = 0; i < size && i < be.length; i++) le[i] = be[be.length - 1 - i];
                return le;
            }
            byte[] reverse(byte[] a) { byte[] r = new byte[a.length]; for (int i = 0; i < a.length; i++) r[i] = a[a.length - 1 - i]; return r; }
            double ld(byte[] b, int o) { return o + 8 <= b.length ? ByteBuffer.wrap(b, o, 8).order(ByteOrder.LITTLE_ENDIAN).getDouble() : 0.0; }
            float lf(byte[] b, int o) { return o + 4 <= b.length ? ByteBuffer.wrap(b, o, 4).order(ByteOrder.LITTLE_ENDIAN).getFloat() : 0f; }
            void std(byte[] b, int o, double v) { if (o + 8 <= b.length) ByteBuffer.wrap(b, o, 8).order(ByteOrder.LITTLE_ENDIAN).putDouble(v); }
            void stf(byte[] b, int o, float v) { if (o + 4 <= b.length) ByteBuffer.wrap(b, o, 4).order(ByteOrder.LITTLE_ENDIAN).putFloat(v); }
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
                    case "trace": trace = new BufferedOutputStream(new FileOutputStream(t[1]), 1 << 20); break;
                    case "functable": {
                        for (String m : Files.readAllLines(Paths.get(t[1]))) {
                            String[] kv = m.trim().split("\\s+");
                            if (kv.length >= 1 && !kv[0].isEmpty()) funcStarts.add(Long.parseUnsignedLong(kv[0], 16));
                        }
                        log.add("functable " + funcStarts.size() + " entries"); break; }
                    case "image": imgLo = Long.parseUnsignedLong(t[1], 16); imgHi = Long.parseUnsignedLong(t[2], 16); break;
                    case "extstub": extStub = t[1].equals("on"); break;
                    case "callother": callotherSkip = t[1].equals("skip"); break;
                    case "fma": fmaEnabled = t[1].equals("on"); break;
                    case "probe": probes.put(Long.parseUnsignedLong(t[1], 16), t[2]); break;
                    case "nudge": nudgeAt.put(Long.parseUnsignedLong(t[1], 16), t[2]); break;
                    case "note": notes.add(ln.substring(5)); break;
                    case "heap": heapBase = Long.parseUnsignedLong(t[1], 16); heapSize = Long.parseUnsignedLong(t[2], 16);
                        heapCur = heapBase + 16; emu.writeMemory(A(heapBase), new byte[(int) heapSize]); break;
                    case "extalloc": extAlloc.put(Long.parseUnsignedLong(t[1], 16), t[2]); break;
                    case "extret": extRet.put(Long.parseUnsignedLong(t[1], 16), Long.parseUnsignedLong(t[2], 16)); break;
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
            if (trace != null) { try { trace.close(); } catch (IOException e) { /* ignore */ } }
            if (outPath != null) {
                try (PrintWriter w = new PrintWriter(new FileWriter(outPath))) {
                    for (String s : results) w.println(s);
                    for (String s : notes) w.println("note " + s);
                    w.println("traced " + traceCount);
                    if (heapSize != 0) w.println(String.format("heapused %x", heapCur - heapBase));
                    w.println("fmacount " + fmaCount);
                    for (Map.Entry<String, Integer> e : extCounts.entrySet()) w.println("extcount " + e.getKey() + " " + e.getValue());
                    for (Map.Entry<String, Integer> e : callotherCounts.entrySet()) w.println("callother " + e.getKey() + " " + e.getValue());
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
