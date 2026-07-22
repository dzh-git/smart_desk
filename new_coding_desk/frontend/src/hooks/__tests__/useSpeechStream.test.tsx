import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useSpeechStream } from "../useSpeechStream";

interface MockMicInstance {
  stopped: boolean;
  resolveStart: (() => void) | null;
}

interface MockWsInstance {
  closed: boolean;
  resolveConnect: ((value: { utteranceId: string; sessionKey: string }) => void) | null;
  utteranceStarted: ((utteranceId: string) => void) | null;
  statusChanged: ((status: "disconnected" | "connecting" | "connected" | "started" | "error") => void) | null;
  connectArgs: [number, number, string] | null;
}

const harness = vi.hoisted(() => ({
  delayMicrophone: false,
  microphones: [] as unknown[],
  sockets: [] as unknown[],
}));

vi.mock("../../audio/microphone", () => ({
  MicrophoneCapture: class {
    stopped = false;
    resolveStart: (() => void) | null = null;

    constructor() {
      harness.microphones.push(this);
    }

    start(): Promise<void> {
      if (!harness.delayMicrophone) return Promise.resolve();
      return new Promise((resolve) => {
        this.resolveStart = resolve;
      });
    }

    stop(): void {
      this.stopped = true;
    }
  },
}));

vi.mock("../../audio/speechWsClient", () => ({
  SpeechWsClient: class {
    closed = false;
    resolveConnect: MockWsInstance["resolveConnect"] = null;
    utteranceStarted: MockWsInstance["utteranceStarted"] = null;
    statusChanged: MockWsInstance["statusChanged"] = null;
    connectArgs: MockWsInstance["connectArgs"] = null;

    constructor() {
      harness.sockets.push(this);
    }

    onUtteranceStarted(callback: (utteranceId: string) => void): void {
      this.utteranceStarted = callback;
    }

    onStatusChange(callback: MockWsInstance["statusChanged"]): void {
      this.statusChanged = callback;
    }

    connect(meetingId: number, seatId: number, languageMode: string): Promise<{ utteranceId: string; sessionKey: string }> {
      this.connectArgs = [meetingId, seatId, languageMode];
      return new Promise((resolve) => {
        this.resolveConnect = resolve;
      });
    }

    sendAudio(): void {}
    sendEndHint(): void {}
    sendCancel(): void {}

    close(): void {
      this.closed = true;
    }
  },
}));

