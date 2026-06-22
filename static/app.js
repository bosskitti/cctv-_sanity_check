const state = {
  devices: [],
};

const els = {
  status: document.querySelector("#appStatus"),
  subnet: document.querySelector("#subnetInput"),
  port: document.querySelector("#portInput"),
  channel: document.querySelector("#channelInput"),
  useCache: document.querySelector("#useCacheInput"),
  filterCameras: document.querySelector("#filterCamerasInput"),
  scan: document.querySelector("#scanButton"),
  verify: document.querySelector("#verifyButton"),
  applyCreds: document.querySelector("#applyCredsButton"),
  rtspUser: document.querySelector("#rtspUserInput"),
  rtspPassword: document.querySelector("#rtspPasswordInput"),
  onvifUser: document.querySelector("#onvifUserInput"),
  onvifPassword: document.querySelector("#onvifPasswordInput"),
  rows: document.querySelector("#deviceRows"),
  summary: document.querySelector("#summary"),

  // Progress Bar
  progressWrap: document.querySelector("#progressWrap"),
  progressBarFill: document.querySelector("#progressBarFill"),
  progressMessage: document.querySelector("#progressMessage"),
  progressPercent: document.querySelector("#progressPercent"),

  // Modal
  configModal: document.querySelector("#configModal"),
  closeModal: document.querySelector("#closeModalButton"),
  saveModal: document.querySelector("#saveModalButton"),
  modalDeviceIp: document.querySelector("#modalDeviceIp"),
  modalDeviceBrand: document.querySelector("#modalDeviceBrand"),
  modalDeviceModel: document.querySelector("#modalDeviceModel"),
  modalDevicePorts: document.querySelector("#modalDevicePorts"),
  modalRtspUser: document.querySelector("#modalRtspUser"),
  modalRtspPassword: document.querySelector("#modalRtspPassword"),
  modalOnvifUser: document.querySelector("#modalOnvifUser"),
  modalOnvifPassword: document.querySelector("#modalOnvifPassword"),
};

els.scan.addEventListener("click", scan);
els.verify.addEventListener("click", verifyRtsp);
els.applyCreds.addEventListener("click", applyDefaultCredentials);

let currentEditIndex = -1;

function formatDetailedPorts(openPorts) {
  const primaryPorts = [80, 554, 2000, 5000, 8080, 8899];
  const results = [];

  primaryPorts.forEach((port) => {
    if (openPorts && openPorts.includes(port)) {
      results.push(`<span class="port-status open">${port}: Open</span>`);
    } else {
      results.push(`<span class="port-status closed">${port}: Closed</span>`);
    }
  });

  if (openPorts) {
    openPorts.forEach((port) => {
      if (!primaryPorts.includes(port)) {
        results.push(`<span class="port-status open">${port}: Open</span>`);
      }
    });
  }

  return results.join("");
}

function openConfigModal(index) {
  currentEditIndex = index;
  const device = state.devices[index];
  if (!device) return;

  els.modalDeviceIp.textContent = device.ip;
  els.modalDeviceBrand.textContent = device.manufacturer || "Unknown";
  els.modalDeviceModel.textContent = device.model || "Unknown";
  els.modalDevicePorts.innerHTML = formatDetailedPorts(device.open_ports);

  els.modalRtspUser.value = device.credentials?.rtsp_user || "";
  els.modalRtspPassword.value = device.credentials?.rtsp_password || "";
  els.modalOnvifUser.value = device.credentials?.onvif_user || "";
  els.modalOnvifPassword.value = device.credentials?.onvif_password || "";

  els.configModal.classList.add("active");
}

function closeConfigModal() {
  els.configModal.classList.remove("active");
  currentEditIndex = -1;
}

function saveModal() {
  if (currentEditIndex === -1) return;
  const device = state.devices[currentEditIndex];
  if (!device) return;

  device.credentials = {
    rtsp_user: els.modalRtspUser.value.trim(),
    rtsp_password: els.modalRtspPassword.value,
    onvif_user: els.modalOnvifUser.value.trim(),
    onvif_password: els.modalOnvifPassword.value,
  };

  closeConfigModal();
  render();
}

els.closeModal.addEventListener("click", closeConfigModal);
els.saveModal.addEventListener("click", saveModal);

window.addEventListener("click", (e) => {
  if (e.target === els.configModal) {
    closeConfigModal();
  }
});

