const WAITING_COPY = Object.freeze({
  checking: ["正在连接会议系统", "正在检查服务器与平板绑定，请稍候…"],
  "waiting-network": ["正在等待网络", "Wi-Fi 尚未连接，连接恢复后将自动继续。"],
  "waiting-backend": ["正在等待会议系统", "服务器尚未就绪，平板会自动重连。"],
  "waiting-binding": ["正在校验平板绑定", "绑定暂未通过，系统会继续重试。"],
  "waiting-frontend": ["正在打开会议页面", "会议页面尚未就绪，系统会自动重试。"],
  "waiting-config": ["平板尚未配置", "请长按右上角图标 5 秒进入首次配置。"],
});

export function connectionWaitingCopy(mode) {
  return WAITING_COPY[mode] ?? null;
}
