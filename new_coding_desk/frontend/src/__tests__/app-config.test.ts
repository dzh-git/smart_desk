import { afterEach, describe, expect, it } from "vitest";

import { apiBase, wsBase } from "../app-config";

type AppConfigWindow = Window & {
  __APP_CONFIG__?: { apiBase?: string; wsBase?: string };
};

function installNative(serverUrl: string | null): void {
  window.SmartDeskNative = {
    getDeviceInfo: () =>
      JSON.stringify({
        type: "device_info",
        data: { serverUrl },
      }),
    startFaceVerification: () => undefined,
    stopFaceVerification: () => undefined,
  };
}

afterEach(() => {
  delete (window as AppConfigWindow).__APP_CONFIG__;
  delete window.SmartDeskNative;
});

describe("runtime app configuration", () => {
  it("uses the Android device serverUrl for HTTP and WebSocket", () => {
    installNative("http://192.168.1.10:8000/");

    expect(apiBase()).toBe("http://192.168.1.10:8000");
    expect(wsBase()).toBe("ws://192.168.1.10:8000");
  });

  it("maps an HTTPS native server to WSS", () => {
    installNative("https://meeting.example.test");

    expect(wsBase()).toBe("wss://meeting.example.test");
  });

  it("keeps app-config.js as the explicit override", () => {
    installNative("http://192.168.1.10:8000");
    (window as AppConfigWindow).__APP_CONFIG__ = {
      apiBase: "https://api.example.test/",
      wsBase: "wss://socket.example.test/",
    };

    expect(apiBase()).toBe("https://api.example.test");
    expect(wsBase()).toBe("wss://socket.example.test");
  });

  it("falls back safely when native device information is malformed", () => {
    window.SmartDeskNative = {
      getDeviceInfo: () => "{not-json",
      startFaceVerification: () => undefined,
      stopFaceVerification: () => undefined,
    };

    expect(apiBase()).toBe("");
    expect(wsBase()).toBe(
      `${window.location.protocol === "https:" ? "wss:" : "ws:"}//${window.location.host}`,
    );
  });
});
