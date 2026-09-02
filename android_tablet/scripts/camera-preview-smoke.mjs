const endpoint = process.env.WEBVIEW_DEBUG_ENDPOINT ?? "http://127.0.0.1:9222";
const action = process.argv[2] ?? "start";
const targets = await fetch(`${endpoint}/json`).then((response) => response.json());
const target = targets.find(
  (candidate) =>
    candidate.type === "page" &&
    candidate.url.startsWith("file:///android_asset/web/index.html"),
);

if (!target) {
  throw new Error("SmartDesk WebView debug target was not found.");
}

const expressions = {
  status: `(() => Object.fromEntries(
    [...document.querySelectorAll(".status-row")].map((row) => [
      row.querySelector("span").textContent.trim(),
      row.querySelector("strong").textContent.trim(),
    ]),
  ))()`,
  start: `(() => {
    window.SmartDeskNative.startFaceDetection();
    return new Promise((resolve) => {
      setTimeout(() => {
        const rows = Object.fromEntries(
          [...document.querySelectorAll(".status-row")].map((row) => [
            row.querySelector("span").textContent.trim(),
            row.querySelector("strong").textContent.trim(),
          ]),
        );
        resolve(rows);
      }, 2500);
    });
  })()`,
  stop: `(() => {
    window.SmartDeskNative.stopFaceDetection();
    return new Promise((resolve) => {
      setTimeout(() => {
        const rows = Object.fromEntries(
          [...document.querySelectorAll(".status-row")].map((row) => [
            row.querySelector("span").textContent.trim(),
            row.querySelector("strong").textContent.trim(),
          ]),
        );
        resolve(rows);
      }, 700);
    });
  })()`,
  cycle: `(async () => {
    const sleep = (milliseconds) =>
      new Promise((resolve) => setTimeout(resolve, milliseconds));
    const cameraValue = () =>
      [...document.querySelectorAll(".status-row")]
        .find((row) => row.querySelector("span").textContent.trim() === "摄像头")
        .querySelector("strong").textContent.trim();

    window.SmartDeskNative.stopFaceDetection();
    await sleep(700);

    const samples = [];
    for (let index = 1; index <= 5; index += 1) {
      window.SmartDeskNative.startFaceDetection();
      await sleep(2000);
      samples.push({ cycle: index, afterStart: cameraValue() });
      window.SmartDeskNative.stopFaceDetection();
      await sleep(700);
      samples[samples.length - 1].afterStop = cameraValue();
    }
    return samples;
  })()`,
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
      awaitPromise: true,
    },
  }),
);

const response = await reply;
socket.close();

if (response.error || response.result?.exceptionDetails) {
  throw new Error(JSON.stringify(response, null, 2));
}

console.log(JSON.stringify(response.result.result.value, null, 2));
