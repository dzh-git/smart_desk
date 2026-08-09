const endpoint = process.env.WEBVIEW_DEBUG_ENDPOINT ?? "http://127.0.0.1:9224";
const targets = await fetch(`${endpoint}/json`).then((response) => response.json());
const target = targets.find(
  (candidate) =>
    candidate.type === "page" &&
    new URL(candidate.url).pathname.endsWith("/web/index.html"),
);

if (!target) {
  throw new Error("SmartDesk diagnostic WebView debug target was not found.");
}

const socket = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((resolve, reject) => {
  socket.addEventListener("open", resolve, { once: true });
  socket.addEventListener("error", reject, { once: true });
});

let requestId = 0;
function evaluate(expression) {
  const id = ++requestId;
  const reply = new Promise((resolve) => {
    const listener = (event) => {
      const message = JSON.parse(event.data);
      if (message.id !== id) return;
      socket.removeEventListener("message", listener);
      resolve(message.result.result.value);
    };
    socket.addEventListener("message", listener);
  });
  socket.send(
    JSON.stringify({
      id,
      method: "Runtime.evaluate",
      params: { expression, returnByValue: true },
    }),
  );
  return reply;
}

const before = await evaluate(`(() => {
  window.scrollTo(0, document.documentElement.scrollHeight);
  return {
    url: location.href,
    scrollY: window.scrollY,
    height: document.documentElement.scrollHeight,
  };
})()`);

await new Promise((resolve) => setTimeout(resolve, 6_500));

const after = await evaluate(`({
  url: location.href,
  scrollY: window.scrollY,
  height: document.documentElement.scrollHeight,
})`);
socket.close();

const preserved =
  before.url === after.url &&
  before.scrollY > 0 &&
  before.scrollY === after.scrollY;

if (!preserved) {
  throw new Error(JSON.stringify({ before, after }, null, 2));
}

console.log(JSON.stringify({ before, after, preserved }, null, 2));
