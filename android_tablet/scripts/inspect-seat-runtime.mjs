const endpoint = process.env.WEBVIEW_DEBUG_ENDPOINT ?? "http://127.0.0.1:9225";
const targets = await fetch(`${endpoint}/json`).then((response) => response.json());
const target = targets.find(
  (candidate) =>
    candidate.type === "page" && new URL(candidate.url).pathname.startsWith("/seat/"),
);

if (!target) {
  throw new Error("SmartDesk seat WebView debug target was not found.");
}

const socket = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((resolve, reject) => {
  socket.addEventListener("open", resolve, { once: true });
  socket.addEventListener("error", reject, { once: true });
});

const requestId = 1;
const reply = new Promise((resolve) => {
  socket.addEventListener("message", (event) => {
    const message = JSON.parse(event.data);
    if (message.id === requestId) resolve(message);
  });
});

socket.send(
  JSON.stringify({
    id: requestId,
    method: "Runtime.evaluate",
    params: {
      expression: `JSON.stringify({
        href: location.href,
        isSecureContext,
        mediaDevices: typeof navigator.mediaDevices,
        getUserMedia: typeof navigator.mediaDevices?.getUserMedia,
        bridge: typeof window.SmartDeskNative?.getDeviceInfo,
        nativeMicrophoneStart: typeof window.SmartDeskNative?.startMicrophoneCapture,
        nativeMicrophoneStop: typeof window.SmartDeskNative?.stopMicrophoneCapture,
        unsupportedMicrophoneWarningVisible: document.body.innerText.includes("此浏览器不支持麦克风"),
        translationModelWarningVisible: document.body.innerText.includes("中英翻译模型不可用"),
        historicalTranslationFailureVisible: document.body.innerText.includes("翻译模型不可用"),
        visibleButtons: Array.from(document.querySelectorAll("button"))
          .filter((button) => button.offsetParent !== null)
          .map((button) => button.innerText.trim())
          .filter(Boolean),
        translationModelWarningExcerpt: (() => {
          const text = document.body.innerText;
          const index = text.indexOf("翻译模型不可用");
          return index < 0 ? null : text.slice(Math.max(0, index - 120), index + 240);
        })(),
        deviceInfo: JSON.parse(window.SmartDeskNative.getDeviceInfo()).data,
      })`,
      returnByValue: true,
    },
  }),
);

const response = await reply;
socket.close();

if (response.error || response.result?.exceptionDetails) {
  throw new Error(JSON.stringify(response, null, 2));
}

console.log(response.result.result.value);
