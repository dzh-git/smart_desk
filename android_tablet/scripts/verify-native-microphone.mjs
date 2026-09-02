const endpoint = process.env.WEBVIEW_DEBUG_ENDPOINT ?? "http://127.0.0.1:9226";
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
      expression: `new Promise((resolve, reject) => {
        const frames = [];
        const statuses = [];
        const timeout = setTimeout(() => {
          cleanup();
          reject(new Error("Native microphone smoke timed out"));
        }, 5_000);
        const handler = (event) => {
          const detail = event.detail;
          if (detail?.type === "microphone_status") {
            statuses.push(detail.data?.status);
          }
          if (detail?.type === "microphone_audio") {
            frames.push(atob(detail.data?.pcm16Base64 ?? "").length);
            if (frames.length >= 5) {
              window.SmartDeskNative.stopMicrophoneCapture();
              setTimeout(() => {
                cleanup();
                resolve({
                  statuses,
                  frameCount: frames.length,
                  frameBytes: frames,
                });
              }, 100);
            }
          }
          if (
            detail?.type === "error" &&
            String(detail.data?.code ?? "").startsWith("MICROPHONE_")
          ) {
            cleanup();
            reject(new Error(detail.data?.message ?? detail.data?.code));
          }
        };
        function cleanup() {
          clearTimeout(timeout);
          window.removeEventListener("smartdesk-native-event", handler);
        }
        window.addEventListener("smartdesk-native-event", handler);
        window.SmartDeskNative.startMicrophoneCapture();
      })`,
      awaitPromise: true,
      returnByValue: true,
    },
  }),
);

const response = await reply;
socket.close();

if (response.error || response.result?.exceptionDetails) {
  throw new Error(JSON.stringify(response, null, 2));
}

const value = response.result.result.value;
const valid =
  value?.statuses?.includes("STARTED") &&
  value?.frameCount >= 5 &&
  value?.frameBytes?.every((size) => size === 3_200);

if (!valid) {
  throw new Error(JSON.stringify(value, null, 2));
}

console.log(JSON.stringify(value, null, 2));
