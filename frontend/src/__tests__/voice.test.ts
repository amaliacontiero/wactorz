import { describe, it, expect, vi, beforeEach } from "vitest";
import { VoiceInput } from "../io/VoiceInput";

// ── Minimal SpeechRecognition mock ────────────────────────────────────────────

class MockSpeechRecognition {
  continuous = false;
  interimResults = false;
  lang = "";
  onresult: ((e: unknown) => void) | null = null;
  onend: (() => void) | null = null;
  onerror: ((e: { error: string }) => void) | null = null;
  start = vi.fn();
  stop = vi.fn();
}

let mockInstance: MockSpeechRecognition | null = null;

function installMock() {
  (globalThis as any).SpeechRecognition = class extends MockSpeechRecognition {
    constructor() { super(); mockInstance = this; }
  };
  delete (globalThis as any).webkitSpeechRecognition;
}

function removeMock() {
  delete (globalThis as any).SpeechRecognition;
  delete (globalThis as any).webkitSpeechRecognition;
}

// Helper: make navigator.mediaDevices.getUserMedia resolve successfully.
function allowMic() {
  Object.defineProperty(globalThis, "navigator", {
    value: {
      mediaDevices: {
        getUserMedia: vi.fn().mockResolvedValue({
          getTracks: () => [{ stop: vi.fn() }],
        }),
      },
    },
    configurable: true,
    writable: true,
  });
}

// Helper: make getUserMedia reject (mic denied).
function denyMic() {
  Object.defineProperty(globalThis, "navigator", {
    value: {
      mediaDevices: {
        getUserMedia: vi.fn().mockRejectedValue(new Error("NotAllowedError")),
      },
    },
    configurable: true,
    writable: true,
  });
}

beforeEach(() => {
  mockInstance = null;
  vi.clearAllMocks();
});

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("VoiceInput — API unavailable", () => {
  it("isAvailable returns false when SpeechRecognition is not in globalThis", () => {
    removeMock();
    const v = new VoiceInput();
    expect(v.isAvailable).toBe(false);
    expect(v.isRecording).toBe(false);
  });

  it("start() returns false when API is unavailable", async () => {
    removeMock();
    const v = new VoiceInput();
    const result = await v.start();
    expect(result).toBe(false);
  });

  it("uses webkitSpeechRecognition as fallback", () => {
    removeMock();
    (globalThis as any).webkitSpeechRecognition = class extends MockSpeechRecognition {
      constructor() { super(); mockInstance = this; }
    };
    const v = new VoiceInput();
    expect(v.isAvailable).toBe(true);
    delete (globalThis as any).webkitSpeechRecognition;
  });
});