async function scan() {
  setBusy(true, "Scanning");
  els.progressWrap.style.display = "block";
  els.progressBarFill.style.width = "0%";
  els.progressPercent.textContent = "0%";
  els.progressMessage.textContent = "Initializing scan...";

  let pollInterval = setInterval(async () => {
    try {
      const res = await fetch("/api/scan-status");
      if (res.ok) {
        const status = await res.json();
        els.progressBarFill.style.width = `${status.percentage}%`;
        els.progressPercent.textContent = `${status.percentage}%`;
        els.progressMessage.textContent = status.message;
      }
    } catch (err) {
      console.error("Progress poll error", err);
    }
  }, 1000);

  try {
    const payload = {
      subnet: els.subnet.value.trim(),
      rtsp_port: Number(els.port?.value || 554),
      use_cache: els.useCache.checked,
      filter_cameras: els.filterCameras.checked,
    };
    const data = await postJson("/api/scan", payload);
    state.devices = data.devices.map((device) => {
      const hasCreds = device.credentials && (device.credentials.rtsp_user || device.credentials.rtsp_password || device.credentials.onvif_user || device.credentials.onvif_password);
      return {
        ...device,
        credentials: hasCreds ? device.credentials : emptyCredentials(),
      };
    });
    render();
    setStatus(
      data.scan_note
        ? `Found ${state.devices.length} device(s). ${data.scan_note}`
        : `Found ${state.devices.length} device(s)`
    );
  } catch (error) {
    setStatus(`Error: ${error.message}`);
  } finally {
    clearInterval(pollInterval);
    els.progressWrap.style.display = "none";
    setBusy(false);
  }
}

async function verifyRtsp() {
  syncCredentialsFromRows();
  setBusy(true, "Verifying RTSP");
  try {
    const payload = {
      channel: Number(els.channel?.value || 1),
      devices: state.devices,
    };
    const data = await postJson("/api/verify-rtsp", payload);
    state.devices = mergeDevices(state.devices, data.devices);
    render();
    setStatus("RTSP verify done");
  } catch (error) {
    setStatus(`Error: ${error.message}`);
  } finally {
    setBusy(false);
  }
}

function applyDefaultCredentials() {
  const defaults = {
    rtsp_user: els.rtspUser.value,
    rtsp_password: els.rtspPassword.value,
    onvif_user: els.onvifUser.value || els.rtspUser.value,
    onvif_password: els.onvifPassword.value || els.rtspPassword.value,
  };
  state.devices = state.devices.map((device) => ({
    ...device,
    credentials: { ...defaults },
  }));
  render();
  setStatus("Credentials applied");
}

function syncCredentialsFromRows() {
  // Credentials are now managed directly via the config modal
}

function render() {
  els.verify.disabled = state.devices.length === 0;
  els.applyCreds.disabled = state.devices.length === 0;
  renderSummary();
  renderRows();
}

function renderSummary() {
  const total = state.devices.length;
  const rtsp = state.devices.filter((device) => device.rtsp_open).length;
  const onvif = state.devices.filter((device) => device.onvif_found).length;
  const ok = state.devices.filter((device) => device.rtsp_auth_status === "OK").length;
  const values = [total, rtsp, onvif, ok];

  [...els.summary.querySelectorAll("strong")].forEach((node, index) => {
    node.textContent = values[index];
  });
}

