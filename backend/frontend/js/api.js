/* fetch 封装：JWT Bearer、统一 {code,data,msg} 契约、401 登出、错误抛出 */
const API = (() => {
  const TOKEN_KEY = "aistudy_token";

  function getToken() { return localStorage.getItem(TOKEN_KEY) || ""; }
  function setToken(t) { t ? localStorage.setItem(TOKEN_KEY, t) : localStorage.removeItem(TOKEN_KEY); }

  async function request(path, opts = {}) {
    const headers = Object.assign({}, opts.headers || {});
    if (opts.json !== undefined) headers["Content-Type"] = "application/json";
    const token = getToken();
    if (token) headers["Authorization"] = "Bearer " + token;
    // 全局加载指示器（无则静默跳过，兼容 api.js 先于 app.js 加载）
    if (typeof loadingOn === "function") loadingOn();
    try {
      const resp = await fetch(path, {
        method: opts.method || "GET",
        headers,
        body: opts.json !== undefined ? JSON.stringify(opts.json) : opts.body,
      });
      let body = {};
      try { body = await resp.json(); } catch (e) { /* 非 JSON */ }
      if (resp.status === 401 && !path.startsWith("/api/auth/login")) {
        setToken("");
        if (typeof onUnauthorized === "function") onUnauthorized();
        throw new Error("登录已过期");
      }
      if (!resp.ok || (body.code && body.code !== 0)) {
        const msg = (body && body.msg) || ("请求失败 " + resp.status);
        throw new Error(msg);
      }
      return body.data;
    } finally {
      if (typeof loadingOff === "function") loadingOff();
    }
  }

  return {
    get: (p) => request(p),
    post: (p, json) => request(p, { method: "POST", json }),
    put: (p, json) => request(p, { method: "PUT", json }),
    del: (p) => request(p, { method: "DELETE" }),
    upload: (p, formData) => request(p, { method: "POST", body: formData }),
    // 方案B：下载源文件（带 Bearer，分块流式 + 进度百分比）
    async download(id, filename) {
      const token = getToken();
      try {
        const resp = await fetch(`/api/materials/${id}/download`, {
          headers: token ? { "Authorization": "Bearer " + token } : {},
        });
        if (!resp.ok) {
          let msg = "下载失败";
          try { const b = await resp.json(); msg = b.msg || msg; } catch (e) { /* ignore */ }
          throw new Error(msg);
        }
        // 分块流式下载：Content-Length 可得 → 显示进度百分比；否则只显示已下载大小
        this._dlProgress(resp);
        const blob = await this._streamToBlob(resp);
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url; a.download = filename || "download";
        document.body.appendChild(a); a.click(); a.remove();
        // 延迟 revoke：避免浏览器还没读取 blob 就撤销导致「download load failed」
        setTimeout(function () { URL.revokeObjectURL(url); }, 120000);
        this._dlProgressDone();
        toast("已开始下载");
      } catch (e) {
        throw e;
      }
    },
    // 分块流式读取 resp.body，边读边更新进度，返回完整 Blob（内存友好且能看到进度）
    async _streamToBlob(resp) {
      const total = parseInt(resp.headers.get("Content-Length") || "0", 10);
      if (!resp.body || !resp.body.getReader) {
        // 无流式能力（如老浏览器）→ 退化为一次 blob
        return resp.blob();
      }
      const reader = resp.body.getReader();
      const chunks = [];
      let received = 0;
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        chunks.push(value);
        received += value.length;
        this._dlProgressUpdate(received, total);
      }
      return new Blob(chunks);
    },
    // 进度指示：无总长只显示已下载 MB，有总长显示百分比（同时更新进度条宽度）
    _dlProgress(resp) {
      const total = parseInt(resp.headers.get("Content-Length") || "0", 10);
      if (typeof $ === "undefined" || !document.getElementById("dlProgress")) return;
      const bar = document.getElementById("dlProgress");
      bar.style.display = "flex";
      const txt = document.getElementById("dlProgressTxt");
      if (total > 0) { txt.textContent = "下载中 0%"; } else { txt.textContent = "准备下载…"; }
      const pct = document.getElementById("dlProgressPct");
      if (pct) pct.style.width = "0%";
    },
    _dlProgressUpdate(received, total) {
      if (typeof $ === "undefined" || !document.getElementById("dlProgress")) return;
      const txt = document.getElementById("dlProgressTxt");
      const pct = document.getElementById("dlProgressPct");
      if (!txt) return;
      const mb = (received / (1024 * 1024)).toFixed(1);
      if (total > 0) {
        const p = Math.min(100, Math.round((received / total) * 100));
        txt.textContent = `下载中 ${p}%`;
        if (pct) pct.style.width = p + "%";
      } else {
        txt.textContent = `下载中 ${mb} MB`;
      }
    },
    _dlProgressDone() {
      if (typeof $ === "undefined" || !document.getElementById("dlProgress")) return;
      const bar = document.getElementById("dlProgress");
      setTimeout(function () { bar.style.display = "none"; }, 600);
    },
    getToken, setToken,
  };
})();
