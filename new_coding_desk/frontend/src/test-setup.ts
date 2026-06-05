import "@testing-library/jest-dom/vitest";
import { vi } from "vitest";

// ── Mock MediaDevices ──────────────────────────────────────────────────────────
// jsdom does not implement navigator.mediaDevices; provide a stub so that
// components can check for browser support and tests can verify getUserMedia calls.

const mockGetUserMedia = vi.fn();

function createMockMediaStream(): MediaStream {
  const track: MediaStreamTrack = {
    kind: "audio",
    enabled: true,
    stop: vi.fn(),
    readyState: "live",
    id: "mock-track",
    muted: false,
    onended: null,
    onmute: null,
    onunmute: null,
    applyConstraints: vi.fn(),
    clone: vi.fn(),
    getCapabilities: vi.fn(),
    getConstraints: vi.fn(),
    getSettings: vi.fn(),
    label: "mock-microphone",
  } as unknown as MediaStreamTrack;

  return {
    active: true,
    id: "mock-stream",
    getTracks: () => [track],
    getAudioTracks: () => [track],
    getVideoTracks: () => [],
    getTrackById: () => track,
    addTrack: vi.fn(),
    removeTrack: vi.fn(),
    clone: vi.fn(),
    onaddtrack: null,
    onremovetrack: null,
  } as unknown as MediaStream;
}

const defaultMockStream = createMockMediaStream();
mockGetUserMedia.mockResolvedValue(defaultMockStream);

Object.defineProperty(navigator, "mediaDevices", {
  value: {
    getUserMedia: mockGetUserMedia,
  },
  configurable: true,
  writable: true,
});

// ── Mock AudioContext ──────────────────────────────────────────────────────────
// jsdom does not implement AudioContext. Provide a minimal stub for
// MicrophoneCapture to function in tests.

class MockScriptProcessorNode {
  connect = vi.fn();
  disconnect = vi.fn();
  onaudioprocess: ((event: AudioProcessingEvent) => void) | null = null;
}

class MockAudioContext {
  sampleRate = 16000;
  state: AudioContextState = "running";
  destination = {} as AudioDestinationNode;
  baseLatency = 0;
  outputLatency = 0;

  createMediaStreamSource(_stream: MediaStream): MediaStreamAudioSourceNode {
    return {
      connect: vi.fn(),
      disconnect: vi.fn(),
      mediaStream: _stream,
    } as unknown as MediaStreamAudioSourceNode;
  }

  createScriptProcessor(
    _bufferSize: number,
    _inputChannels: number,
    _outputChannels: number,
  ): ScriptProcessorNode {
    return new MockScriptProcessorNode() as unknown as ScriptProcessorNode;
  }

  close(): Promise<void> {
    this.state = "closed";
    return Promise.resolve();
  }
}

// Only set if not already defined (some test environments may polyfill)
if (typeof globalThis.AudioContext === "undefined") {
  (globalThis as unknown as Record<string, unknown>).AudioContext =
    MockAudioContext;
}

// ── Re-export mock helpers for test files ─────────────────────────────────────
// Allow test files to access the mock getUserMedia to override its behavior.

export { mockGetUserMedia, createMockMediaStream };
