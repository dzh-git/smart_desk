const endpoint =
  process.env.WEBVIEW_DEBUG_ENDPOINT ?? "http://127.0.0.1:9222";
const action = process.argv[2] ?? "status";
const personId = process.argv[3] ?? "seat-01";
const numericValue = Number(process.argv[3] ?? "0.75");
const targets = await fetch(`${endpoint}/json`).then((response) =>
  response.json(),
);
const target = targets.find(
  (candidate) =>
    candidate.type === "page" &&
    candidate.url.startsWith("file:///android_asset/web/index.html"),
);

if (!target) {
  throw new Error("SmartDesk WebView debug target was not found.");
}

const expressions = {
  status: `JSON.parse(window.SmartDeskNative.getIdentityStatus())`,
  enroll: `(() => JSON.parse(
    window.SmartDeskNative.startFaceEnrollment(${JSON.stringify(personId)})
  ))()`,
  verify: `JSON.parse(window.SmartDeskNative.startFaceVerification())`,
  stop: `JSON.parse(window.SmartDeskNative.stopFaceVerification())`,
  people: `JSON.parse(window.SmartDeskNative.getRegisteredFaces())`,
  remove: `JSON.parse(
    window.SmartDeskNative.removeFaceTemplate(${JSON.stringify(personId)})
  )`,
  threshold: `JSON.parse(
    window.SmartDeskNative.applyProvisionalThreshold(${numericValue})
  )`,
  "diag-on": `JSON.parse(window.SmartDeskNative.setFaceDiagnosticsEnabled(true))`,
  "diag-off": `JSON.parse(window.SmartDeskNative.setFaceDiagnosticsEnabled(false))`,
  "diag-clear": `JSON.parse(window.SmartDeskNative.clearFaceDiagnostics())`,
};

if (!expressions[action]) {
  throw new Error(`Unknown action: ${action}`);
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
      expression: expressions[action],
      returnByValue: true,
    },
  }),
);

const response = await reply;
socket.close();

if (response.error || response.result?.exceptionDetails) {
  throw new Error(JSON.stringify(response, null, 2));
}

console.log(JSON.stringify(response.result.result.value, null, 2));
