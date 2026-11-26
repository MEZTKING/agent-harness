// Light, dark or the computer's choice (Settings > Look), set before the page draws so it never flashes.
"use strict";
(function () {
  let t = null;
  try { t = localStorage.getItem("rt-theme"); } catch { /* storage unavailable */ }
  if (t === "light" || t === "dark") document.documentElement.dataset.theme = t;
})();
