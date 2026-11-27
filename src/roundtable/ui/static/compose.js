// The message box: one box for a new idea, a note to the planner, a question in chat and a letter.
// It keeps a draft (the app's own folder: it survives closing the app), takes pictures and files (Attach,
// paste or drop; big pictures are made smaller here first), @file references from the project, speaking
// instead of typing where this browser can, and – for a project at work – Next task or Now.
// Server side: ui/attachapi.py and attachments.py.
import { BRAND, h, fill, get, post, q, toast } from "./core.js";

const PART = 1_000_000;  // base64 characters a request (the app's servers take 2 MB at most)
const MAX_PX = 1568;     // a longer picture is made smaller before it leaves this window
const MODES = [["queue", "Next task", "The planner and the next task read it. The task working now isn't stopped."],
  ["steer", "Now", "The task working now reads it at its next step, and every task after it."]];

let styled = false;
function style() {  // the box's own look, once (the coordinator may move it into style.css)
  if (styled) return;
  styled = true;
  document.head.append(h("style", { "data-for": "compose" }, `
.compose { display: flex; flex-direction: column; gap: 8px; position: relative; }
.compose textarea { min-height: 84px; }
.compose.drop textarea { outline: 2px dashed var(--color-accent); outline-offset: 2px; }
.compose-files { display: flex; flex-wrap: wrap; gap: 6px; }
.compose-file { display: inline-flex; align-items: center; gap: 6px; padding: 3px 4px 3px 6px; border-radius: var(--radius-small);
  background: var(--color-sunken); border: 1px solid var(--color-oak-line); font-size: 13px; max-width: 260px; }
.compose-file img { width: 32px; height: 32px; object-fit: cover; border-radius: 4px; }
.compose-file .name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.compose-file button { min-height: 24px; padding: 0 7px; border: none; background: transparent; color: var(--color-muted); }
.compose-bar { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; }
.compose-bar .spacer { flex: 1; }
.compose-bar .mic.on { background: var(--color-bad-soft); color: var(--color-bad); }
.compose-at { position: absolute; z-index: 5; left: 0; right: 0; top: 92px; max-height: 220px; overflow: auto; margin: 0; padding: 4px;
  list-style: none; background: var(--color-surface); border: 1px solid var(--color-oak-line); border-radius: var(--radius-small); box-shadow: var(--shadow); }
.compose-at li { padding: 5px 8px; border-radius: 4px; cursor: pointer; font: 13px/1.4 var(--font-mono); }
.compose-at li.on, .compose-at li:hover { background: var(--color-accent-soft); }
.compose-saved { font-size: 12.5px; }
`));
}

// A picture made smaller (and a phone photo's size cut) before it's sent; anything else as it is.
export async function shrinkPicture(file, maxPx = MAX_PX) {
  if (!/^image\/(png|jpeg|webp)$/.test(file.type) || typeof createImageBitmap !== "function") return file;
  try {
    const bmp = await createImageBitmap(file);
    const scale = Math.min(1, maxPx / Math.max(bmp.width, bmp.height));
    if (scale === 1 && file.size < 1_500_000) return file;
    const c = document.createElement("canvas");
    c.width = Math.round(bmp.width * scale); c.height = Math.round(bmp.height * scale);
    c.getContext("2d").drawImage(bmp, 0, 0, c.width, c.height);
    const png = file.type === "image/png" && file.size < 1_500_000;
    const blob = await new Promise((res) => c.toBlob(res, png ? "image/png" : "image/jpeg", 0.85));
    if (!blob) return file;
    const name = png ? file.name : file.name.replace(/\.(png|webp|jpe?g)$/i, "") + ".jpg";
    return new File([blob], name, { type: blob.type });
  } catch { return file; }
}

const b64 = (buf) => { let s = ""; const a = new Uint8Array(buf); for (let i = 0; i < a.length; i += 0x8000) s += String.fromCharCode(...a.subarray(i, i + 0x8000)); return btoa(s); };

