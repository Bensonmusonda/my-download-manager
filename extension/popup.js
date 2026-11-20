/**
 * Smart Download Manager — Popup Script
 * Modernized UI controller with live telemetry and feedback toasts.
 */

document.addEventListener("DOMContentLoaded", async () => {
  const appStatus = document.getElementById("appStatus");
  const appStatusText = document.getElementById("appStatusText");
  const tabDomain = document.getElementById("tabDomain");
  const cfStatus = document.getElementById("cfStatus");
  const cookieCount = document.getElementById("cookieCount");
  const sendSessionBtn = document.getElementById("sendSessionBtn");
  const sendUrlBtn = document.getElementById("sendUrlBtn");
  const autoCatchToggle = document.getElementById("autoCatchToggle");
  const toastMsg = document.getElementById("toastMsg");

  let toastTimer = null;

  function showToast(msg, isError = false) {
    if (toastTimer) clearTimeout(toastTimer);
    toastMsg.textContent = msg;
    toastMsg.className = `toast ${isError ? "error" : "success"}`;
    toastTimer = setTimeout(() => {
      toastMsg.className = "toast";
      toastMsg.textContent = "";
    }, 4000);
  }

  // 1. Check autoCatch setting
  try {
    const settings = await chrome.storage.local.get({ autoCatch: true });
    autoCatchToggle.checked = settings.autoCatch;

    autoCatchToggle.addEventListener("change", async (e) => {
      await chrome.storage.local.set({ autoCatch: e.target.checked });
      showToast(e.target.checked ? "✔ Auto-catch downloads enabled" : "ℹ Auto-catch disabled");
    });
  } catch (err) {
    console.warn("Storage error:", err);
  }

  // 2. Check connection to desktop bridge server (port 8992)
  chrome.runtime.sendMessage({ type: "CHECK_STATUS" }, (response) => {
    if (response && response.online) {
      appStatus.className = "status-badge online";
      appStatusText.textContent = "Bridge Active";
    } else {
      appStatus.className = "status-badge offline";
      appStatusText.textContent = "App Offline";
    }
  });

  // 3. Inspect active tab for domain and Cloudflare cookies
  try {
    const [activeTab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (activeTab && activeTab.url && activeTab.url.startsWith("http")) {
      const parsed = new URL(activeTab.url);
      tabDomain.textContent = parsed.hostname;
      tabDomain.title = activeTab.url;

      const cookiesMap = new Map();
      let hasCf = false;

      // Harvest by URL
      try {
        const byUrl = await chrome.cookies.getAll({ url: activeTab.url });
        if (byUrl) {
          for (const c of byUrl) {
            cookiesMap.set(c.name, c.value);
            if (c.name === "cf_clearance") hasCf = true;
          }
        }
      } catch (e) {}

      // Harvest by domain
      try {
        const byDomain = await chrome.cookies.getAll({ domain: parsed.hostname });
        if (byDomain) {
          for (const c of byDomain) {
            cookiesMap.set(c.name, c.value);
            if (c.name === "cf_clearance") hasCf = true;
          }
        }
      } catch (e) {}

      if (hasCf) {
        cfStatus.innerHTML = '<span class="pill-status pill-cf-active">🛡 cf_clearance active</span>';
      } else if (cookiesMap.size > 0) {
        cfStatus.innerHTML = '<span class="pill-status pill-cf-none">🌐 Session Ready</span>';
      } else {
        cfStatus.innerHTML = '<span class="pill-status pill-cf-neutral">No cookies</span>';
      }

      cookieCount.textContent = `${cookiesMap.size} harvested`;
    } else {
      tabDomain.textContent = "Non-web page";
      cfStatus.innerHTML = '<span class="pill-status pill-cf-neutral">--</span>';
      cookieCount.textContent = "0";
      sendSessionBtn.disabled = true;
      sendUrlBtn.disabled = true;
    }
  } catch (err) {
    tabDomain.textContent = "Unable to read tab";
    console.error("Tab query error:", err);
  }

  // 4. Send session & Referer to desktop app
  sendSessionBtn.addEventListener("click", () => {
    sendSessionBtn.disabled = true;
    sendSessionBtn.querySelector("span").textContent = "Sending Session...";

    chrome.runtime.sendMessage({ type: "SEND_ACTIVE_TAB" }, (res) => {
      sendSessionBtn.disabled = false;
      sendSessionBtn.querySelector("span").textContent = "Send Session & Referer to App";

      if (res && res.success) {
        const msg = res.cookieInfo?.hasCfClearance
          ? "✅ cf_clearance session synced to App!"
          : "✅ Cookies & Referer synced to App!";
        showToast(msg);
      } else {
        showToast("Failed: Is Smart Download Manager running?", true);
      }
    });
  });

  // 5. Send page URL as a download task
  sendUrlBtn.addEventListener("click", () => {
    sendUrlBtn.disabled = true;
    sendUrlBtn.querySelector("span").textContent = "Dispatching Task...";

    chrome.runtime.sendMessage({ type: "DOWNLOAD_ACTIVE_TAB" }, (res) => {
      sendUrlBtn.disabled = false;
      sendUrlBtn.querySelector("span").textContent = "Download Page URL in App";

      if (res && res.success) {
        showToast("⬇ Task dispatched to Smart Downloader!");
      } else {
        showToast("Failed: Is Smart Downloader running on port 8992?", true);
      }
    });
  });
});
