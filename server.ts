import express from "express";
import path from "path";
import dotenv from "dotenv";
import { createServer as createViteServer } from "vite";

dotenv.config();

async function startServer() {
  const app = express();

  // Port configuration:
  // - In AI Studio container dev server, MUST bind to 3000 for ingress proxy routing.
  // - In production (bundled dist/server.cjs or PM2), default to 13379 or process.env.PORT.
  const isBundled = typeof __filename === "string" && __filename.endsWith(".cjs");
  const PORT = (process.env.NODE_ENV === "production" || isBundled)
    ? (Number(process.env.PORT) || 13379)
    : 3000;

  app.use(express.json());

  // API Proxy Route for Audiobookshelf:
  // Completely bypasses browser CORS restrictions by fetching server-to-server.
  app.post("/api/proxy/abs", async (req, res) => {
    let controller: AbortController | null = null;
    let timeoutId: NodeJS.Timeout | null = null;
    // Allow up to 300 seconds (5 minutes) for heavy operations such as faster-whisper
    // model downloading, CPU speech-to-text inference on long audio clips, or cold starts.
    const PROXY_TIMEOUT_MS = Number(process.env.PROXY_TIMEOUT_MS) || 300000;

    try {
      const { targetUrl, method = "GET", headers = {}, body } = req.body;
      if (!targetUrl || typeof targetUrl !== "string") {
        return res.status(400).json({ error: "targetUrl is required" });
      }

      // Auto-prefix protocol if omitted
      let cleanTargetUrl = targetUrl.trim();
      if (!cleanTargetUrl.startsWith("http://") && !cleanTargetUrl.startsWith("https://")) {
        cleanTargetUrl = `https://${cleanTargetUrl}`;
      }

      // Ensure valid URL
      const parsedUrl = new URL(cleanTargetUrl);
      if (!["http:", "https:"].includes(parsedUrl.protocol)) {
        return res.status(400).json({ error: "Invalid protocol. Only http and https are allowed." });
      }

      // Sanitize headers: remove hop-by-hop headers and host to avoid breaking upstream SNI/CORS
      const safeHeaders: Record<string, string> = {};
      if (headers && typeof headers === "object") {
        for (const [k, v] of Object.entries(headers)) {
          const lower = k.toLowerCase();
          if (!["host", "connection", "content-length", "keep-alive", "transfer-encoding"].includes(lower) && typeof v === "string") {
            safeHeaders[k] = v;
          }
        }
      }
      safeHeaders["User-Agent"] = safeHeaders["User-Agent"] || "Audiobookshelf-Bookmarks-Extractor/1.0";
      safeHeaders["Accept"] = safeHeaders["Accept"] || "*/*";

      controller = new AbortController();
      timeoutId = setTimeout(() => controller?.abort(), PROXY_TIMEOUT_MS);

      const fetchOptions: RequestInit = {
        method,
        headers: safeHeaders,
        signal: controller.signal,
      };

      if (body && ["POST", "PUT", "PATCH"].includes(method.toUpperCase())) {
        fetchOptions.body = typeof body === "string" ? body : JSON.stringify(body);
        if (!safeHeaders["Content-Type"]) {
          safeHeaders["Content-Type"] = "application/json";
        }
      }

      const response = await fetch(cleanTargetUrl, fetchOptions);
      if (timeoutId) clearTimeout(timeoutId);

      const contentType = response.headers.get("content-type") || "";

      let data;
      if (contentType.includes("application/json")) {
        data = await response.json();
      } else {
        data = await response.text();
      }

      return res.status(200).json({
        ok: response.ok,
        status: response.status,
        statusText: response.statusText,
        data,
      });
    } catch (err: unknown) {
      if (timeoutId) clearTimeout(timeoutId);

      const errObj = err as { name?: string; message?: string; cause?: { message?: string; code?: string } };
      const causeText = errObj?.cause?.message || errObj?.cause?.code || "";
      const isTimeout = errObj?.name === "AbortError";

      let msg = errObj?.message || "Failed to reach remote server";
      if (isTimeout) {
        msg = `Request timed out after ${Math.round(PROXY_TIMEOUT_MS / 1000)} seconds`;
      } else if (causeText) {
        msg = `${msg} (${causeText})`;
      }

      // Helpful context for localhost targets when running in cloud environments
      let hint = "";
      try {
        const parsed = new URL(req.body?.targetUrl || "");
        if (["localhost", "127.0.0.1", "0.0.0.0"].includes(parsed.hostname)) {
          hint = " Note: 'localhost' refers to this cloud container, not your client computer. Connect directly from your browser or use a public tunnel.";
        }
      } catch {}

      console.warn(`[ABS Proxy] Connection warning for ${req.body?.targetUrl || "unknown"}: ${msg}${hint}`);

      return res.status(502).json({
        ok: false,
        status: 502,
        error: "Proxy connection error",
        message: `${msg}${hint}`,
      });
    }
  });

  // System configuration endpoint: provides detected ports & server URLs
  app.get("/api/config", (req, res) => {
    const sidecarPort = process.env.SIDECAR_PORT || 13380;
    const absServer = process.env.ABS_TARGET_SERVER || process.env.ABS_SERVER_URL || "";
    res.json({
      ok: true,
      sidecarPort: Number(sidecarPort) || 13380,
      absTargetServer: absServer,
      webPort: PORT,
    });
  });

  // Health check endpoint
  app.get("/api/health", (req, res) => {
    res.json({ status: "ok" });
  });

  // Vite middleware for development
  if (process.env.NODE_ENV !== "production") {
    const vite = await createViteServer({
      server: { middlewareMode: true },
      appType: "spa",
    });
    app.use(vite.middlewares);
  } else {
    const distPath = path.join(process.cwd(), "dist");
    app.use(express.static(distPath));
    app.get("*", (req, res) => {
      res.sendFile(path.join(distPath, "index.html"));
    });
  }

  app.listen(PORT, "0.0.0.0", () => {
    console.log(`Server running on http://localhost:${PORT}`);
  });
}

startServer();