describe("VoiceInput — API available", () => {
  beforeEach(() => { installMock(); allowMic(); });
  afterEach(() => { removeMock(); });

  it("isAvailable returns true", () => {
    const v = new VoiceInput();
    expect(v.isAvailable).toBe(true);
  });

  it("configures recognition with correct settings", () => {
    new VoiceInput();
    expect(mockInstance!.continuous).toBe(false);
    expect(mockInstance!.interimResults).toBe(true);
    expect(mockInstance!.lang).toBe("en-US");
  });

  // ── start ──────────────────────────────────────────────────────────────────

  it("start() calls recognition.start() and returns true", async () => {
    const v = new VoiceInput();
    const ok = await v.start();
    expect(ok).toBe(true);
    expect(mockInstance!.start).toHaveBeenCalledOnce();
    expect(v.isRecording).toBe(true);
  });

  it("start() returns false if already recording", async () => {
    const v = new VoiceInput();
    await v.start();
    const ok = await v.start();
    expect(ok).toBe(false);
    expect(mockInstance!.start).toHaveBeenCalledOnce();
  });

  it("start() returns false and calls onError when mic denied", async () => {
    denyMic();
    const v = new VoiceInput();
    const errSpy = vi.fn();
    v.onError = errSpy;
    const ok = await v.start();
    expect(ok).toBe(false);
    expect(errSpy).toHaveBeenCalledWith(expect.stringContaining("denied"));
  });

  // ── stop ───────────────────────────────────────────────────────────────────

  it("stop() calls recognition.stop() when recording", async () => {
    const v = new VoiceInput();
    await v.start();
    v.stop();
    expect(mockInstance!.stop).toHaveBeenCalledOnce();
    expect(v.isRecording).toBe(false);
  });

  it("stop() is a no-op when not recording", () => {
    const v = new VoiceInput();
    expect(() => v.stop()).not.toThrow();
    expect(mockInstance!.stop).not.toHaveBeenCalled();
  });

  // ── onresult ───────────────────────────────────────────────────────────────

  it("fires onTranscript with final=true on final result", async () => {
    const v = new VoiceInput();
    const spy = vi.fn();
    v.onTranscript = spy;
    await v.start();

    const evt = {
      resultIndex: 0,
      results: {
        length: 1,
        0: { isFinal: true, length: 1, 0: { transcript: "hello world" } },
      },
    };
    mockInstance!.onresult!(evt);
    expect(spy).toHaveBeenCalledWith("hello world", true);
  });

  it("fires onTranscript with final=false on interim result", async () => {
    const v = new VoiceInput();
    const spy = vi.fn();
    v.onTranscript = spy;
    await v.start();

    const evt = {
      resultIndex: 0,
      results: {
        length: 1,
        0: { isFinal: false, length: 1, 0: { transcript: "hel" } },
      },
    };
    mockInstance!.onresult!(evt);
    expect(spy).toHaveBeenCalledWith("hel", false);
  });

  it("handles result without transcript gracefully", async () => {
    const v = new VoiceInput();
    v.onTranscript = vi.fn();
    await v.start();
    const evt = {
      resultIndex: 0,
      results: {
        length: 1,
        0: { isFinal: false, length: 1, 0: undefined },
      },
    };
    expect(() => mockInstance!.onresult!(evt)).not.toThrow();
  });

  // ── onend ──────────────────────────────────────────────────────────────────

  it("onend clears isRecording and calls onStop", async () => {
    const v = new VoiceInput();
    const stopSpy = vi.fn();
    v.onStop = stopSpy;
    await v.start();
    mockInstance!.onend!();
    expect(v.isRecording).toBe(false);
    expect(stopSpy).toHaveBeenCalledOnce();
  });

  // ── onerror ────────────────────────────────────────────────────────────────

  it("onerror calls onError with user message for 'not-allowed'", async () => {
    const v = new VoiceInput();
    const errSpy = vi.fn();
    v.onError = errSpy;
    await v.start();
    mockInstance!.onerror!({ error: "not-allowed" });
    expect(errSpy).toHaveBeenCalledWith(expect.stringContaining("denied"));
  });

  it("onerror calls onError for 'service-not-allowed'", async () => {
    const v = new VoiceInput();
    const errSpy = vi.fn();
    v.onError = errSpy;
    await v.start();
    mockInstance!.onerror!({ error: "service-not-allowed" });
    expect(errSpy).toHaveBeenCalledWith(expect.stringContaining("HTTPS"));
  });

  it("onerror calls onError for 'audio-capture'", async () => {
    const v = new VoiceInput();
    const errSpy = vi.fn();
    v.onError = errSpy;
    await v.start();
    mockInstance!.onerror!({ error: "audio-capture" });
    expect(errSpy).toHaveBeenCalledWith(expect.stringContaining("microphone"));
  });

  it("onerror nulls recognition for permanent errors (making isAvailable false)", async () => {
    const v = new VoiceInput();
    await v.start();
    mockInstance!.onerror!({ error: "not-allowed" });
    expect(v.isAvailable).toBe(false);
  });

  it("onerror does not call onError for 'no-speech'", async () => {
    const v = new VoiceInput();
    const errSpy = vi.fn();
    v.onError = errSpy;
    await v.start();
    mockInstance!.onerror!({ error: "no-speech" });
    expect(errSpy).not.toHaveBeenCalled();
  });

  it("onerror does not call onError for 'aborted'", async () => {
    const v = new VoiceInput();
    const errSpy = vi.fn();
    v.onError = errSpy;
    await v.start();
    mockInstance!.onerror!({ error: "aborted" });
    expect(errSpy).not.toHaveBeenCalled();
  });

  it("onerror calls onError for 'network' error", async () => {
    const v = new VoiceInput();
    const errSpy = vi.fn();
    v.onError = errSpy;
    await v.start();
    mockInstance!.onerror!({ error: "network" });
    expect(errSpy).toHaveBeenCalledWith(expect.stringContaining("Network"));
  });

  it("onerror calls onStop after any error", async () => {
    const v = new VoiceInput();
    const stopSpy = vi.fn();
    v.onStop = stopSpy;
    await v.start();
    mockInstance!.onerror!({ error: "no-speech" });
    expect(stopSpy).toHaveBeenCalledOnce();
  });
});
