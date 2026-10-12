"use strict";
(() => {
  const app = window.Telegram && window.Telegram.WebApp;
  const dom = {
    list: document.getElementById("list"),
    search: document.getElementById("search"),
    count: document.getElementById("count"),
    status: document.getElementById("status"),
    refresh: document.getElementById("refresh"),
    toast: document.getElementById("toast"),
  };
  let items = [];
  let toastHandle;

  function normalize(value) {
    return String(value || "").normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "").toUpperCase().replace(/\s+/g, " ").trim();
  }
  function distance(a, b, max) {
    if (Math.abs(a.length - b.length) > max) return max + 1;
    let previous = Array.from({length: b.length + 1}, (_, i) => i);
    for (let i = 1; i <= a.length; i++) {
      const current = [i];
      let smallest = i;
      for (let j = 1; j <= b.length; j++) {
        const value = Math.min(previous[j] + 1, current[j - 1] + 1,
          previous[j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1));
        current.push(value);
        smallest = Math.min(smallest, value);
      }
      if (smallest > max) return max + 1;
      previous = current;
    }
    return previous[b.length];
  }
  function rank(name, query) {
    if (!query) return 0;
    if (name === query) return 0;
    if (name.startsWith(query)) return 1;
    if (name.includes(query)) return 2;
    const tokens = query.split(" ").filter(Boolean);
    if (tokens.every(t => name.includes(t))) return 3;
    // Typos: conservative edit-distance matching against each customer word.
    const words = name.split(/[^\p{L}\p{N}]+/u).filter(Boolean);
    const ok = tokens.every(token => {
      if (name.includes(token)) return true;
      const tolerance = token.length >= 6 ? 2 : token.length >= 4 ? 1 : 0;
      return tolerance > 0 && words.some(w => distance(w, token, tolerance) <= tolerance);
    });
    return ok ? 10 : -1;
  }
  function safeUrl(url) {
    try {
      const parsed = new URL(url);
      return parsed.protocol === "https:" && parsed.origin === location.origin
        && parsed.pathname.startsWith("/share/") ? parsed.href : null;
    } catch { return null; }
  }
  function showStatus(message) {
    dom.status.textContent = message;
    dom.status.hidden = false;
    dom.list.hidden = true;
  }
  function toast(message) {
    dom.toast.textContent = message;
    dom.toast.hidden = false;
    clearTimeout(toastHandle);
    toastHandle = setTimeout(() => { dom.toast.hidden = true; }, 1700);
  }
  async function copyLink(url) {
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(url);
      } else {
        const input = document.createElement("textarea");
        input.value = url;
        input.style.position = "fixed";
        input.style.opacity = "0";
        document.body.appendChild(input);
        input.focus();
        input.select();
        const ok = document.execCommand("copy");
        input.remove();
        if (!ok) throw new Error("copy failed");
      }
      if (app && app.HapticFeedback) app.HapticFeedback.notificationOccurred("success");
      toast("✓ 已複製連結");
    } catch {
      toast("複製失敗，請長按客戶名稱複製網址");
    }
  }
  function render() {
    const query = normalize(dom.search.value);
    const found = items.map((item, index) =>
      ({ item, index, score: rank(normalize(item.name), query) }))
      .filter(row => row.score >= 0)
      .sort((a, b) => a.score - b.score || a.index - b.index);
    dom.count.textContent = query
      ? "找到 " + found.length + " 位 · 共 " + items.length + " 筆"
      : "全部 " + items.length + " 筆有效分享";
    dom.list.replaceChildren();
    if (!found.length) { showStatus(query ? "沒有找到相關客戶，試試其他名稱。" : "目前沒有有效分享。"); return; }
    const fragment = document.createDocumentFragment();
    for (const {item, index} of found) {
      const row = document.createElement("article");
      row.className = "item";
      const number = document.createElement("span");
      number.className = "number";
      number.textContent = String(index + 1);
      const details = document.createElement("div");
      details.className = "details";
      const name = document.createElement("a");
      name.className = "name";
      name.textContent = item.name;
      name.href = item.url;
      name.target = "_blank";
      name.rel = "noopener noreferrer";
      const expires = document.createElement("div");
      expires.className = "expiry";
      expires.textContent = item.expires ? "有效至 " + item.expires : "永久有效";
      details.append(name, expires);
      const copy = document.createElement("button");
      copy.className = "copy";
      copy.type = "button";
      copy.textContent = "📋 複製";
      copy.setAttribute("aria-label", "複製 " + item.name + " 的網址");
      copy.addEventListener("click", () => copyLink(item.url));
      row.append(number, details, copy);
      fragment.appendChild(row);
    }
    dom.list.appendChild(fragment);
    dom.list.hidden = false;
    dom.status.hidden = true;
  }
  async function load() {
    if (!app || !app.initData) {
      showStatus("請從 Telegram Bot 的「開啟客戶清單」按鈕進入。一般瀏覽器不會顯示公司連結。");
      dom.count.textContent = "未登入";
      return;
    }
    dom.refresh.disabled = true;
    showStatus("正在載入有效客戶分享…");
    try {
      const response = await fetch("/api/telegram/order-shares/directory", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        credentials: "omit",
        cache: "no-store",
        body: JSON.stringify({initData: app.initData}),
      });
      const data = await response.json();
      if (!response.ok || !data.ok || !Array.isArray(data.items)) {
        items = [];
        dom.count.textContent = "無法取得資料";
        showStatus(response.status === 403
          ? "沒有權限：請確認 Telegram 帳號已加入公司私人群組，然後重新開啟。"
          : "資料暫時無法載入，請稍後按更新。");
        return;
      }
      items = data.items.map(item => ({
        name: String(item.name || ""),
        url: safeUrl(item.url),
        expires: item.expires ? String(item.expires) : null,
      })).filter(item => item.name && item.url);
      render();
    } catch {
      items = [];
      dom.count.textContent = "讀取失敗";
      showStatus("網路連線失敗，請按更新再試一次。");
    } finally {
      dom.refresh.disabled = false;
    }
  }
  dom.refresh.addEventListener("click", load);
  dom.search.addEventListener("input", render);
  if (app) {
    try { app.ready(); app.expand(); } catch { /* unsupported client */ }
  }
  load();
})();
