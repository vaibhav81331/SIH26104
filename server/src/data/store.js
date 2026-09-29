// Read-only access to the Python-exported serve bundle (data/serve).
//
// Everything here is loaded once at startup and held in memory: 91 replay
// days x ~360 places is small, and serving from memory keeps every request
// in the low milliseconds with no database to operate.

import fs from "node:fs";
import path from "node:path";
import { config } from "../config.js";

const readJson = (p) => JSON.parse(fs.readFileSync(p, "utf8"));

export class ServeStore {
  constructor(dir = config.paths.serve) {
    this.dir = dir;
    this.reload();
  }

  reload() {
    const need = ["meta.json", "districts.json", "wards.geojson", "cells.geojson", "replay/index.json", "validation.json"];
    const missing = need.filter((f) => !fs.existsSync(path.join(this.dir, f)));
    if (missing.length) {
      throw new Error(
        `serve bundle incomplete in ${this.dir}: missing ${missing.join(", ")}. ` +
          `Build it with:  python -m ushma.export`,
      );
    }
    this.meta = readJson(path.join(this.dir, "meta.json"));
    this.districts = readJson(path.join(this.dir, "districts.json"));
    this.wardsGeo = readJson(path.join(this.dir, "wards.geojson"));
    this.cellsGeo = readJson(path.join(this.dir, "cells.geojson"));
    this.validation = readJson(path.join(this.dir, "validation.json"));
    this.coolingSites = fs.existsSync(path.join(this.dir, "cooling_sites.json"))
      ? readJson(path.join(this.dir, "cooling_sites.json"))
      : [];

    const idx = readJson(path.join(this.dir, "replay", "index.json"));
    this.replayDates = idx.dates;
    this.defaultDate = idx.default;
    this.replay = new Map();
    for (const d of this.replayDates) this.replay.set(d, readJson(path.join(this.dir, "replay", `${d}.json`)));

    this.live = null;
    const livePath = path.join(this.dir, "live", "latest.json");
    if (fs.existsSync(livePath)) this.live = readJson(livePath);

    this.wardIndex = new Map(this.wardsGeo.features.map((f) => [f.properties.id, f]));
    this.districtIndex = new Map(this.districts.map((d) => [String(d.id), d]));
    this.bandNames = this.meta.bands.names;
    this.bandEdges = this.meta.bands.edges;
    return this;
  }

  reloadLive() {
    const p = path.join(this.dir, "live", "latest.json");
    this.live = fs.existsSync(p) ? readJson(p) : null;
    return this.live;
  }

  /** Payload for an as-of date in replay mode, or the live payload. */
  payload(mode, asOf) {
    if (mode === "live" && this.live) return this.live;
    return this.replay.get(asOf) ?? this.replay.get(this.defaultDate);
  }

  levelOf(band) {
    const i = this.bandNames.indexOf(band);
    return i < 0 ? 0 : i;
  }
}
