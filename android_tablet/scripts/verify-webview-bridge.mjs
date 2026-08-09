const endpoint = process.env.WEBVIEW_DEBUG_ENDPOINT ?? "http://127.0.0.1:9222";
const targets = await fetch(`${endpoint}/json`).then((response) => response.json());
const target = targets.find(
  (candidate) =>
    candidate.type === "page" &&
    candidate.url.startsWith("file:///android_asset/web/index.html"),
);

if (!target) {
  throw new Error("SmartDesk WebView debug target was not found.");
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
    if (message.id === requestId) {
      resolve(message);
    }
  });
});

socket.send(
  JSON.stringify({
    id: requestId,
    method: "Runtime.evaluate",
    params: {
      expression: `(() => {
        const nativeResult = window.SmartDeskNative.getDeviceInfo();
        const labels = [...document.querySelectorAll(".configuration label span")]
          .map((item) => item.textContent.trim());
        if (labels.some((label) => label.includes("设备密钥"))) {
          throw new Error("Diagnostic page must not expose a device-token field");
        }
        const values = [...document.querySelectorAll(".status-row strong")]
          .map((item) => item.textContent.trim());
        return {
          nativeResult,
          values,
          configurationVisible: Boolean(
            document.querySelector('form[aria-label="设备配置"]'),
          ),
          provisioningAvailable:
            typeof window.SmartDeskNative.provisionDeviceConfig === "function",
        };
      })()`,
      returnByValue: true,
      awaitPromise: true,
    },
  }),
);

const response = await reply;
socket.close();

if (response.error || response.result?.exceptionDetails) {
  throw new Error(JSON.stringify(response, null, 2));
}

const value = response.result.result.value;
if (!value?.provisioningAvailable) {
  throw new Error("SmartDeskNative.provisionDeviceConfig is unavailable");
}
console.log(JSON.stringify(value, null, 2));
