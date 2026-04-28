import { describe, it, expect, vi, beforeEach } from "vitest";

// TTSManager reads localStorage in its constructor, so we import after setup.
// Re-import each test via dynamic import to get a fresh instance.

describe("TTSManager", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.clearAllMocks();
    // Reset the module so the singleton re-reads localStorage
    vi.resetModules();
  });

  async function freshTTS() {
    const mod = await import("../io/TTSManager");
    return { TTSManager: mod.TTSManager, tts: mod.tts };
  }

  // ── constructor / localStorage ────────────────────────────────────────────

  it("beepEnabled defaults to true (no localStorage entry)", async () => {
    const { TTSManager } = await freshTTS();
    const m = new TTSManager();
    expect(m.beepEnabled).toBe(true);
  });

  it("beepEnabled is false when localStorage has '0'", async () => {
    localStorage.setItem("wactorz.beep", "0");
    const { TTSManager } = await freshTTS();
    const m = new TTSManager();
    expect(m.beepEnabled).toBe(false);
  });

  it("ttsEnabled defaults to false", async () => {
    const { TTSManager } = await freshTTS();
    const m = new TTSManager();
    expect(m.ttsEnabled).toBe(false);
  });

  it("ttsEnabled is true when localStorage has '1'", async () => {
    localStorage.setItem("wactorz.tts", "1");
    const { TTSManager } = await freshTTS();
    const m = new TTSManager();
    expect(m.ttsEnabled).toBe(true);
  });

  // ── toggleBeep ─────────────────────────────────────────────────────────────

  it("toggleBeep() flips beepEnabled and persists", async () => {
    const { TTSManager } = await freshTTS();
    const m = new TTSManager();
    expect(m.toggleBeep()).toBe(false);
    expect(localStorage.getItem("wactorz.beep")).toBe("0");
    expect(m.toggleBeep()).toBe(true);
    expect(localStorage.getItem("wactorz.beep")).toBe("1");
  });

  // ── toggleTTS ──────────────────────────────────────────────────────────────

  it("toggleTTS() flips ttsEnabled and persists", async () => {
    const { TTSManager } = await freshTTS();
    const m = new TTSManager();
    expect(m.toggleTTS()).toBe(true);
    expect(localStorage.getItem("wactorz.tts")).toBe("1");
    expect(m.toggleTTS()).toBe(false);
    expect(localStorage.getItem("wactorz.tts")).toBe("0");
  });

  it("toggleTTS() calls speechSynthesis.cancel() when disabling", async () => {
    const { TTSManager } = await freshTTS();
    const m = new TTSManager();
    m.toggleTTS(); // enable
    m.toggleTTS(); // disable → should cancel
    expect((globalThis as any).speechSynthesis.cancel).toHaveBeenCalled();
  });

  // ── checkUserIntent ────────────────────────────────────────────────────────

  it("checkUserIntent('please speak') sets forceNext flag", async () => {
    const { TTSManager } = await freshTTS();
    const m = new TTSManager();
    m.checkUserIntent("please speak the reply");
    // After forcing, the next notify should call speak
    m.notify("hello");
    expect((globalThis as any).speechSynthesis.speak).toHaveBeenCalledOnce();
  });

  it("checkUserIntent with no keyword does not set forceNext", async () => {
    const { TTSManager } = await freshTTS();
    const m = new TTSManager();
    m.checkUserIntent("what is the weather?");
    m.notify("sunny");
    expect((globalThis as any).speechSynthesis.speak).not.toHaveBeenCalled();
  });

  it("forceNext flag is consumed after one notify", async () => {
    const { TTSManager } = await freshTTS();
    const m = new TTSManager();
    m.checkUserIntent("read it out");
    m.notify("first");
    m.notify("second");
    expect((globalThis as any).speechSynthesis.speak).toHaveBeenCalledOnce();
  });

  // ── notify paths ───────────────────────────────────────────────────────────

  it("notify() calls beep when beepEnabled=true (mocked AudioContext)", async () => {
    const { TTSManager } = await freshTTS();
    const m = new TTSManager();
    expect(m.beepEnabled).toBe(true);
    // Should not throw even though AudioContext is mocked
    expect(() => m.notify("hi")).not.toThrow();
  });

  it("notify() calls speak when ttsEnabled=true", async () => {
    localStorage.setItem("wactorz.tts", "1");
    const { TTSManager } = await freshTTS();
    const m = new TTSManager();
    m.notify("hello agent");
    expect((globalThis as any).speechSynthesis.speak).toHaveBeenCalledOnce();
  });

  it("notify() does not call speak when both ttsEnabled=false and no forceNext", async () => {
    const { TTSManager } = await freshTTS();
    const m = new TTSManager();
    m.notify("hello agent");
    expect((globalThis as any).speechSynthesis.speak).not.toHaveBeenCalled();
  });

  // ── speak keyword variants ────────────────────────────────────────────────

  it.each(["speak", "read it out", "say it", "tell me", "voice", "aloud", "out loud", "read this out"])(
    "checkUserIntent recognises keyword '%s'",
    async (phrase) => {
      const { TTSManager } = await freshTTS();
      const m = new TTSManager();
      m.checkUserIntent(phrase);
      m.notify("response");
      expect((globalThis as any).speechSynthesis.speak).toHaveBeenCalledOnce();
    },
  );

  // ── AudioContext failure / suspend paths ──────────────────────────────────

  it("_ctx() returns null when AudioContext construction throws", async () => {
    const origAC = (globalThis as any).AudioContext;
    (globalThis as any).AudioContext = function () { throw new Error("blocked"); };
    const { TTSManager } = await freshTTS();
    const m = new TTSManager();
    // notify() → _beep() → _ctx() throws in constructor → returns null → no crash
    expect(() => m.notify("hi")).not.toThrow();
    (globalThis as any).AudioContext = origAC;
  });

  it("_ctx() calls resume() when AudioContext is suspended", async () => {
    const resumeSpy = vi.fn().mockResolvedValue(undefined);
    const origAC = (globalThis as any).AudioContext;
    class SuspendedAC extends origAC {
      state = "suspended";
      resume = resumeSpy;
    }
    (globalThis as any).AudioContext = SuspendedAC;
    const { TTSManager } = await freshTTS();
    const m = new TTSManager();
    expect(() => m.notify("hi")).not.toThrow();
    expect(resumeSpy).toHaveBeenCalled();
    (globalThis as any).AudioContext = origAC;
  });

  // ── singleton export ───────────────────────────────────────────────────────

  it("exports a singleton tts instance", async () => {
    const { tts, TTSManager } = await freshTTS();
    expect(tts).toBeInstanceOf(TTSManager);
  });
});
