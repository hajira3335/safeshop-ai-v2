import { onRequestPost } from "../functions/api/check.js";
import { onRequestGet } from "../functions/api/health.js";

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname === "/api/check" && request.method === "POST") return onRequestPost({ request, env });
    if (url.pathname === "/api/health") return onRequestGet({ env });
    return env.ASSETS.fetch(request);
  },
};
