/**
 * Queue - Print Queue Manager component
 */

const QueueUI = (() => {
  function init() {
    refresh();
    const refreshBtn = document.getElementById('btn-queue-refresh');
    if (refreshBtn) refreshBtn.addEventListener('click', refresh);
  }

  async function refresh() {
    const resp = await fetch('/api/queue');
    const items = await resp.json();
    _render(items);
  }

  function _render(items) {
    const tbody = document.getElementById('queue-tbody');
    if (!tbody) return;
    if (!items.length) {
      tbody.innerHTML = '<tr><td colspan="4" class="empty-row">Queue is empty</td></tr>';
      return;
    }
    tbody.innerHTML = items.map(item => `
      <tr>
        <td>${_escape(item.name)}</td>
        <td>${_escape(item.added_at)}</td>
        <td><span class="badge badge-${item.status}">${_escape(item.status)}</span></td>
        <td>
          <button class="btn-sm btn-primary" onclick="QueueUI.send('${item.id}')">📤 Send</button>
          <button class="btn-sm btn-danger"  onclick="QueueUI.remove('${item.id}')">🗑️ Remove</button>
        </td>
      </tr>
    `).join('');
  }

  async function send(id) {
    const moonrakerUrl = localStorage.getItem('moonraker_url') || '';
    const apiKey       = localStorage.getItem('moonraker_key') || '';
    const resp = await fetch(`/api/queue/${id}/send`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ moonraker_url: moonrakerUrl, api_key: apiKey }),
    });
    const result = await resp.json();
    alert(result.ok ? '✅ Sent to printer!' : `❌ Error: ${result.error}`);
    refresh();
  }

  async function remove(id) {
    if (!confirm('Remove this item?')) return;
    await fetch(`/api/queue/${id}/remove`, { method: 'POST' });
    refresh();
  }

  function _escape(str) {
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');
  }

  return { init, refresh, send, remove };
})();