function renderRows() {
  if (!state.devices.length) {
    els.rows.innerHTML = `<tr class="empty-row"><td colspan="7">ยังไม่มีข้อมูล กด Scan เพื่อค้นหากล้องในวง LAN</td></tr>`;
    return;
  }

  els.rows.innerHTML = state.devices.map((device, index) => {
    const rtspCred = device.credentials?.rtsp_user ? "RTSP: " + device.credentials.rtsp_user : "RTSP: -";
    const onvifCred = device.credentials?.onvif_user ? "ONVIF: " + device.credentials.onvif_user : "ONVIF: -";
    const hasCreds = device.credentials?.rtsp_user || device.credentials?.onvif_user;
    const chipTone = hasCreds ? "ok" : "warn";
    const chipText = hasCreds ? "Configured" : "Not Configured";

    let signalHtml = "";
    if (device.channels_status) {
      const validChannels = device.channels_status.filter(ch => ch.status === "ONLINE" || ch.status === "VIDEO_LOSS");
      if (validChannels.length > 0) {
        signalHtml = validChannels.map(ch => {
          const isOnline = ch.status === "ONLINE";
          const badgeClass = isOnline ? "channel-badge online" : "channel-badge loss";
          const statusText = isOnline ? `🟢 CH${ch.channel}` : `🔴 CH${ch.channel}`;
          const titleText = isOnline ? `Online (${ch.bytes.toLocaleString()} B)` : `Video Loss (${ch.bytes.toLocaleString()} B)`;
          return `<span class="${badgeClass}" title="${titleText}">${statusText}</span>`;
        }).join(" ") + `
          <div style="margin-top: 6px;">
            <button class="btn-check-signal" style="background: var(--ok); border-color: var(--ok); color: #fff; height: 26px; font-size: 11px;" onclick="addToDashboard(${index})">➕ Add to Dashboard</button>
          </div>
        `;
      } else {
        const firstChan = device.channels_status[0];
        signalHtml = `<span class="chip bad">⚠️ ERROR (${firstChan.error || "Unknown"})</span>`;
      }
    } else if (device.rtsp_auth_status === "ONLINE" || device.rtsp_auth_status === "VIDEO_LOSS") {
      const isOnline = device.rtsp_auth_status === "ONLINE";
      const badgeClass = isOnline ? "channel-badge online" : "channel-badge loss";
      const statusText = isOnline ? `🟢 ONLINE` : `🔴 VIDEO LOSS`;
      signalHtml = `<span class="${badgeClass}">${statusText}</span>
          <div style="margin-top: 6px;">
            <button class="btn-check-signal" style="background: var(--ok); border-color: var(--ok); color: #fff; height: 26px; font-size: 11px;" onclick="addToDashboard(${index})">➕ Add to Dashboard</button>
          </div>`;
    }

    return `
      <tr>
        <td><strong><a href="#" class="ip-link" onclick="openConfigModal(${index}); return false;">${escapeHtml(device.ip)}</a></strong></td>
        <td>
          <div>${escapeHtml(device.mac || "-")}</div>
          <div class="ports">${escapeHtml(formatPorts(device.open_ports))}</div>
        </td>
        <td>${escapeHtml(device.manufacturer || "Unknown")}<br><span class="chip">${escapeHtml(device.brand_key)}</span></td>
        <td>${escapeHtml(device.model || "Unknown")}</td>
        <td>
          <div class="chips">
            ${chip(device.rtsp_open ? "RTSP OPEN" : "RTSP CLOSED", device.rtsp_open ? "ok" : "bad")}
            ${chip(device.onvif_found ? "ONVIF YES" : "ONVIF NO", device.onvif_found ? "ok" : "warn")}
            ${authChip(device.rtsp_auth_status)}
          </div>
        </td>
        <td>
          <div class="chips">
            ${chip(chipText, chipTone)}
          </div>
          <div style="font-size: 11px; margin-top: 4px; color: var(--muted);">
            ${escapeHtml(rtspCred)}<br>${escapeHtml(onvifCred)}
          </div>
        </td>
        <td class="url-cell">
          <div>RTSP: <span id="rtspDisplay-${index}">${escapeHtml(device.rtsp_url || "-")}</span></div>
          <div>ONVIF: ${escapeHtml(device.xaddr || "-")}</div>
          <div style="margin-top: 8px; display: flex; flex-wrap: wrap; align-items: center; gap: 8px;">
            <button class="btn-check-signal" onclick="checkSignal(${index}, this)">Auto Check</button>
            <button class="btn-manual-rtsp" onclick="promptManualRtsp(${index})">Manual URL</button>
            <span id="signalStatus-${index}">${signalHtml}</span>
          </div>
        </td>
      </tr>
    `;
  }).join("");
}

function chip(text, tone) {
  return `<span class="chip ${tone}">${escapeHtml(text)}</span>`;
}

function authChip(status) {
  const value = status || "NOT_CHECKED";
  if (value === "OK") return chip(value, "ok");
  if (value === "NOT_CHECKED" || value === "NO_CREDENTIAL") return chip(value, "warn");
  return chip(value, "bad");
}

function formatPorts(ports) {
  if (!ports || !ports.length) return "-";
  const visible = ports.slice(0, 10).join(", ");
  return ports.length > 10 ? `${visible}, ...` : visible;
}

function fieldValue(index, field) {
  const input = els.rows.querySelector(`[data-index="${index}"][data-field="${field}"]`);
  return input ? input.value : "";
}

async function postJson(url, payload) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || response.statusText);
  return data;
}

function mergeDevices(current, updates) {
  const byIp = new Map(current.map((device) => [device.ip, device]));
  return updates.map((device) => ({
    ...(byIp.get(device.ip) || {}),
    ...device,
    credentials: byIp.get(device.ip)?.credentials || emptyCredentials(),
  }));
}

function emptyCredentials() {
  return {
    rtsp_user: "",
    rtsp_password: "",
    onvif_user: "",
    onvif_password: "",
  };
}

function setBusy(busy, label = "Working") {
  els.scan.disabled = busy;
  els.verify.disabled = busy || state.devices.length === 0;
  els.applyCreds.disabled = busy || state.devices.length === 0;
  if (busy) setStatus(label);
}