describe("useSpeechStream lifecycle", () => {
  beforeEach(() => {
    harness.delayMicrophone = false;
    harness.microphones.length = 0;
    harness.sockets.length = 0;
    window.localStorage.clear();
  });

  it("persists the selected language and locks it into start/reconnect", async () => {
    const { result, unmount } = renderHook(() => useSpeechStream(41, 1, true));
    act(() => result.current.setLanguageMode("en"));
    expect(result.current.languageMode).toBe("en");
    expect(window.localStorage.getItem("smartdesk.speechLanguageMode.1")).toBe("en");

    let startPromise!: Promise<void>;
    act(() => { startPromise = result.current.start(); });
    await waitFor(() => expect(harness.sockets).toHaveLength(1));
    const socket = harness.sockets[0] as MockWsInstance;
    expect(socket.connectArgs).toEqual([41, 1, "en"]);
    await act(async () => {
      socket.resolveConnect?.({
        utteranceId: "utt_41_1_000025",
        sessionKey: "speech_41_1",
      });
      await startPromise;
    });
    act(() => result.current.setLanguageMode("zh"));
    expect(result.current.languageMode).toBe("en");
    unmount();
  });

  it("allows only one start while microphone permission is pending", async () => {
    harness.delayMicrophone = true;
    const { result, unmount } = renderHook(() => useSpeechStream(41, 1, true));

    let firstStart!: Promise<void>;
    let secondStart!: Promise<void>;
    act(() => {
      firstStart = result.current.start();
      secondStart = result.current.start();
    });

    expect(harness.microphones).toHaveLength(1);
    const microphone = harness.microphones[0] as MockMicInstance;
    act(() => microphone.resolveStart?.());
    await waitFor(() => expect(harness.sockets).toHaveLength(1));

    const socket = harness.sockets[0] as MockWsInstance;
    await act(async () => {
      socket.resolveConnect?.({
        utteranceId: "utt_41_1_000026",
        sessionKey: "speech_41_1",
      });
      await firstStart;
      await secondStart;
    });

    expect(result.current.utteranceId).toBe("utt_41_1_000026");
    unmount();
  });

  it("ignores callbacks from a cancelled connection after immediate restart", async () => {
    const onTerminal = vi.fn();
    const { result, unmount } = renderHook(() => useSpeechStream(
      41, 1, true, { onLocalTerminalUtterance: onTerminal },
    ));

    let oldStart!: Promise<void>;
    act(() => {
      oldStart = result.current.start();
    });
    await waitFor(() => expect(harness.sockets).toHaveLength(1));
    const oldSocket = harness.sockets[0] as MockWsInstance;

    act(() => result.current.cancel());

    let newStart!: Promise<void>;
    act(() => {
      newStart = result.current.start();
    });
    await waitFor(() => expect(harness.sockets).toHaveLength(2));
    const newSocket = harness.sockets[1] as MockWsInstance;

    await act(async () => {
      newSocket.resolveConnect?.({
        utteranceId: "utt_41_1_000027",
        sessionKey: "speech_41_1",
      });
      await newStart;
    });
    expect(result.current.utteranceId).toBe("utt_41_1_000027");

    await act(async () => {
      oldSocket.resolveConnect?.({
        utteranceId: "utt_41_1_000026",
        sessionKey: "speech_41_1",
      });
      await oldStart;
      oldSocket.utteranceStarted?.("utt_41_1_000028");
    });

    expect(result.current.status).toBe("recording");
    expect(result.current.utteranceId).toBe("utt_41_1_000027");
    expect(onTerminal).not.toHaveBeenCalledWith("utt_41_1_000027", "cancel");
    unmount();
  });

  it("releases a cancelled microphone request without disturbing its restart", async () => {
    harness.delayMicrophone = true;
    const { result, unmount } = renderHook(() => useSpeechStream(41, 1, true));

    let oldStart!: Promise<void>;
    act(() => {
      oldStart = result.current.start();
    });
    const oldMicrophone = harness.microphones[0] as MockMicInstance;

    act(() => result.current.cancel());
    expect(oldMicrophone.stopped).toBe(true);

    harness.delayMicrophone = false;
    let newStart!: Promise<void>;
    act(() => {
      newStart = result.current.start();
    });
    await waitFor(() => expect(harness.sockets).toHaveLength(1));
    const newSocket = harness.sockets[0] as MockWsInstance;

    await act(async () => {
      newSocket.resolveConnect?.({
        utteranceId: "utt_41_1_000027",
        sessionKey: "speech_41_1",
      });
      await newStart;
    });

    await act(async () => {
      oldMicrophone.resolveStart?.();
      await oldStart;
    });

    expect(harness.sockets).toHaveLength(1);
    expect(result.current.status).toBe("recording");
    expect(result.current.utteranceId).toBe("utt_41_1_000027");
    unmount();
  });

  it("reconnects an unexpectedly closed speech socket while recording", async () => {
    vi.useFakeTimers();
    const { result, unmount } = renderHook(() => useSpeechStream(41, 1, true));

    let startPromise!: Promise<void>;
    act(() => {
      startPromise = result.current.start();
    });
    await act(async () => {
      await Promise.resolve();
    });
    const firstSocket = harness.sockets[0] as MockWsInstance;
    await act(async () => {
      firstSocket.resolveConnect?.({
        utteranceId: "utt_41_1_000026",
        sessionKey: "speech_41_1",
      });
      await startPromise;
    });

    act(() => {
      firstSocket.statusChanged?.("disconnected");
      vi.advanceTimersByTime(500);
    });
    expect(harness.sockets).toHaveLength(2);
    expect(result.current.status).toBe("connecting_speech_ws");

    const replacement = harness.sockets[1] as MockWsInstance;
    await act(async () => {
      replacement.resolveConnect?.({
        utteranceId: "utt_41_1_000027",
        sessionKey: "speech_41_1",
      });
      await Promise.resolve();
    });

    expect(result.current.status).toBe("recording");
    expect(result.current.utteranceId).toBe("utt_41_1_000027");
    unmount();
    vi.useRealTimers();
  });
});
