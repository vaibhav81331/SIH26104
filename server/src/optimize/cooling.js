// Cooling-centre siting: a maximal-covering location problem.
//
// "I can open N cooling centres in this city tomorrow. Where?"
//
// Demand at each ward = forecast excess deaths over the next three days
// (already population- and vulnerability-weighted by the risk model), falling
// back to population x vulnerability when the heat is mild. A centre at a
// candidate site covers every ward whose centroid is within `radiusKm`.
//
// Solved greedily with lazy evaluation: at each step pick the site that adds
// the most uncovered demand. Maximal covering is NP-hard; greedy is within a
// factor (1 - 1/e) ~ 63% of optimal in the worst case and, on instances this
// size, typically within a few percent -- and it returns instantly, which is
// what a decision screen needs.

const R = 6371;
export function haversineKm(a, b) {
  const toRad = (d) => (d * Math.PI) / 180;
  const dLat = toRad(b.lat - a.lat);
  const dLon = toRad(b.lon - a.lon);
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(toRad(a.lat)) * Math.cos(toRad(b.lat)) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(h));
}

/**
 * @param {Array<{id,lat,lon,demand,excess}>} wards demand points
 * @param {Array<{id,lat,lon}>} sites candidate sites
 * @param {number} n number of centres
 * @param {number} radiusKm coverage radius
 */
export function greedyMaxCover(wards, sites, n, radiusKm) {
  const covers = sites.map((s) =>
    wards.reduce((acc, w, i) => (haversineKm(s, w) <= radiusKm ? (acc.push(i), acc) : acc), []),
  );
  const covered = new Uint8Array(wards.length);
  const chosen = [];
  const gain = (j) => covers[j].reduce((s, i) => s + (covered[i] ? 0 : wards[i].demand), 0);

  // Lazy greedy: gains only ever shrink, so a stale upper bound is safe.
  const heap = sites.map((_, j) => ({ j, g: gain(j) })).sort((a, b) => b.g - a.g);
  while (chosen.length < Math.min(n, sites.length) && heap.length) {
    const top = heap.shift();
    const g = gain(top.j);
    if (heap.length && g < heap[0].g) {
      top.g = g;
      let k = heap.findIndex((h) => h.g < g);
      if (k < 0) k = heap.length;
      heap.splice(k, 0, top);
      continue;
    }
    if (g <= 0 && chosen.length) break;
    chosen.push({ site: sites[top.j], gain: g, wards: covers[top.j].filter((i) => !covered[i]).map((i) => wards[i].id) });
    for (const i of covers[top.j]) covered[i] = 1;
  }

  const total = wards.reduce((s, w) => s + w.demand, 0);
  const got = wards.reduce((s, w, i) => s + (covered[i] ? w.demand : 0), 0);
  return {
    chosen,
    coveredWardIds: wards.filter((_, i) => covered[i]).map((w) => w.id),
    coveredDemandShare: total > 0 ? got / total : 0,
    coveredExcess: wards.reduce((s, w, i) => s + (covered[i] ? w.excess : 0), 0),
    totalExcess: wards.reduce((s, w) => s + w.excess, 0),
  };
}
