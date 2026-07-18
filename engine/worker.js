import { Container } from "@cloudflare/containers";
import { env as workerEnv } from "cloudflare:workers";

export class HbPdfEngine extends Container {
  defaultPort = 8080;
  sleepAfter = "15m";
  envVars = {
    OPENAI_API_KEY: workerEnv.OPENAI_API_KEY,
    HB_MODEL: workerEnv.HB_MODEL,
    HB_SHARED_SECRET: workerEnv.HB_SHARED_SECRET,
    HB_CACHE_URL: "http://hb-cache",
  };
}

HbPdfEngine.outboundByHost = {
  "hb-cache": async (request, env) => {
    const url = new URL(request.url);
    const key = decodeURIComponent(url.pathname.slice(1));
    if (!/^[a-f0-9]{64}$/.test(key)) {
      return new Response("Invalid cache key", { status: 400 });
    }

    if (request.method === "GET") {
      const value = await env.HB_CACHE.get(key);
      return value === null
        ? new Response(null, { status: 404 })
        : new Response(value, {
            headers: { "Content-Type": "application/json" },
          });
    }

    if (request.method === "PUT") {
      await env.HB_CACHE.put(key, await request.text());
      return new Response(null, { status: 204 });
    }

    return new Response("Method not allowed", { status: 405 });
  },
};

export default {
  async fetch(request, env) {
    const pathname = new URL(request.url).pathname;
    if (pathname !== "/annotate" && pathname !== "/healthz") {
      return new Response("Not found", { status: 404 });
    }
    const container = env.HB_PDF_ENGINE.getByName("primary");
    return container.fetch(request);
  },
};
