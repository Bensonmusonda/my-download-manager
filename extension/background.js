/**
 * Smart Download Manager — Background Service Worker
 * 
 * Captures browser sessions (cf_clearance cookies & User-Agent)
 * and forwards downloads with anti-hotlink Referer headers to the local desktop app.
 */

const BRIDGE_URL = "http://127.0.0.1:8992";

// ── Cookie Harvesting Helper ──────────────────────────────────────────

async function getCookiesForUrl(urlStr, refererStr = "") {
  try {
    const cookiesMap = new Map();
    let hasCfClearance = false;

    // 1. Fetch cookies by exact target URL
    try {
      const byUrl = await chrome.cookies.getAll({ url: urlStr });
      if (byUrl) {
        for (const c of byUrl) {
          cookiesMap.set(c.name, c.value);
          if (c.name === "cf_clearance") hasCfClearance = true;
        }
      }
    } catch (e) {}

    // 2. Fetch cookies by target domain
    try {
      const parsed = new URL(urlStr);
      const byDomain = await chrome.cookies.getAll({ domain: parsed.hostname });
      if (byDomain) {
        for (const c of byDomain) {
          cookiesMap.set(c.name, c.value);
          if (c.name === "cf_clearance") hasCfClearance = true;
        }
      }
    } catch (e) {}

    // 3. If referer URL is provided (e.g. kwik.cx for uwucdn.top), also harvest referer cookies!
    if (refererStr && refererStr.startsWith("http")) {
      try {
        const refCookies = await chrome.cookies.getAll({ url: refererStr });
        if (refCookies) {
          for (const c of refCookies) {
            if (!cookiesMap.has(c.name)) {
              cookiesMap.set(c.name, c.value);
            }
            if (c.name === "cf_clearance") hasCfClearance = true;
          }
        }
        const refParsed = new URL(refererStr);
        const refByDomain = await chrome.cookies.getAll({ domain: refParsed.hostname });
        if (refByDomain) {
          for (const c of refByDomain) {
            if (!cookiesMap.has(c.name)) {
              cookiesMap.set(c.name, c.value);
            }
            if (c.name === "cf_clearance") hasCfClearance = true;
          }
        }
      } catch (e) {}
    }

    const parts = [];
    for (const [name, val] of cookiesMap.entries()) {
      parts.push(`${name}=${val}`);
    }

    return {
      cookieHeader: parts.join("; "),
      hasCfClearance: hasCfClearance,
      count: cookiesMap.size,
    };
  } catch (err) {
    console.error("Failed to read cookies:", err);
    return { cookieHeader: "", hasCfClearance: false, count: 0 };
  }
}

// ── Bridge Communication ──────────────────────────────────────────────

async function pingDesktopApp() {
  try {
    const res = await fetch(`${BRIDGE_URL}/status`, { method: "GET" });
    if (res.ok) {
      return await res.json();
    }
  } catch (e) {
    // Desktop app is not running
  }
  return null;
}

async function sendDownloadToApp(payload) {
  try {
    const res = await fetch(`${BRIDGE_URL}/download`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    return res.ok;
  } catch (err) {
    console.warn("Could not reach desktop app at", BRIDGE_URL, err);
    return false;
  }
}

async function sendSessionToApp(payload) {
  try {
    const res = await fetch(`${BRIDGE_URL}/session`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    return res.ok;
  } catch (err) {
    console.warn("Could not reach desktop app at", BRIDGE_URL, err);
    return false;
  }
}

// ── Context Menus ─────────────────────────────────────────────────────

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({
    id: "sdm-download-link",
    title: "⬇ Download with Smart Downloader",
    contexts: ["link"],
  });

  chrome.contextMenus.create({
    id: "sdm-send-session",
    title: "🛡 Send Session & Referer to Downloader",
    contexts: ["page"],
  });
});

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  const pageUrl = tab ? tab.url : "";

  if (info.menuItemId === "sdm-download-link") {
    const linkUrl = info.linkUrl;
    if (!linkUrl) return;

    const cookieInfo = await getCookiesForUrl(linkUrl, pageUrl);
    const payload = {
      url: linkUrl,
      referer: pageUrl,
      cookies: cookieInfo.cookieHeader,
      user_agent: navigator.userAgent,
      filename: "",
    };

    const sent = await sendDownloadToApp(payload);
    if (!sent) {
      chrome.notifications?.create({
        type: "basic",
        iconUrl: "icons/icon128.png",
        title: "Smart Download Manager",
        message: "Desktop app is not running. Please launch Smart Downloader first.",
      });
    }
  } else if (info.menuItemId === "sdm-send-session") {
    if (!pageUrl) return;

    const cookieInfo = await getCookiesForUrl(pageUrl);
    const payload = {
      url: pageUrl,
      domain: new URL(pageUrl).hostname,
      referer: pageUrl,
      cookies: cookieInfo.cookieHeader,
      user_agent: navigator.userAgent,
      has_cf_clearance: cookieInfo.hasCfClearance,
    };

    const sent = await sendSessionToApp(payload);
    if (sent) {
      chrome.notifications?.create({
        type: "basic",
        iconUrl: "icons/icon128.png",
        title: "Session Captured",
        message: cookieInfo.hasCfClearance
          ? "✅ cf_clearance & Referer sent to Smart Downloader!"
          : "Session cookies & Referer sent to Smart Downloader.",
      });
    }
  }
});

// ── Download Interception (Auto-Catch) ─────────────────────────────────

chrome.downloads.onCreated.addListener(async (downloadItem) => {
  const settings = await chrome.storage.local.get({ autoCatch: true });
  if (!settings.autoCatch) return;

  const url = downloadItem.finalUrl || downloadItem.url;
  if (!url || !url.startsWith("http")) return;

  const appStatus = await pingDesktopApp();
  if (!appStatus) {
    return;
  }

  // Get active tab to determine source Referer
  const [activeTab] = await chrome.tabs.query({ active: true, currentWindow: true });
  const referer = downloadItem.referrer || (activeTab ? activeTab.url : "");

  const cookieInfo = await getCookiesForUrl(url, referer);
  const payload = {
    url: url,
    referer: referer,
    cookies: cookieInfo.cookieHeader,
    user_agent: navigator.userAgent,
    filename: downloadItem.filename || "",
  };

  const sent = await sendDownloadToApp(payload);
  if (sent) {
    try {
      chrome.downloads.cancel(downloadItem.id, () => {
        chrome.downloads.erase({ id: downloadItem.id });
      });
    } catch (e) {}
  }
});

// ── Messages from Popup ────────────────────────────────────────────────

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type === "CHECK_STATUS") {
    pingDesktopApp().then((status) => sendResponse({ online: !!status, status }));
    return true;
  }

  if (message.type === "SEND_ACTIVE_TAB") {
    chrome.tabs.query({ active: true, currentWindow: true }).then(async (tabs) => {
      if (!tabs || tabs.length === 0) {
        sendResponse({ success: false, error: "No active tab" });
        return;
      }
      const activeTab = tabs[0];
      const cookieInfo = await getCookiesForUrl(activeTab.url);

      const payload = {
        url: activeTab.url,
        domain: new URL(activeTab.url).hostname,
        referer: activeTab.url,
        cookies: cookieInfo.cookieHeader,
        user_agent: navigator.userAgent,
        has_cf_clearance: cookieInfo.hasCfClearance,
        count: cookieInfo.count,
      };

      const sent = await sendSessionToApp(payload);
      sendResponse({ success: sent, cookieInfo, referer: activeTab.url });
    });
    return true;
  }
});