// The @word being typed just before the caret, if any: {start, word}.
export function atWord(text, caret) {
  const m = /(^|[\s(])@([\w./\\-]*)$/.exec(text.slice(0, caret));
  return m ? { start: caret - m[2].length - 1, word: m[2] } : null;
}

const speech = () => window.SpeechRecognition || window.webkitSpeechRecognition || null;

// opts: key (the draft's name, e.g. "new-idea" or "chat:<project>"), project (a project's path: @ lists its files),
// placeholder, label, rows, modes (show Next task / Now), sendLabel, textless (only pictures and files),
// noFiles (words only: drafts and Speak, no Attach, paste or drop – a letter),
// onSend({text, mode, key, items}) -> resolves when sent (the box is then cleared), hint (a line under the box)
export function composer(opts = {}) {
  style();
  const key = opts.key || "message";
  let mode = "queue", items = [], saveTimer = null, listening = null, atList = [], atPick = 0, atAt = null;
  const area = h("textarea", { rows: opts.rows || 4, placeholder: opts.placeholder || "Write here…", "aria-label": opts.label || "Your message",
    hidden: opts.textless || null });
  const files = h("div", { class: "compose-files", "aria-live": "polite" });
  const saved = h("span", { class: "compose-saved muted", title: "What you write is kept, even if you close the app, until you send it." });
  const at = h("ul", { class: "compose-at", role: "listbox", hidden: true, "aria-label": "Files in the project" });
  const input = h("input", { type: "file", multiple: true, hidden: true, onchange: () => { addFiles([...input.files]); input.value = ""; } });
  const attach = opts.noFiles ? null : h("button", { type: "button", class: "small", title: "Add pictures or files. You can also paste a picture or drop files on the box.",
    onclick: () => input.click() }, "Attach");
  const mic = speech() && !opts.textless ? h("button", { type: "button", class: "small mic", "aria-pressed": "false",
    title: "Speak instead of typing. Your words appear in the box; nothing is sent until you press Send. Your computer's speech service turns speech into words.",
    onclick: () => (listening ? stop() : listen()) }, "Speak") : null;
  const modeRow = opts.modes ? h("span", { class: "seg", role: "group", "aria-label": "When it arrives" }) : null;
  const send = opts.onSend ? h("button", { type: "button", class: "primary", onclick: () => doSend() }, opts.sendLabel || "Send") : null;
  const root = h("div", { class: "compose" }, area, at, files,
    h("div", { class: "compose-bar" }, attach, mic, modeRow, h("span", { class: "spacer" }), saved, send), input,
    opts.hint ? h("p", { class: "muted small" }, opts.hint) : null);

  function drawModes() {
    if (!modeRow) return;
    fill(modeRow, MODES.map(([id, label, tip]) => h("button", { type: "button", class: id === mode ? "on" : "", title: tip, "aria-pressed": String(id === mode),
      onclick: () => { mode = id; drawModes(); saveSoon(); } }, label)));
  }
  function drawFiles() {
    fill(files, items.map((x) => h("span", { class: "compose-file", title: `${x.name}, ${x.size_words}` },
      x.preview ? h("img", { src: x.preview, alt: "" }) : null,
      h("span", { class: "name" }, x.name), h("span", { class: "muted" }, x.size_words),
      h("button", { type: "button", title: `Take ${x.name} off`, "aria-label": `Remove ${x.name}`, onclick: () => remove(x.id) }, "✕"))));
  }
  function show(d) {
    items = d.items || [];
    drawFiles();
  }

  // -- the draft --
  function saveSoon() {
    clearTimeout(saveTimer);
    saved.textContent = "";
    saveTimer = setTimeout(async () => {
      try { await post("/api/attach/draft", { key, text: area.value, mode }); saved.textContent = area.value.trim() ? "Draft kept" : ""; }
      catch { saved.textContent = "Not saved yet"; }
    }, 600);
  }
  (async () => {
    try {
      const d = await get("/api/attach/draft?" + q({ key }));
      if (d.text && !area.value) area.value = d.text;
      mode = d.mode || "queue";
      show(d);
      if (d.text) saved.textContent = "Draft kept";
    } catch { /* an older app: no drafts */ }
    drawModes();
  })();

  // -- files --
  async function addOne(file) {
    const small = await shrinkPicture(file);
    const data = b64(await small.arrayBuffer());
    let r = {};
    for (let i = 0; i < data.length || i === 0; i += PART) {
      const last = i + PART >= data.length;
      r = await post("/api/attach/upload", { key, name: small.name || "picture.png", data: data.slice(i, i + PART), upload_id: r.upload_id, last });
    }
    return r.draft;
  }
  async function addFiles(list) {
    if (!attach) return;  // words only
    attach.disabled = true;
    try { for (const f of list) { const d = await addOne(f); if (d) show(d); } }
    catch (e) { toast(e.message, true); }
    finally { attach.disabled = false; }
  }
  async function remove(id) {
    try { show(await post("/api/attach/remove", { key, id })); } catch (e) { toast(e.message, true); }
  }
  area.addEventListener("paste", (ev) => {
    if (!attach) return;
    const pics = [...(ev.clipboardData ? ev.clipboardData.files : [])];
    if (pics.length) { ev.preventDefault(); addFiles(pics); }
  });
  root.addEventListener("dragover", (ev) => { if (!attach) return; ev.preventDefault(); root.classList.add("drop"); });
  root.addEventListener("dragleave", () => root.classList.remove("drop"));
  root.addEventListener("drop", (ev) => { if (!attach) return; ev.preventDefault(); root.classList.remove("drop"); addFiles([...ev.dataTransfer.files]); });

  // -- @file --
  async function lookAt() {
    atAt = opts.project ? atWord(area.value, area.selectionStart) : null;
    if (!atAt) { at.hidden = true; return; }
    try { atList = (await get("/api/attach/files?" + q({ project: opts.project, q: atAt.word }))).files || []; } catch { atList = []; }
    atPick = 0;
    drawAt();
  }
  function drawAt() {
    at.hidden = !atList.length;
    fill(at, atList.map((f, i) => h("li", { role: "option", class: i === atPick ? "on" : "", "aria-selected": String(i === atPick),
      title: "Attach this file as it is when you send", onmousedown: (ev) => { ev.preventDefault(); pickAt(f); } }, f)));
  }
  function pickAt(f) {
    const caret = area.selectionStart;
    area.value = area.value.slice(0, atAt.start) + "@" + f + " " + area.value.slice(caret);
    const pos = atAt.start + f.length + 2;
    area.setSelectionRange(pos, pos);
    at.hidden = true; atList = [];
    saveSoon();
  }
  area.addEventListener("input", () => { saveSoon(); lookAt(); });
  area.addEventListener("keydown", (ev) => {
    if (!at.hidden && atList.length) {
      if (ev.key === "ArrowDown" || ev.key === "ArrowUp") { ev.preventDefault(); atPick = (atPick + (ev.key === "ArrowDown" ? 1 : atList.length - 1)) % atList.length; drawAt(); return; }
      if (ev.key === "Enter" || ev.key === "Tab") { ev.preventDefault(); pickAt(atList[atPick]); return; }
      if (ev.key === "Escape") { at.hidden = true; return; }
    }
    if (ev.key === "Enter" && (ev.ctrlKey || ev.metaKey) && send) { ev.preventDefault(); doSend(); }
  });
  area.addEventListener("blur", () => setTimeout(() => { at.hidden = true; }, 150));

  // -- speaking --
  function listen() {
    const R = speech();
    const rec = new R();
    rec.lang = "en-GB"; rec.continuous = true; rec.interimResults = false;
    rec.onresult = (ev) => {
      for (let i = ev.resultIndex; i < ev.results.length; i++) if (ev.results[i].isFinal) {
        const said = ev.results[i][0].transcript.trim();
        if (said) area.value = (area.value && !/\s$/.test(area.value) ? area.value + " " : area.value) + said;
      }
      saveSoon();
    };
    rec.onerror = (ev) => { if (ev.error === "not-allowed") toast(`The microphone isn't allowed. Allow it for ${BRAND.name}, then try again.`, true); };
    rec.onend = () => { listening = null; mic.classList.remove("on"); mic.textContent = "Speak"; mic.setAttribute("aria-pressed", "false"); };
    try { rec.start(); } catch { return; }
    listening = rec; mic.classList.add("on"); mic.textContent = "Stop"; mic.setAttribute("aria-pressed", "true");
  }
  function stop() { if (listening) listening.stop(); }

  // -- sending --
  async function doSend() {
    if (!opts.onSend) return;
    if (!area.value.trim() && !opts.textless) { toast("Write something first.", true); area.focus(); return; }
    clearTimeout(saveTimer);
    if (send) send.disabled = true;
    try {
      await post("/api/attach/draft", { key, text: area.value, mode });
      await opts.onSend({ text: area.value.trim(), mode, key, items });
      clear();
    } catch (e) { toast(e.message, true); }
    finally { if (send && send.isConnected) send.disabled = false; }
  }
  // Empty the box and its draft (sending through attachapi empties the draft already: no harm).
  function clear() {
    area.value = ""; items = []; drawFiles(); saved.textContent = "";
    post("/api/attach/clear", { key }).catch(() => {});
  }

  root.composer = { key, text: () => area.value, mode: () => mode, items: () => items, clear, focus: () => area.focus(),
    setText: (t) => { area.value = t; saveSoon(); }, saveNow: () => post("/api/attach/draft", { key, text: area.value, mode }) };
  return root;
}
