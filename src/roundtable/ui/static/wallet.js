// Learning's own weekly money (improve/wallet.py, ui/walletapi.py). walletCard() for Settings → Spending and the top
// of Models → Learning. Short first: one line ("Learning: $0.42 of $2 this week"); the week's lines behind More.
// Off shows one sentence and one button that asks the owner for a figure. Nothing shows on an older PC.
import { h, fill, get, post, has, act, dialog, money } from "./core.js";

walletStyles();

const WHAT = { analyst: "Looking for ideas", replay: "Testing on past tasks", yardstick: "Testing on practice tasks",
  probe: "Checking the models work", tool: "Other" };

export function walletCard() {
  const box = h("section", { class: "card wl" },
    h("div", { class: "card-head" }, h("h2", { title: "Money learning may spend by itself each week, apart from your projects" }, "Learning")));
  const body = h("div", {}, h("p", { class: "muted small" }, "Looking…"));
  box.append(body);
  const load = async () => {
    if (!(await has("/api/learning/wallet"))) { box.remove(); return; }
    try { fill(body, ...parts(await get("/api/learning/wallet"), load)); }
    catch (e) { fill(body, h("p", { class: "muted" }, "Couldn't read learning's money. Open this page again to retry.")); }
  };
  load();
  return box;
}

function parts(v, reload) {
  const choose = h("button", { class: v.on ? "btn small" : "btn", title: "Choose how much learning may spend by itself each week" },
    v.on ? "Change" : "Let it learn by itself…");
  choose.addEventListener("click", () => ask(v, choose, reload));
  if (!v.on) return [h("p", {}, "Learning by itself is off."), h("div", { class: "wl-acts" }, choose)];
  const more = h("details", { class: "wl-more" }, h("summary", { title: "This week's spending line by line, and when it runs next" }, "More"));
  const facts = [
    `${money(v.left)} left this week.`,
    v.spent_elsewhere ? `Your other computers spent ${money(v.spent_elsewhere)} of it.` : "",
    v.next_run ? `Next run: ${new Date(v.next_run).toLocaleString("en-GB", { weekday: "long", hour: "2-digit", minute: "2-digit" })}.` : "",
    v.day_limit ? `It counts inside your daily limit (${money(v.day_limit)}).` : "",
  ].filter(Boolean).join(" ");
  const lines = (v.lines || []).slice().reverse().map((l) =>
    h("li", { title: l.proposal ? `For change ${l.proposal}` : "" }, `${WHAT[l.what] || WHAT.tool}: ${money(l.usd)}`));
  more.append(h("p", { class: "muted small" }, facts),
    lines.length ? h("ul", { class: "wl-lines" }, lines) : h("p", { class: "muted small" }, "Nothing spent yet this week."),
    h("div", { class: "wl-acts" }, choose));
  return [h("p", {}, v.words), more];
}

async function ask(v, btn, reload) {
  const field = await dialog({ title: "Learning's weekly money", text: `How much may learning spend by itself each week? Choices: ${(v.choices || [0, 1, 2, 5]).map((c) => (c ? money(c) : "Off (0)")).join(", ")}.`,
    yes: "Next", input: { placeholder: "2", label: "Dollars a week", value: String(v.allowance || 2) } });
  if (field === null || field === false) return;
  const usd = Number(String(field).replace(/[^0-9.]/g, "")) || 0;
  await act(btn, async () => {
    const q = await post("/api/learning/allowance", { usd });
    if (q && q.confirm && !(await dialog({ title: "Are you sure?", text: q.question, yes: usd ? "Yes, allow it" : "Switch it off" }))) return;
    await post("/api/learning/allowance", { usd, confirm: true });
    await reload();
  });
}

function walletStyles() {
  if (typeof document === "undefined" || document.getElementById("wl-style")) return;
  document.head.append(h("style", { id: "wl-style" }, `
.wl-more { margin-top: 6px; border: 1px solid var(--color-line); border-radius: var(--radius-small); background: var(--color-sunken); padding: 4px 10px; }
.wl-more > summary { cursor: pointer; padding: 2px 0; }
.wl-lines { margin: 4px 0; padding-left: 18px; }
.wl-lines li { margin: 2px 0; }
.wl-acts { display: flex; gap: 8px; margin: 8px 0 4px; flex-wrap: wrap; }
`));
}
