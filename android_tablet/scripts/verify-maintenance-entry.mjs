const endpoint = process.env.WEBVIEW_DEBUG_ENDPOINT ?? "http://127.0.0.1:9222";
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
      expression: `(() => {
        const button = document.querySelector('[data-testid="maintenance-access"]');
        const scroll = document.querySelector('[data-testid="seat-page-scroll"]');
        const header = button?.closest('header');
        const originalScrollTop = scroll?.scrollTop ?? 0;
        if (scroll && header) scroll.scrollTop = header.offsetHeight + 8;
        const headerLeavesViewport = Boolean(
          scroll && header &&
          header.getBoundingClientRect().bottom <= scroll.getBoundingClientRect().top,
        );
        if (scroll) scroll.scrollTop = originalScrollTop;
        return {
          buttonPresent: Boolean(button),
          buttonLabel: button?.getAttribute('aria-label'),
          statusText: button?.parentElement?.textContent?.trim(),
          isLastInStatusGroup: button?.parentElement?.lastElementChild === button,
          inScrollContainer: Boolean(scroll?.contains(button)),
          scrollOverflowY: scroll ? getComputedStyle(scroll).overflowY : null,
          headerLeavesViewport,
          bridgeBegin: typeof window.SmartDeskNative?.beginMaintenanceHold,
          bridgeCancel: typeof window.SmartDeskNative?.cancelMaintenanceHold,
        };
      })()`,
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
  value?.buttonPresent &&
  value?.isLastInStatusGroup &&
  value?.inScrollContainer &&
  value?.scrollOverflowY === "auto" &&
  value?.headerLeavesViewport &&
  value?.bridgeBegin === "function" &&
  value?.bridgeCancel === "function";

if (!valid) {
  throw new Error(JSON.stringify(value, null, 2));
}

console.log(JSON.stringify(value, null, 2));
