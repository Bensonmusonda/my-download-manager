/**
 * Smart Download Manager — Popup Script
 */

document.addEventListener("DOMContentLoaded", async () => {
  const appStatus = document.getElementById("appStatus");
  const tabDomain = document.getElementById("tabDomain");
  const cfStatus = document.getElementById("cfStatus");
  const cookieCount = document.getElementById("cookieCount");
  const sendSessionBtn = document.getElementById("sendSessionBtn");
  const sendUrlBtn = document.getElementById("sendUrlBtn");
  const autoCatchToggle = document.getElementById("autoCatchToggle");
  const toastMsg = document.getElementById("toastMsg");

  function showToast(msg, isError = false) {
    toastMsg.textContent = msg;
    toastMsg.style.color = isError ? "#f87171" : "#4ade80";
    setTimeout(() => {
      toastMsg.textContent = "";
    }, 3500);
  }

  // 1. Check autoCatch setting
  const settings = await chrome.storage.local.get({ autoCatch: true });
  autoCatchToggle.checked = settings.autoCatch;

  autoCatchToggle.addEventListener("change", async (e) => {
    await chrome.storage.local.set({ autoCatch: e.target.checked });
    showToast(e.target.checked ? "Auto-catch enabled" : "Auto-catch disabled");
  });

  // 2. Check connection to desktop app
  chrome.runtime.sendMessage({ type: "CHECK_STATUS" }, (response) => {
    if (response && response.online) {
      appStatus.textContent = "Connected";
      appStatus.className = "status-badge online";
    } else {
      appStatus.textContent = "App Offline";
      appStatus.className = "status-badge offline";
    }
  });

  // 3. Inspect active tab with robust URL-based cookie search
  const [activeTab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (activeTab && activeTab.url && activeTab.url.startsWith("http")) {
    try {
      const parsed = new URL(activeTab.url);
      tabDomain.textContent = parsed.hostname;

      // Query both URL and domain
      const cookiesMap = new Map();
      let hasCf = false;

      const byUrl = await chrome.cookies.getAll({ url: activeTab.url });
      if (byUrl) {
        for (const c of byUrl) {
          cookiesMap.set(c.name, c.value);
          if (c.name === "cf_clearance") hasCf = true;
        }
      }

      const byDomain = await chrome.cookies.getAll({ domain: parsed.hostname });
      if (byDomain) {
        for (const c of byDomain) {
          cookiesMap.set(c.name, c.value);
          if (c.name === "cf_clearance") hasCf = true;
        }
      }

      if (hasCf) {
        cfStatus.textContent = "🛡 cf_clearance active ✅";
        cfStatus.style.color = "#4ade80";
      } else if (cookiesMap.size > 0) {
        cfStatus.textContent = "🌐 Session ready (no captcha)";
        cfStatus.style.color = "#38bdf8";
      } else {
        cfStatus.textContent = "⚪ No cookies on page";
        cfStatus.style.color = "#9ca3af";
      }

      cookieCount.textContent = `${cookiesMap.size} cookie(s)`;
    } catch (e) {
      tabDomain.textContent = "Invalid URL";
    }
  } else {
    tabDomain.textContent = "Non-web page";
    cfStatus.textContent = "--";
    cookieCount.textContent = "0";
  }

  // 4. Send session button click
  sendSessionBtn.addEventListener("click", () => {
    sendSessionBtn.disabled = true;
    sendSessionBtn.textContent = "Sending...";

    chrome.runtime.sendMessage({ type: "SEND_ACTIVE_TAB" }, (res) => {
      sendSessionBtn.disabled = false;
      sendSessionBtn.textContent = "🛡 Send Session & Referer to App";

      if (res && res.success) {
        showToast(
          res.cookieInfo?.hasCfClearance
            ? "✅ cf_clearance & Referer sent to App!"
            : "✅ Session cookies & Referer sent to App!"
        );
      } else {
        showToast("Failed: Is Smart Downloader running?", true);
      }
    });
  });

  // 5. Send page URL as download
  sendUrlBtn.addEventListener("click", async () => {
    if (!activeTab || !activeTab.url) return;
    sendUrlBtn.disabled = true;

    chrome.runtime.sendMessage({ type: "SEND_ACTIVE_TAB" }, async (res) => {
      sendUrlBtn.disabled = false;
      if (res && res.success) {
        showToast("⬇ Task dispatched to Smart Downloader!");
      } else {
        showToast("Desktop app offline. Launch it first.", true);
      }
    });
  });
});
