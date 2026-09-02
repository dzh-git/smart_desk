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
      expression: `new Promise(async (resolve, reject) => {
        const delay = (milliseconds) => new Promise((done) => setTimeout(done, milliseconds));
        const findButton = (label) => Array.from(document.querySelectorAll("button"))
          .find((button) => button.innerText.includes(label));
        const waitFor = async (predicate, timeoutMs) => {
          const deadline = Date.now() + timeoutMs;
          while (Date.now() < deadline) {
            if (predicate()) return;
            await delay(100);
          }
          throw new Error("Timed out waiting for speech UI state");
        };

        try {
          const start = findButton("开始识别");
          if (!start || start.disabled) {
            throw new Error("Speech Start button is unavailable or disabled");
          }
          start.click();
          await waitFor(() => document.body.innerText.includes("Streaming audio"), 8_000);
          await delay(1_500);

          const stop = findButton("停止");
          if (!stop) throw new Error("Speech Stop button was not found");
          stop.click();
          await waitFor(() => document.body.innerText.includes("Click Start to begin speaking"), 8_000);

          resolve({
            started: true,
            stopped: true,
            microphoneWarningVisible: document.body.innerText.includes("此浏览器不支持麦克风"),
            translationWarningVisible: document.body.innerText.includes("中英翻译模型不可用"),
          });
        } catch (error) {
          findButton("取消")?.click();
          reject(error);
        }
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
if (
  !value?.started ||
  !value?.stopped ||
  value.microphoneWarningVisible ||
  value.translationWarningVisible
) {
  throw new Error(JSON.stringify(value, null, 2));
}

console.log(JSON.stringify(value, null, 2));
