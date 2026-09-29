// USHMA server entry point.

import { createApp } from "./app.js";
import { config } from "./config.js";

const { app, store, engine } = createApp();

app.listen(config.port, config.host, () => {
  const active = engine.active();
  console.log(`USHMA  http://${config.host}:${config.port}`);
  console.log(`  mode ${engine.mode}, as-of ${engine.asOf}, replay ${store.replayDates[0]} .. ${store.replayDates.at(-1)}`);
  console.log(`  ${store.wardIndex.size} wards, ${store.districts.length} districts, ${active.length} active alerts`);
  console.log(`  channels: ${config.channels.mode}${config.channels.mode === "simulated" ? " (nothing leaves this machine)" : ""}`);
  if (config.apiKey === "ushma-dev-key") {
    console.warn("  WARNING: using the default development API key. Set USHMA_API_KEY for any shared deployment.");
  }
});