function setStatus(text) {
  els.status.textContent = text;
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

function escapeAttr(value) {
  return escapeHtml(value).replace(/`/g, "&#096;");
}

async function checkSignal(index, btn = null) {
  const device = state.devices[index];
  if (!device) return;

  const statusEl = document.querySelector(`#signalStatus-${index}`);

  if (btn) btn.disabled = true;
  statusEl.textContent = "Checking...";
  statusEl.className = "";

  try {
    const payload = {
      ip: device.ip,
      port: device.open_ports.includes(554) ? 554 : (device.open_ports[0] || 554),
      brand_key: device.brand_key,
      credentials: device.credentials,
      channel: Number(els.channel?.value || 1),
      custom_rtsp_url: device.rtsp_url_manual ? device.rtsp_url : null
    };
    const res = await postJson("/api/check-signal", payload);
    
    if (res.rtsp_url) {
      device.rtsp_url = res.rtsp_url;
      const displayEl = document.querySelector(`#rtspDisplay-${index}`);
      if (displayEl) {
        displayEl.textContent = res.rtsp_url;
      }
    }

    if (res.channels) {
      device.channels_status = res.channels;
      const validChannels = res.channels.filter(ch => ch.status === "ONLINE" || ch.status === "VIDEO_LOSS");
      if (validChannels.length > 0) {
        statusEl.innerHTML = validChannels.map(ch => {
          const isOnline = ch.status === "ONLINE";
          const badgeClass = isOnline ? "channel-badge online" : "channel-badge loss";
          const statusText = isOnline ? `🟢 CH${ch.channel}` : `🔴 CH${ch.channel}`;
          const titleText = isOnline ? `Online (${ch.bytes.toLocaleString()} B)` : `Video Loss (${ch.bytes.toLocaleString()} B)`;
          return `<span class="${badgeClass}" title="${titleText}">${statusText}</span>`;
        }).join(" ") + `
          <div style="margin-top: 6px;">
            <button class="btn-check-signal" style="background: var(--ok); border-color: var(--ok); color: #fff; height: 26px; font-size: 11px;" onclick="addToDashboard(${index})">➕ Add to Dashboard</button>
          </div>
        `;
      } else {
        const firstChan = res.channels[0];
        statusEl.innerHTML = `<span class="chip bad">⚠️ ERROR (${firstChan.error || "Unknown"})</span>`;
      }
    } else if (res.status === "ONLINE") {
      statusEl.innerHTML = `<span class="chip ok">🟢 ONLINE (${res.bytes.toLocaleString()} B)</span>`;
    } else if (res.status === "VIDEO_LOSS") {
      statusEl.innerHTML = `<span class="chip bad">🔴 VIDEO LOSS (${res.bytes.toLocaleString()} B)</span>`;
    } else {
      statusEl.innerHTML = `<span class="chip warn">⚠️ ERROR (${res.error || "Unknown"})</span>`;
    }
  } catch (err) {
    statusEl.innerHTML = `<span class="chip bad">⚠️ ERROR (${err.message})</span>`;
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function promptManualRtsp(index) {
  const device = state.devices[index];
  if (!device) return;

  const currentUrl = device.rtsp_url || "";
  const customUrl = prompt("Enter Custom RTSP URL for " + device.ip + ":\n(Example: rtsp://admin:password@ip:port/h264/ch1/main/av_stream)", currentUrl);
  
  if (customUrl === null) return;
  
  const trimmed = customUrl.trim();
  device.rtsp_url = trimmed;
  device.rtsp_url_manual = trimmed !== "";

  const displayEl = document.querySelector(`#rtspDisplay-${index}`);
  if (displayEl) {
    displayEl.textContent = trimmed || "-";
  }

  try {
    await postJson("/api/update-device-rtsp", {
      ip: device.ip,
      rtsp_url: trimmed,
      rtsp_url_manual: device.rtsp_url_manual
    });
  } catch (err) {
    console.error("Failed to save manual RTSP URL:", err);
  }

  const rowEl = els.rows.children[index];
  const autoCheckBtn = rowEl ? rowEl.querySelector(".btn-check-signal") : null;
  checkSignal(index, autoCheckBtn);
}

async function addToDashboard(index) {
  const device = state.devices[index];
  if (!device) return;

  const btn = event.currentTarget;
  if (btn) btn.disabled = true;

  try {
    const payload = {
      ip: device.ip,
      mac: device.mac,
      manufacturer: device.manufacturer,
      model: device.model,
      brand_key: device.brand_key,
      open_ports: device.open_ports,
      rtsp_url: device.rtsp_url,
      rtsp_url_manual: device.rtsp_url_manual,
      credentials: device.credentials,
      channels_status: device.channels_status || [
        { channel: 1, status: device.rtsp_auth_status, bytes: 11000 }
      ]
    };
    
    await postJson("/api/dashboard/add", payload);
    alert(`Successfully added ${device.ip} to the dashboard!`);
  } catch (err) {
    alert(`Failed to add: ${err.message}`);
  } finally {
    if (btn) btn.disabled = false;
  }
}
