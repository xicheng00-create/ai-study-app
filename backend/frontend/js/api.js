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
  }

  return {
    get: (p) => request(p),
    post: (p, json) => request(p, { method: "POST", json }),
    put: (p, json) => request(p, { method: "PUT", json }),
    del: (p) => request(p, { method: "DELETE" }),
    upload: (p, formData) => request(p, { method: "POST", body: formData }),
    getToken, setToken,
  };
})();
