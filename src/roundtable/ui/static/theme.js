// The look (Settings > Look): Eclipse (the usual one), Pitch (true black) or Ash (light). Set before the page draws so it
// never flashes. Older choices carry over: "dark" becomes Eclipse, "light" becomes Ash.
"use strict";
(function () {
  let t = null;
  try { t = localStorage.getItem("rt-theme"); } catch { /* storage unavailable */ }
  const was = { dark: "eclipse", light: "ash", system: "eclipse" };
  t = was[t] || t;
  document.documentElement.dataset.theme = t === "pitch" || t === "ash" ? t : "eclipse";
})();
