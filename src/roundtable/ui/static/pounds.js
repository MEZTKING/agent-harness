// Costs also in pounds: "≈ £0.95" beside the dollars. Dollars always come first: the bills are in dollars.
// The rate comes from the PC (GET /api/rates: the European Central Bank's daily rate, or one the owner typed).
import { h, get, post, has, toast } from "./core.js";

let RATE = null, LOADING = null, AT = 0;
const FRESH_MS = 60 * 60 * 1000;

// Ask the PC for the rate (at most once an hour unless forced). Resolves to the rate, or null.
export function loadRate(force = false) {
  if (!force && RATE && Date.now() - AT < FRESH_MS) return Promise.resolve(RATE);
  if (LOADING) return LOADING;
  LOADING = (async () => {
    try { if (await has("/api/rates")) { RATE = await get("/api/rates"); AT = Date.now(); } }
    catch { /* no pounds this time: dollars alone */ }
    LOADING = null;
    return RATE;
  })();
  return LOADING;
}

// The same rounding as money.pounds_text and the phone's Pounds.kt: half up, pennies under £100, whole pounds above.
export function poundsText(usd, perUsd) {
  const u = Number(usd), p = Number(perUsd);
  if (usd === null || usd === undefined || usd === "" || !isFinite(u) || !isFinite(p) || p <= 0 || u < 0) return "";
  const gbp = u * p;
  if (gbp === 0) return "≈ £0.00";
  if (gbp < 0.005) return "≈ under £0.01";
  if (gbp >= 100) return "≈ £" + Math.round(Number(gbp.toPrecision(12))).toLocaleString("en-GB");
  const pence = Math.round(Number((gbp * 100).toPrecision(12)));
  return "≈ £" + (pence / 100).toFixed(2);
}

// "≈ £0.95", or "" while there is no rate or pounds are off. Starts loading the rate the first time.
export function pounds(usd) {
  if (!RATE) { loadRate(); return ""; }
  if (RATE.show !== "usd+gbp" || !RATE.per_usd) return "";
  return poundsText(usd, RATE.per_usd);
}

// The pounds as a small grey tag with the rate in its tooltip, or null. Put it after the dollar amount.
export function poundsTag(usd) {
  const text = pounds(usd);
  return text ? h("span", { class: "muted pounds", title: RATE.words || "A guide: the bills are in dollars" }, " " + text) : null;
}

// Settings → Spending: dollars only, or dollars and pounds; the bank's rate or one typed in.
export async function poundsSettings() {
  if (!(await has("/api/rates"))) return null;
  let r;
  try { r = await loadRate(true); } catch { r = null; }
  if (!r) return null;
  const words = h("p", { class: "muted small" }, r.words || "");
  const show = h("select", { "aria-label": "How costs are shown", title: "Pounds are a guide worked out from the dollars" },
    h("option", { value: "usd+gbp" }, "Dollars, and pounds beside them"), h("option", { value: "usd" }, "Dollars only"));
  show.value = r.show;
  const typed = r.setting !== "auto" && r.setting !== undefined && r.setting !== null;
  const how = h("select", { "aria-label": "Which rate", title: "The European Central Bank's rate is read once a day; nothing about you is sent" },
    h("option", { value: "auto" }, "The bank's rate, checked daily"), h("option", { value: "typed" }, "A rate I type"));
  how.value = typed ? "typed" : "auto";
  const num = h("input", { type: "number", step: "0.0001", min: "0.0001", max: "99", value: typed ? r.setting : (r.per_usd || ""),
    "aria-label": "Pounds for one dollar", title: "How many pounds one dollar is worth, for example 0.79", style: "width: 8em" });
  const numRow = h("label", { class: "small", hidden: !typed }, "£ for each $1 ", num);
  const save = async (body) => {
    try { const out = await post("/api/rates", body); RATE = out; AT = Date.now(); words.textContent = out.words || ""; toast("Saved"); }
    catch (e) { toast(String(e.message || e), true); }
  };
  show.addEventListener("change", () => save({ show: show.value }));
  how.addEventListener("change", () => { numRow.hidden = how.value !== "typed"; if (how.value === "auto") save({ rate: "auto" }); });
  num.addEventListener("change", () => { if (num.value) save({ rate: num.value }); });
  return h("div", { class: "pounds-settings" },
    h("h3", {}, "Pounds"),
    h("p", { class: "small" }, "The bills are in dollars. Pounds show beside them as a guide."),
    h("div", { class: "row" }, show, how, numRow), words);
}
