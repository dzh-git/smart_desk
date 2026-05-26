export function statusClass(s) {
  return s === 'active' ? 'badge-active' : s === 'finished' ? 'badge-done' : 'badge-pending'
}

export function statusLabel(s) {
  return s === 'active' ? '进行中' : s === 'finished' ? '已结束' : '待开始'
}
