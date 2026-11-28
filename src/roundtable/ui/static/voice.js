// Talk to the planner (POST /api/chat/talk): what you say becomes words with the same speech service Speak
// uses (the browser's own), is shown, and goes as a question – never as an instruction. The answer is read
// aloud with the computer's own voices. When the planner proposes something to do, it is read back and waits:
// a spoken "yes" or a tap; anything that spends or undoes needs the tap (and asks "Are you sure?" as its button
// would). Where this window has no speech service the button isn't shown.
import { BRAND, h, fill, post, toast } from "./core.js";
import { runCommand } from "./slash.js";

const Recogniser = () => (typeof window !== "undefined" && (window.SpeechRecognition || window.webkitSpeechRecognition)) || null;
export const canTalk = () => !!Recogniser();

let styled = false;
function style() {
  if (styled || typeof document === "undefined") return;
  styled = true;
  document.head.append(h("style", { "data-for": "voice" }, `
.vo { display: flex; flex-direction: column; gap: 6px; }
.vo .talk.on { background: var(--color-bad-soft); color: var(--color-bad); }
.vo-heard { font-size: 13px; font-style: italic; color: var(--color-muted); }
.vo-offer { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; padding: 6px 8px; border: 1px solid var(--color-accent);
  border-radius: var(--radius-small); background: var(--color-accent-soft); font-size: 13px; }
.vo-offer .t { flex: 1; min-width: 160px; }
@media (prefers-reduced-motion: no-preference) { .vo .talk.on { animation: vo-pulse 1.4s ease-in-out infinite; } }
@keyframes vo-pulse { 50% { opacity: .6; } }
`));
}

function speak(text) {
  return new Promise((done) => {
    const s = typeof window !== "undefined" ? window.speechSynthesis : null;
    if (!s || !text) { done(); return; }
    s.cancel();
    const u = new SpeechSynthesisUtterance(String(text).slice(0, 1200));
    u.lang = "en-GB";
    const v = s.getVoices().find((x) => /^en-GB/i.test(x.lang)) || s.getVoices().find((x) => /^en/i.test(x.lang));
    if (v) u.voice = v;
    u.onend = u.onerror = () => done();
    s.speak(u);
  });
}

function hear({ onWords, seconds = 0 } = {}) {
  return new Promise((resolve, reject) => {
    const R = Recogniser();
    const rec = new R();
    rec.lang = "en-GB"; rec.continuous = false; rec.interimResults = true;
    let final = "", timer = null;
    rec.onresult = (ev) => {
      let now = "";
      for (let i = 0; i < ev.results.length; i++) { now += ev.results[i][0].transcript; if (ev.results[i].isFinal) final = now; }
      if (onWords) onWords(now);
    };
    rec.onerror = (ev) => { clearTimeout(timer); reject(new Error(ev.error === "not-allowed"
      ? `The microphone isn't allowed. Allow it for ${BRAND.name}, then try again.` : "Nothing was heard. Try again.")); };
    rec.onend = () => { clearTimeout(timer); resolve(final.trim()); };
    if (seconds) timer = setTimeout(() => rec.stop(), seconds * 1000);
    rec.start();
    hear.current = rec;
  });
}

// The Talk button and what goes with it. opts.onDone(): the chat has a new question and answer (load it again).
export function talkButton(path, opts = {}) {
  if (!canTalk()) return null;
  style();
  const heard = h("div", { class: "vo-heard", "aria-live": "polite" });
  const offer = h("div", { class: "vo-offer", hidden: true, role: "group", "aria-label": "What the planner offers to do" });
  const btn = h("button", { type: "button", class: "small talk", "aria-pressed": "false",
    title: "Talk to the planner: say a question and hear the answer. Your computer's speech service turns speech into words, as for Speak; what you say is sent as a question, never as an instruction." },
  "Talk");
  const node = h("div", { class: "vo" }, h("div", { class: "row" }, btn), heard, offer);
  let busy = false;
  const on = (v) => { btn.classList.toggle("on", v); btn.setAttribute("aria-pressed", String(v)); btn.textContent = v ? "Listening…" : "Talk"; };

  async function act(action) {
    offer.hidden = true;
    try { await runCommand(path, action.line, { onReply: (t, b) => { if (!b) { toast(t); speak(t); } } }); }
    catch (e) { toast(e.message, true); speak(e.message); }
    if (opts.onDone) opts.onDone();
  }
  async function propose(action) {
    const line = `Shall I ${action.words.charAt(0).toLowerCase()}${action.words.slice(1)}?`;
    fill(offer, h("span", { class: "t" }, `${line} (${action.line})`),
      h("button", { type: "button", class: "small primary", onclick: () => act(action) }, "Yes, do it"),
      h("button", { type: "button", class: "small", onclick: () => { offer.hidden = true; speak("All right, nothing was done."); } }, "No"));
    offer.hidden = false;
    await speak(action.confirm ? `${line} It spends or changes things, so tap Yes to do it.` : `${line} Say yes, or tap.`);
    if (action.confirm || offer.hidden) return;  // the tap is needed
    try {
      const said = (await hear({ seconds: 6, onWords: (w) => { heard.textContent = w; } })).toLowerCase();
      if (!offer.hidden && /^(yes|yeah|yep|do it|go ahead|please)\b/.test(said)) act(action);
    } catch { /* the buttons stay */ }
  }
  btn.addEventListener("click", async () => {
    if (busy) { if (hear.current) hear.current.stop(); return; }
    busy = true; on(true); offer.hidden = true;
    try {
      const said = await hear({ onWords: (w) => { heard.textContent = w; } });
      on(false);
      if (!said) { heard.textContent = "Nothing was heard. Tap Talk and try again."; return; }
      heard.textContent = `You asked: ${said}`;
      btn.disabled = true;
      const r = await post("/api/chat/talk", { path, text: said });
      if (opts.onDone) opts.onDone();
      await speak(r.reply);
      if (r.action) await propose(r.action);
    } catch (e) { toast(e.message, true); }
    finally { busy = false; on(false); btn.disabled = false; }
  });
  return node;
}
