const state = {
  devices: [],
};

const els = {
  grid: document.querySelector("#dashboardGrid"),
  status: document.querySelector("#dashboardStatus"),
  refreshAll: document.querySelector("#refreshAllButton"),
};

els.refreshAll.addEventListener("click", refreshAll);

async function loadDashboard() {
  setStatus("Loading dashboard...");
  try {
    const response = await fetch("/api/dashboard/list");
    if (!response.ok) throw new Error("Failed to load dashboard");
    const data = await response.json();
    state.devices = data.devices || [];
    render();
    setStatus(`Loaded ${state.devices.length} device(s)`);
  } catch (err) {
    setStatus(`Error: ${err.message}`);
  }
}

async function refreshAll() {
  setBusy(true, "Refreshing all streams...");
  try {
    const response = await fetch("/api/dashboard/refresh", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    });
    if (!response.ok) throw new Error("Failed to refresh dashboard");
    const data = await response.json();
    state.devices = data.devices || [];
    render();
    setStatus(`Refreshed ${state.devices.length} device(s) successfully`);
  } catch (err) {
    setStatus(`Refresh failed: ${err.message}`);
  } finally {
    setBusy(false);
  }
}

async function removeDevice(ip) {
  if (!confirm(`Are you sure you want to remove ${ip} from the dashboard?`)) return;
  
  try {
    const response = await fetch("/api/dashboard/remove", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ip }),
    });
    if (!response.ok) throw new Error("Failed to remove device");
    state.devices = state.devices.filter((device) => device.ip !== ip);
    render();
    setStatus(`Removed ${ip}`);
  } catch (err) {
    setStatus(`Error: ${err.message}`);
  }
}

function render() {
  if (state.devices.length === 0) {
    els.grid.innerHTML = `
      <div class="empty-row" style="grid-column: 1 / -1; background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 48px; text-align: center; color: var(--muted);">
        <h3>ยังไม่มีกล้องในแดชบอร์ด</h3>
        <p>กลับไปที่หน้าสแกนเครือข่าย แล้วกด "➕ Add to Dashboard" บนกล้องที่สแกนเจอ</p>
      </div>
    `;
    return;
  }

  els.grid.innerHTML = state.devices
    .map((device) => {
      const channelBlocks = [];
      const channelsStatus = device.channels_status || [];

      // Render 8 channel blocks
      for (let channelId = 1; channelId <= 8; channelId++) {
        const chInfo = channelsStatus.find((ch) => ch.channel === channelId);
        let blockClass = "offline";
        let statusText = "OFF";
        let titleText = "Not Checked / No Signal";

        if (chInfo) {
          if (chInfo.status === "ONLINE") {
            blockClass = "online";
            statusText = "ON";
            titleText = `Online (${chInfo.bytes.toLocaleString()} B)`;
          } else if (chInfo.status === "VIDEO_LOSS") {
            blockClass = "loss";
            statusText = "LOSS";
            titleText = `Video Loss (${chInfo.bytes.toLocaleString()} B)`;
          }
        }

        channelBlocks.push(`
          <div class="chan-block ${blockClass}" title="${escapeHtml(titleText)}">
            <span class="chan-num">CH${channelId}</span>
            <span class="chan-status-text">${statusText}</span>
          </div>
        `);
      }

      return `
        <div class="card">
          <header class="card-header">
            <div>
              <h3 class="card-title">${escapeHtml(device.ip)}</h3>
              <div class="card-subtitle">
                ${escapeHtml(device.manufacturer || "Unknown")} 
                ${device.model && device.model !== "Unknown" ? `| ${escapeHtml(device.model)}` : ""}
              </div>
            </div>
            <button class="btn-danger-outline" onclick="removeDevice('${device.ip}')">Remove</button>
          </header>
          <div class="card-body">
            <div class="channel-grid">
              ${channelBlocks.join("")}
            </div>
          </div>
          <footer class="card-footer">
            <div><strong>RTSP:</strong> ${escapeHtml(device.rtsp_url || "-")}</div>
            <div><strong>ONVIF:</strong> ${escapeHtml(device.xaddr || "-")}</div>
          </footer>
        </div>
      `;
    })
    .join("");
}

function setStatus(text) {
  els.status.textContent = text;
}

function setBusy(busy, label = "Refreshing...") {
  els.refreshAll.disabled = busy;
  if (busy) setStatus(label);
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#039;",
  }[char]));
}

// Initialize on page load
loadDashboard();
