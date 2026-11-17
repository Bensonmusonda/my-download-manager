# Chrome Extension & Session Bridge Guide

The **Smart Download Manager Bridge** is a companion browser extension for Google Chrome, Microsoft Edge, and Brave. It solves Cloudflare blocks permanently by sharing authentic browser sessions (especially **`cf_clearance`** cookies) directly with the desktop app.

---

## 1. Why the Extension Solves the Cloudflare Problem

When you download a file from a Cloudflare-protected site, Cloudflare verifies:
1. **Your IP Address** (matches).
2. **`cf_clearance` Cookie** (issued to you after passing the Turnstile/captcha challenge).
3. **Exact User-Agent Header** (must match the browser that solved the challenge).
4. **TLS Fingerprint (JA3/JA4)** (must match Chrome's TLS handshake).

### The Previous Obstacle:
On Windows, Chrome locks its SQLite cookie database while running, and Chrome 127+ uses App-Bound Encryption, preventing Python scripts from reading cookies off the hard drive while you browse.

### The Extension Solution:
The extension runs inside Chrome with official user permissions. When you pass a challenge:
- It reads the **live, unencrypted `cf_clearance` cookie** directly via `chrome.cookies.getAll()`.
- It captures your exact `navigator.userAgent`.
- It sends this session payload over a local, private HTTP bridge (`http://127.0.0.1:8992`).
- Smart Download Manager's `curl_cffi` engine impersonates Chrome's TLS fingerprint and uses your exact session cookies.
- **Cloudflare sees the download request as 100% legitimate browser traffic.**

---

## 2. Step-by-Step Installation (Takes 30 Seconds)

The extension is located in the [`extension/`](file:///d:/Projects/my_smart_downloader/extension) folder of this repository.

1. Open **Google Chrome** (or Edge / Brave).
2. Navigate to:
   ```text
   chrome://extensions/
   ```
3. Enable **Developer mode** using the toggle switch in the top-right corner.
4. Click the **Load unpacked** button in the top-left corner.
5. In the file picker, select the extension folder:
   ```text
   d:\Projects\my_smart_downloader\extension
   ```
6. The **Smart Download Manager Bridge** icon will appear in your Chrome toolbar. Pin it for easy access!

---

## 3. How to Use It

### Method A: One-Click Cloudflare Session Sharing
1. In Chrome, browse to the download page and solve the Cloudflare challenge (if prompted).
2. Click the **Smart Downloader** extension icon in your toolbar.
3. You will see:
   - Current Tab domain.
   - Status: `✅ cf_clearance active`.
4. Click **🛡 Send Session (cf_clearance) to App**.
5. Smart Downloader will immediately display:
   ```text
   Received live cf_clearance for example.com!
   ```
   Any current or subsequent downloads for that site will download without being blocked!

### Method B: Right-Click Context Menu
1. Right-click any download link on any webpage.
2. Select **⬇ Download with Smart Downloader**.
3. The link, Referer, User-Agent, and all cookies are instantly forwarded to the desktop app.
4. The download starts automatically with multi-connection speed boosting.

### Method C: Automatic Download Catching
1. In the extension popup, make sure **"Auto-catch downloads"** is checked (enabled by default).
2. Whenever you click a download button on any site:
   - The extension detects the download.
   - It captures the session cookies for that domain.
   - Dispatches the task to Smart Download Manager.
   - Cancels Chrome's native single-stream download so Smart Downloader can download it at maximum speed.

---

## 4. Privacy & Security

- **Local Only**: The bridge operates exclusively over loopback (`127.0.0.1:8992`). No data ever leaves your computer or goes to any remote server.
- **No Third-Party Cloud**: Open-source, transparent Manifest V3 implementation.

