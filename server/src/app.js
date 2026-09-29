// Express application factory. Kept separate from index.js so tests can build
// an app against a temporary runtime directory without opening a real port.

import fs from "node:fs";
import path from "node:path";
import express from "express";
import compression from "compression";
import { config } from "./config.js";
import { ServeStore } from "./data/store.js";
import { RuntimeDb } from "./data/db.js";
import { AlertEngine } from "./alerts/engine.js";
import { v1 } from "./routes/v1.js";
import { errorHandler, notFound, rateLimit } from "./middleware.js";

export function createApp({ serveDir, runtimeDir, dashboardDir } = {}) {
  const store = new ServeStore(serveDir);
  const db = new RuntimeDb(runtimeDir);
  const engine = new AlertEngine(store, db);

  const app = express();
  app.disable("x-powered-by");
  app.set("trust proxy", "loopback");
  app.use(compression({ filter: (req, res) => !req.path.startsWith("/v1/stream") && compression.filter(req, res) }));
  app.use(express.json({ limit: "256kb" }));
  app.use((req, res, next) => {
    res.set({ "x-content-type-options": "nosniff", "referrer-policy": "same-origin", "x-frame-options": "SAMEORIGIN" });
    next();
  });

  app.use("/v1", rateLimit(), v1(store, db, engine));
  app.use("/v1", notFound);

  // The built dashboard, with SPA fallback for client-side routes.
  const dist = dashboardDir ?? config.paths.dashboard;
  if (fs.existsSync(dist)) {
    // Hashed build assets can be cached; the service worker and the HTML entry
    // point must always revalidate, or clients stay pinned to an old build.
    app.use(express.static(dist, {
      maxAge: "1h",
      index: false,
      setHeaders: (res, file) => {
        if (/(sw\.js|index\.html|manifest\.webmanifest)$/.test(file)) res.setHeader("cache-control", "no-cache");
      },
    }));
    app.get(/^\/(?!v1\/).*/, (req, res) => res.set("cache-control", "no-cache").sendFile(path.join(dist, "index.html")));
  } else {
    app.get("/", (req, res) =>
      res.type("text").send("USHMA API is running. The dashboard is not built yet: cd dashboard && npm install && npm run build"),
    );
  }

  app.use(errorHandler);
  return { app, store, db, engine };
}
