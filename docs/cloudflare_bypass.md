# Cloudflare & Browser Session Integration

Many download portals and file mirrors sit behind Cloudflare protections (Turnstile challenge, "Under Attack" interstitial, or JA3/JA4 TLS fingerprint filtering). Standard HTTP clients (like Python `requests` or `urllib`) are instantly blocked with HTTP 403 or HTML challenge pages.

Smart Download Manager integrates two technologies to bypass these blocks:

---

## 1. Browser-Grade TLS Fingerprinting (`curl_cffi`)

Standard Python clients announce distinctive OpenSSL cipher suites and TLS extension orders that Cloudflare anti-bot systems flag as non-browser traffic.

Smart Download Manager uses `curl_cffi` compiled with `impersonate="chrome"`:
- Matches authentic Google Chrome TLS Client Hello packets.
- Emulates Chrome's HTTP/2 frames, stream priorities, and header ordering.
- Spoofs the JA3 and JA4 TLS fingerprints.

---

## 2. Automatic Cookie Extraction (`cf_clearance`)

When you solve a Cloudflare challenge in your web browser (Chrome, Edge, or Firefox), Cloudflare sets an authentication cookie called **`cf_clearance`**.

Before starting any download, Smart Download Manager's [`browser_session.py`](file:///d:/Projects/my_smart_downloader/browser_session.py):
1. Identifies the domain of your download URL.
2. Scans your local browser cookie stores:
   - Google Chrome
   - Microsoft Edge
   - Mozilla Firefox
3. Extracts matching cookies for that domain, prioritizing sessions that hold `cf_clearance`.
4. Reads your browser's authentic User-Agent (including exact Chrome version from `%LOCALAPPDATA%\Google\Chrome\User Data\Local State`).
5. Injects these cookies and User-Agent headers into every HTTP request.

---

## 3. Best Practices If You Encounter a Block

If a server blocks your download:
1. Open the download link in **Google Chrome**, **Edge**, or **Firefox**.
2. Solve the Cloudflare Turnstile or captcha challenge in the browser until the file starts downloading or the direct download button appears.
3. Cancel the in-browser download (if it started).
4. Run Smart Download Manager:
   ```powershell
   python __main__.py
   ```
5. Paste the download URL. The manager will immediately pick up the fresh `cf_clearance` cookie from your browser and download without being blocked.

