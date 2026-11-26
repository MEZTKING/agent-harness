// Settings: keys (by maker, with Test), AI services, the recommended setup, the hub, backups, plugins, your phone,
// updates, the look and an Advanced part. And the first-run set-up. Everything is done here: nothing to type
// elsewhere, no file to edit.
import { h, fill, get, post, S, act, card, page, ago, empty, seg, toast, dialog, fileSize, plural, jobName, modelName, every, has } from "./core.js";

const SECTIONS = [["keys", "Keys", "The keys that let Roundtable use each AI maker"], ["services", "AI services", "Which AI services Roundtable can use, and adding more"],
  ["recommended", "Recommended setup", "Who plans, codes and checks, in one click"], ["hub", "Hub", "Where your projects, journal and letters are kept and shared"],
  ["phone", "Your phone", "Use Roundtable from your phone"], ["backups", "Backups", "Copies of your settings and plans"],
  ["plugins", "Plugins", "Extra abilities for Roundtable"], ["updates", "Updates", "The newest Roundtable Hold"], ["look", "Look", "Light or dark"],
  ["advanced", "Advanced", "Folders, set-up and the settings files"]];

export async function viewSettings(section = "keys") {
  if (!SECTIONS.some(([k]) => k === section)) section = "keys";
  const st = S.setup = await get("/api/setup");
  const nav = h("nav", { class: "side-nav", "aria-label": "Settings" }, SECTIONS.map(([k, t, tip]) =>
    h("a", { href: `#/settings/${k}`, class: k === section ? "on" : "", "aria-current": k === section ? "page" : null, title: tip }, t)));
  const views = { keys: keysPart, services: servicesPart, recommended: recommendedPart, hub: hubPart, phone: phonePart, backups: backupsPart,
    plugins: pluginsPart, updates: updatesPart, look: lookPart, advanced: advancedPart };
  const body = await views[section](st);
  return page("Settings", `Roundtable Hold ${st.version}`, h("div", { class: "settings" }, nav, h("div", { class: "settings-body" }, body)));
}

// ---------- keys ----------
async function keysPart(st) {
  let presets = {};
  if (S.ov.harness) { try { presets = (await get("/api/providers")).presets || {}; } catch { presets = {}; } }
  const docsFor = (name) => (Object.values(presets).find((p) => p.api_key_env === name) || {}).docs;
  const result = {};
  const rows = st.keys.map((k) => {
    const input = h("input", { type: "password", class: "grow", autocomplete: "off", disabled: !st.desktop, "aria-label": `${k.label} key`,
      placeholder: k.set ? "Saved. Paste a new key to replace it" : `Paste your ${k.label} key` });
    const out = h("p", { class: "key-result small", "aria-live": "polite" });
    const pill = k.set ? h("span", { class: "pill good" }, "saved") : h("span", { class: "pill" }, "no key yet");
    result[k.name] = out;
    const test = async (btn) => {
      const pid = (k.providers || [])[0];
      if (!pid) { out.textContent = "Nothing uses this key yet, so there's nothing to test."; return; }
      out.textContent = "Testing…"; out.className = "key-result small";
      await act(btn, () => post("/api/providers", { action: "test", id: pid }), null, (r) => {
        out.className = "key-result small " + (r.ok ? "good" : "bad");
        out.textContent = r.ok ? (r.message || "It works.") : (r.missing_key ? "There's no key yet: paste it above and press Save." : `It didn't work: ${r.error || r.message}. Check the key was copied whole, then Save it again.`);
      });
    };
    const docs = docsFor(k.name);
    return h("div", { class: "key-row", id: `key-${k.name}` },
      h("div", { class: "key-name" }, h("b", {}, k.label), pill),
      h("div", { class: "row" }, input,
        st.desktop ? h("button", { class: "primary small", onclick: (ev) => {
          if (!input.value.trim()) return toast("Paste the key first.", true);
          act(ev.currentTarget, () => post("/api/setup/keys", { keys: { [k.name]: input.value.trim() } }), `${k.label} key saved`, async (r) => { S.setup = r; input.value = ""; pill.className = "pill good"; pill.textContent = "saved"; await test(null); });
        } }, "Save") : null,
        h("button", { class: "small", title: "Checks the key works, with a tiny request", onclick: (ev) => test(ev.currentTarget) }, "Test"),
        k.set && st.desktop ? h("button", { class: "small danger", onclick: async (ev) => {
          if (await dialog({ title: `Remove the ${k.label} key?`, text: "Models from this maker stop working until you add a key again.", yes: "Remove", danger: true }))
            act(ev.currentTarget, () => post("/api/setup/keys", { keys: { [k.name]: "" } }), "Key removed", () => location.reload());
        } }, "Remove") : null,
        !k.set && docs ? h("a", { class: "btn small", href: docs, target: "_blank", rel: "noopener", title: "Opens the maker's page where you make a key; copy it and paste it here" }, "Get a key") : null),
      out);
  });
  return [card("Keys", h("p", { class: "muted small" }, "Only the makers you use need a key. ",
    st.desktop ? (st.secure_keys ? "Keys are kept in Windows' own safe store, never in a plain file." : "Keys are kept in a private file in Roundtable's folder.")
      : "This copy reads keys from the computer's own settings; the desktop app can save them here."), rows),
  card("Not sure which keys?", h("p", {}, "A DeepSeek key alone is enough to start: every job falls back to it. For the full recommended setup add Openference and OpenRouter too, and Claude for the coder."),
    h("a", { class: "btn", href: "#/settings/recommended" }, "See the recommended setup"))];
}

// ---------- AI services ----------
async function servicesPart(st) {
  if (!S.ov.harness) return needsSetup();
  const data = await get("/api/providers");
  const out = h("div", { class: "small", "aria-live": "polite" });
  const say = (pid, r) => fill(out, h("p", { class: r.ok ? "good" : "bad" }, r.ok ? (r.message || `${pid}: it works`) : r.missing_key ? "There's no key yet: add it under Keys." : `It didn't work: ${r.error}`));
  const rows = data.providers.map((p) => h("div", { class: "svc-row" },
    h("div", { class: "grow" }, h("b", {}, (p.name || p.id).split(" (")[0]), h("small", { class: "muted" }, p.source === "custom.yaml" ? " · added by you" : " · built in")),
    !p.needs_key ? h("span", { class: "pill" }, "no key needed") : p.key_set ? h("span", { class: "pill good" }, "key saved") : h("a", { class: "pill warn", href: "#/settings/keys", title: "Add its key under Keys" }, "no key yet"),
    h("button", { class: "small", title: "Checks it answers", onclick: (ev) => { fill(out, "Testing…"); act(ev.currentTarget, () => post("/api/providers", { action: "test", id: p.id }), null, (r) => say(p.id, r)); } }, "Test"),
    h("button", { class: "small", title: "Lists the models it has (they can then be chosen in Models)", onclick: (ev) => act(ev.currentTarget, () => post("/api/providers", { action: "models", id: p.id }), null,
      (r) => fill(out, h("details", { open: true }, h("summary", {}, `${plural(r.models.length, "model")} at ${(p.name || p.id).split(" (")[0]}`), h("ul", { class: "plain cols" }, r.models.slice(0, 300).map((m) => h("li", {}, modelName(`${p.id}/${m}`, true))))))) }, "Its models"),
    p.source === "custom.yaml" ? h("button", { class: "small danger", onclick: async (ev) => {
      if (await dialog({ title: `Remove ${p.name || p.id}?`, text: "Jobs that use its models fall back to their backups.", yes: "Remove", danger: true }))
        act(ev.currentTarget, () => post("/api/providers", { action: "remove", id: p.id }), "Removed", () => location.reload());
    } }, "Remove") : null));
  const ids = Object.keys(data.presets);
  const preset = h("select", { "aria-label": "Service" }, ids.map((id) => h("option", { value: id, selected: id === "openrouter" }, data.presets[id].name)));
  const name = h("input", { placeholder: "Its name here (optional)", "aria-label": "Name", title: "A short name of your own, if you add the same service twice" });
  const url = h("input", { class: "grow", placeholder: "Its web address (only for your own service)", "aria-label": "Web address" });
  const key = h("input", { type: "password", class: "grow", autocomplete: "off", placeholder: "Its key", "aria-label": "Key", disabled: !data.desktop });
  const hdr = h("input", { placeholder: "Key header, e.g. api-key", "aria-label": "Key header" });
  const qry = h("input", { class: "grow", placeholder: "Extra settings, e.g. api-version=2025-01-01", "aria-label": "Extra settings" });
  const docs = h("a", { class: "btn small", target: "_blank", rel: "noopener", title: "Opens the service's page where you make a key" }, "Get a key");
  const sync = () => { const p = data.presets[preset.value]; url.value = p.base_url || ""; url.hidden = !p.custom; docs.href = p.docs || "#"; docs.hidden = !p.docs; key.disabled = !data.desktop || (!p.api_key_env && !p.custom); };
  preset.addEventListener("change", sync); sync();
  const add = h("button", { class: "primary", onclick: (ev) => {
    const query = {};
    qry.value.split(/[,&]/).map((x) => x.trim()).filter(Boolean).forEach((kv) => { const [k, ...v] = kv.split("="); query[k.trim()] = v.join("=").trim(); });
    act(ev.currentTarget, () => post("/api/providers", { action: "add", preset: preset.value, id: name.value, base_url: url.value, key: key.value, auth_header: hdr.value, query }),
      (r) => `Added ${data.presets[preset.value].name.split(" (")[0]}`, (r) => { say(r.added.id, r.test); key.value = ""; });
  } }, "Add it");
  return [card("AI services", h("p", { class: "muted small" }, "The services Roundtable can use. Their models can then be chosen for any job in Models."), rows, out),
    card("Add a service", h("p", { class: "muted small" }, "Pick one from the list; it's tested straight away. Anything not listed: choose the custom one (any service that works like OpenAI's)."),
      h("div", { class: "row" }, preset, docs), h("div", { class: "row" }, name, url), h("div", { class: "row" }, key),
      h("details", {}, h("summary", { class: "small" }, "For unusual services (Azure and gateways)"), h("div", { class: "row" }, hdr, qry)),
      h("div", { class: "row" }, add))];
}

// ---------- recommended setup ----------
async function recommendedPart(st) {
  if (!S.ov.harness || !(st.config_exists || {}).harness) return needsSetup();
  const r = await get("/api/setup/recommended");
  const models = (ms) => ms.length ? h("span", { title: ms.length > 1 ? `If it can't answer: ${ms.slice(1).map((m) => modelName(m)).join(", then ")}` : "" },
    modelName(ms[0]), ms.length > 1 ? h("span", { class: "muted small" }, ` + ${plural(ms.length - 1, "backup")}`) : null) : h("span", { class: "muted" }, "nobody");
  return card("Recommended setup", h("p", {}, r.summary),
    h("p", { class: "muted small" }, "Three sets of models, chosen per project: ", r.profiles.map((p, i) => [i ? ", " : "", h("b", { title: p.description }, p.name[0].toUpperCase() + p.name.slice(1)),
      p.name === r.default_profile ? " (used unless a project picks another)" : ""])),
    h("table", { class: "plain-table" }, h("tr", {}, h("th", {}, "Job"), h("th", {}, "Now"), h("th", {}, "With the recommended setup")),
      r.rows.map((x) => h("tr", {}, h("td", {}, jobName(x.role)), h("td", { class: "small" }, models(x.before)), h("td", { class: "small" }, x.same ? h("span", { class: "muted" }, "the same") : models(x.after))))),
    h("div", { class: "row" },
      h("button", { class: r.in_use ? "" : "primary", disabled: r.in_use, title: "Your hub, limits, plugins and keys stay as they are; the old settings are kept so you can go back", onclick: async (ev) => {
        if (await dialog({ title: "Use the recommended setup?", text: "Who does each job changes to the table above. Your old settings are kept as a copy, so you can go back.", yes: "Use it" }))
          act(ev.currentTarget, () => post("/api/setup/recommended", {}), "Done: you're using the recommended setup", () => location.reload());
      } }, r.in_use ? "You're using the recommended setup" : "Use the recommended setup"),
      h("a", { class: "btn", href: "#/models" }, "Choose each job yourself")));
}

// ---------- hub ----------
async function hubPart(st) {
  const mode = st.hub.mode;
  const url = h("input", { class: "grow", placeholder: "Your hub's GitHub address, e.g. https://github.com/you/agent-hub-data", "aria-label": "GitHub address" });
  return card("Your hub", h("p", {}, "The hub keeps your projects' journals and letters, and shares them with your other computers, your phone and every Claude session."),
    h("p", {}, "Now: ", mode === "git" ? h("span", { class: "pill good" }, "Shared through GitHub") : mode === "file" ? h("span", { class: "pill info" }, "On this computer only") : h("span", { class: "pill bad" }, "Not set up"),
      S.ov.agents ? h("span", { class: "muted small" }, ` · ${plural(S.ov.agents.length, "project")}`) : null),
    st.hub.error ? h("p", { class: "bad small" }, "It didn't open: ", st.hub.error) : null,
    st.desktop ? [
      st.git ? [h("p", { class: "muted small" }, "To share it, connect a private GitHub repository: the app copies it here and keeps both in step."),
        h("div", { class: "row" }, url, h("button", { class: "primary", onclick: (ev) => act(ev.currentTarget, () => post("/api/setup/hub", { mode: "github", url: url.value.trim() }), "Connecting…",
          (j) => { if (j && j.id) location.hash = `#/activity/work/${j.id}`; }) }, mode === "git" ? "Connect another" : "Connect"))]
        : h("div", {}, h("p", {}, "Sharing through GitHub needs Git on this computer. Until then everything works on this computer only."),
          h("a", { class: "btn", href: "https://git-scm.com/download/win", target: "_blank", rel: "noopener", title: "Opens Git's download page; install it, then open Roundtable Hold again" }, "Get Git for Windows")),
      mode === "git" ? h("div", { class: "row" }, h("button", { onclick: async (ev) => {
        if (await dialog({ title: "Keep the hub on this computer only?", text: "It stops sharing with your other computers and your phone. Nothing is deleted.", yes: "This computer only" }))
          act(ev.currentTarget, () => post("/api/setup/hub", { mode: "local" }), "The hub is on this computer only now", () => location.reload());
      } }, "Use this computer only")) : null,
      mode === "none" ? h("button", { onclick: (ev) => act(ev.currentTarget, () => post("/api/setup/hub", { mode: "local" }), "Hub made on this computer", () => location.reload()) }, "Start a hub on this computer") : null]
      : h("p", { class: "muted small" }, "This copy was started with its own hub settings."));
}

// ---------- your phone ----------
async function phonePart() {
  let st;
  try { st = await get("/api/phone"); } catch (e) { return card("Your phone", h("p", {}, e.message)); }
  const box = h("div");
  const call = async (btn, body, ok) => act(btn, () => post("/api/phone", body), ok, (r) => draw(r));
  function draw(s) {
    const pairing = s.pairing ? h("div", { class: "pairing" },
      h("img", { src: s.pairing.qr, alt: "The pairing code as a square picture", width: 220, height: 220 }),
      h("div", { class: "stack" }, h("p", {}, "In Roundtable Mobile tap ", h("b", {}, "Pair with a PC"), " and point the camera at this square."),
        h("p", {}, "Or type this code: ", h("b", { class: "code" }, s.pairing.code)),
        h("p", { class: "muted small" }, `It works once, for ${Math.max(1, Math.ceil(s.pairing.expires_in / 60))} more minute${s.pairing.expires_in > 60 ? "s" : ""}.`))) : null;
    fill(box,
      h("p", {}, "Now: ", s.running ? h("span", { class: "pill good" }, "On") : s.enabled ? h("span", { class: "pill bad", title: s.error || "" }, "On, but not working") : h("span", { class: "pill" }, "Off")),
      s.error ? h("p", { class: "bad small" }, s.error, " Turn it off and on again; if it still fails, restart the app.") : null,
      h("p", { class: "muted small" }, "A paired phone sees every project, answers what waits, approves, tries again, talks to the planner and reads and sends letters. Keys, settings and updates stay on this computer. The connection is private; away from home it works through Tailscale."),
      h("div", { class: "row" },
        s.running ? h("button", { class: "primary", onclick: (ev) => call(ev.currentTarget, { action: "pair" }) }, "Pair a phone")
          : h("button", { class: "primary", onclick: (ev) => call(ev.currentTarget, { action: "enable" }, "Your phone can connect now") }, "Let my phone connect"),
        s.enabled ? h("button", { onclick: async (ev) => { if (await dialog({ title: "Stop phone access?", text: "Paired phones stay paired and connect again when you turn it back on.", yes: "Turn off" })) call(ev.currentTarget, { action: "disable" }, "Phone access is off"); } }, "Turn off") : null),
      pairing,
      h("h3", {}, "Paired phones"),
      s.devices.length ? h("ul", { class: "plain devices" }, s.devices.map((d) => h("li", {}, h("b", {}, d.name), h("span", { class: "muted small" }, ` · paired ${ago(d.paired_at)} · last seen ${ago(d.last_seen) || "not yet"}`),
        h("button", { class: "small danger", onclick: async (ev) => { if (await dialog({ title: `Remove ${d.name}?`, text: "It will need to pair again.", yes: "Remove", danger: true })) call(ev.currentTarget, { action: "revoke", device_id: d.id }, "Phone removed"); } }, "Remove"))))
        : h("p", { class: "muted small" }, "None yet."));
  }
  draw(st);
  every(box, async () => { if (st.pairing || box.querySelector(".pairing")) { st = await get("/api/phone"); draw(st); } }, 4000);
  const machines = (await has("/api/machines")) ? (await import("./machines.js")).machinesStrip() : null;
  return [card("Your phone", box), machines ? card("Your computers", machines) : null];
}

// ---------- backups ----------
async function backupsPart() {
  let st;
  try { st = await get("/api/backup"); } catch (e) { return card("Backups", h("p", {}, e.message)); }
  const box = h("div", { class: "stack" });
  const save = (btn, body, ok) => act(btn, () => post("/api/backup", { action: "settings", ...body }), ok, (r) => draw(r));
  function draw(s) {
    const set = s.settings;
    const folder = h("input", { class: "grow", value: set.to === "auto" ? "" : set.to, placeholder: "A folder, e.g. your OneDrive folder or a USB stick", "aria-label": "Backup folder",
      title: "Leave empty to use Google Drive. Any folder works: OneDrive, a USB stick, another disk." });
    const phrase = h("input", { type: "password", class: "grow", autocomplete: "off", "aria-label": "Passphrase",
      placeholder: s.passphrase_remembered ? "Remembered until you close the app" : "Passphrase (optional, recommended)",
      title: "Locks the backup so only someone with the passphrase can open it. It's never saved: if you forget it, the backup can't be opened." });
    const remember = h("input", { type: "checkbox", checked: s.passphrase_remembered, onchange: async (ev) => {
      if (ev.target.checked && !phrase.value) { ev.target.checked = false; return toast("Type the passphrase first.", true); }
      act(null, () => post("/api/backup", { action: "passphrase", passphrase: phrase.value, remember: ev.target.checked }), ev.target.checked ? "Remembered until you close the app" : "Forgotten", (r) => draw(r));
    } });
    const pick = h("select", { class: "grow", "aria-label": "Which backup" }, s.backups.map((b) => h("option", { value: b.path }, `${new Date(b.at).toLocaleString()} · ${fileSize(b.size)}${b.locked ? " · locked" : ""}${b.this_pc ? "" : " · another computer"}`)));
    const last = s.last.last_at ? `${ago(s.last.last_at)}${s.last.last_size ? ` · ${fileSize(s.last.last_size)}` : ""}` : "None yet";
    const noDrive = String(s.no_drive || "").replace(/\s*\(https?:[^)]*\)/, "");
    fill(box,
      card("Backups", h("p", { class: "muted small" }, "A backup holds your settings, what Roundtable has learned, and every project's plan and history. It never holds your keys."),
        s.destination ? h("p", {}, "They go to: ", h("b", { title: s.destination }, s.destination.split(/[\\/]/).slice(-2).join(" › ")))
          : h("p", { class: "warn" }, noDrive, " ", h("a", { href: "https://www.google.com/drive/download/", target: "_blank", rel: "noopener" }, "Get Google Drive")),
        h("div", { class: "row" }, folder, h("button", { class: "small", onclick: (ev) => save(ev.currentTarget, { to: folder.value.trim() || "auto" }, "Saved") }, "Use this folder"),
          set.to !== "auto" ? h("button", { class: "small", onclick: (ev) => save(ev.currentTarget, { to: "auto" }, "Backups go to Google Drive") }, "Use Google Drive") : null),
        h("p", {}, "Last backup: ", last, s.last.last_error ? h("span", { class: "pill warn" }, "it had a problem") : null),
        s.last.last_error ? h("p", { class: "bad small" }, String(s.last.last_error).replace(/https?:\/\/\S+/g, "").trim()) : null,
        h("div", { class: "row wrap" },
          h("label", { class: "check", title: "Once a day while Roundtable Hold is open, never while a project is being built" },
            h("input", { type: "checkbox", checked: set.daily, onchange: (ev) => save(null, { daily: ev.target.checked }, ev.target.checked ? "Daily backups on" : "Daily backups off") }), "Back up every day"),
          h("label", { class: "check", title: "Older backups from this computer are deleted; nothing else in the folder is touched" }, "Keep the newest ",
            h("input", { type: "number", min: 1, max: 100, value: set.keep, class: "narrow", "aria-label": "How many to keep", onchange: (ev) => save(null, { keep: Number(ev.target.value) }, "Saved") })),
          h("label", { class: "check", title: "Recommended: a backup holds your plans. The daily backup needs the passphrase typed once each time the app opens." },
            h("input", { type: "checkbox", checked: set.encrypt, onchange: (ev) => save(null, { encrypt: ev.target.checked }, "Saved") }), "Lock with a passphrase")),
        h("div", { class: "row" }, phrase, h("label", { class: "check small", title: "Kept in memory only, until you close the app, so the daily backup can be locked" }, remember, "Remember until I close the app")),
        h("div", { class: "row" }, h("button", { class: "primary", onclick: (ev) => {
          if (set.encrypt && !phrase.value && !s.passphrase_remembered) return toast("Type the passphrase first: backups are set to be locked.", true);
          act(ev.currentTarget, () => post("/api/backup", { action: "now", passphrase: phrase.value, remember: remember.checked }), "Backing up…", (j) => { if (j && j.id) location.hash = `#/activity/work/${j.id}`; });
        } }, "Back up now"))),
      card("Put a backup back", h("p", { class: "muted small" }, "Brings back a backup's settings, plans and history. A copy of what's here now is made first. Projects whose folders are gone are made again."),
        s.backups.length ? h("div", { class: "row" }, pick, h("button", { class: "danger", title: "Shows what it would replace and asks first", onclick: async (ev) => {
          const file = pick.value;
          try {
            const info = await post("/api/backup", { action: "inspect", file, passphrase: phrase.value });
            if (!(await dialog({ title: "Put this backup back?", text: info.lines.join("\n") + "\n\nAfterwards, add your keys again and pair your phone again.", yes: "Put it back", danger: true, wide: true }))) return;
            act(ev.currentTarget, () => post("/api/backup", { action: "restore", file, passphrase: phrase.value, confirm: true }), "Putting it back…", (j) => { location.hash = `#/activity/work/${j.id}`; });
          } catch (e) { toast(e.message, true); }
        } }, "Put it back…")) : h("p", { class: "muted" }, "No backups in that folder yet.")));
  }
  draw(st);
  return box;
}

// ---------- plugins ----------
async function pluginsPart() {
  let st;
  try { st = await get("/api/plugins"); } catch (e) { return card("Plugins", h("p", {}, e.message)); }
  const trust = "A plugin is someone's program: it can do anything Roundtable Hold can. Only add plugins from people you trust.";
  const send = async (btn, body, ok) => {
    try {
      if (btn) btn.disabled = true;
      const r = await post("/api/plugins", body);
      if (r && r.needs_ok) {
        const perms = (r.needs_ok.permissions || []).map((p) => `• ${p.words}`).join("\n");
        if (!(await dialog({ title: `Add ${r.needs_ok.name || "this plugin"}?`, text: `It asks to:\n${perms || "• nothing special"}\n\n${trust}`, yes: "Add it" }))) return;
        return send(btn, { ...body, confirmed: (r.needs_ok.permissions || []).map((p) => p.id) }, ok);
      }
      if (ok) toast(ok);
      location.reload();
    } catch (e) { toast(e.message, true); } finally { if (btn && btn.isConnected) btn.disabled = false; }
  };
  const rows = st.plugins.map((p) => {
    const fields = (p.settings || []).map((f) => {
      const input = f.type === "boolean" ? h("input", { type: "checkbox", checked: !!f.value }) : h("input", { class: "grow", value: f.value ?? "", placeholder: String(f.default ?? "") });
      input.dataset.key = f.key;
      return h("label", { class: "field", title: f.description }, h("span", { class: "label" }, f.description || f.key), input);
    });
    return h("article", { class: "plugin" },
      h("div", { class: "row" }, h("b", { class: "grow" }, p.name || p.id, h("span", { class: "muted small" }, p.builtin ? " · comes with Roundtable" : "")),
        h("label", { class: "switch", title: p.enabled ? "Switch it off" : "Switch it on" }, h("input", { type: "checkbox", checked: p.enabled, onchange: (ev) => send(null, { action: ev.target.checked ? "enable" : "disable", id: p.id }, ev.target.checked ? "Switched on" : "Switched off") }), p.enabled ? "On" : "Off")),
      h("p", { class: "small" }, p.description || ""),
      p.problem ? h("p", { class: "warn small" }, p.problem) : null,
      (p.permissions || []).length ? h("p", { class: "muted small", title: trust }, "It may: " + p.permissions.map((x) => x.words).join("; ")) : null,
      fields.length ? h("details", {}, h("summary", { class: "small" }, "Its settings"), fields, h("button", { class: "small", onclick: (ev) => {
        const values = {};
        fields.forEach((l) => { const el = l.querySelector("input"); values[el.dataset.key] = el.type === "checkbox" ? el.checked : el.value; });
        send(ev.currentTarget, { action: "settings", id: p.id, values }, "Saved");
      } }, "Save its settings")) : null,
      p.builtin ? null : h("button", { class: "small danger", onclick: async (ev) => { if (await dialog({ title: `Remove ${p.name || p.id}?`, yes: "Remove", danger: true })) send(ev.currentTarget, { action: "remove", id: p.id }, "Removed"); } }, "Remove"));
  });
  const source = h("input", { class: "grow", placeholder: "Where it comes from: a folder, a GitHub link or a package name", "aria-label": "Where the plugin comes from", title: "You'll see what it may do before anything is added." });
  return card("Plugins", h("p", { class: "muted small" }, "Extra abilities for Roundtable, like the token saver. ", h("span", { title: trust }, "Only add plugins from people you trust.")),
    rows.length ? rows : h("p", { class: "muted" }, "None yet."),
    h("div", { class: "row" }, source, h("button", { onclick: (ev) => source.value.trim() ? send(ev.currentTarget, { action: "add", source: source.value.trim() }, "Plugin added") : toast("Say where the plugin comes from first.", true) }, "Add a plugin")));
}

// ---------- updates ----------
async function updatesPart(st) {
  const box = h("div", {}, h("p", { class: "muted" }, "Checking…"));
  (async () => {
    let u;
    try { u = await get("/api/update"); } catch (e) { u = { error: e.message }; }
    const kind = (u.install || {}).kind;
    const words = u.error && !u.available ? "Couldn't check for updates just now (no internet?). Try again later."
      : u.available ? (kind === "app" && u.latest ? `Roundtable Hold ${u.latest} is ready (you have ${st.version}).` : "A newer Roundtable Hold is ready.")
        : kind === "other" ? "This copy can't update itself. Install the newest Roundtable Hold from its releases page." : `You have the newest Roundtable Hold (${st.version}).`;
    fill(box, h("p", {}, words),
      (u.changes || []).length && kind === "app" ? h("details", {}, h("summary", {}, "What's new"), h("ul", {}, u.changes.slice(0, 20).map((c) => h("li", {}, c.replace(/^[-*]\s*/, ""))))) : null,
      h("div", { class: "row" },
        h("button", { class: u.available ? "primary" : "", disabled: !u.available, title: "Backs up your settings first, then updates", onclick: (ev) => act(ev.currentTarget, () => post("/api/update", {}), "Updating…",
          (j) => { if (j && j.id) location.hash = `#/activity/work/${j.id}`; }) }, u.available ? "Update now" : "Up to date"),
        h("button", { onclick: () => updatesPart(st).then((n) => box.replaceWith(n)) }, "Check again")));
  })();
  return card("Updates", box);
}

// ---------- look ----------
function lookPart() {
  let now = "system";
  try { now = localStorage.getItem("rt-theme") || "system"; } catch { /* storage unavailable */ }
  const pick = (v) => {
    try { if (v === "system") localStorage.removeItem("rt-theme"); else localStorage.setItem("rt-theme", v); } catch { /* storage unavailable */ }
    if (v === "system") delete document.documentElement.dataset.theme; else document.documentElement.dataset.theme = v;
  };
  return card("Look", h("p", { class: "muted small" }, "How Roundtable looks on this computer."),
    seg([["light", "Light", "Warm parchment and oak"], ["dark", "Dark", "The hall by candlelight"], ["system", "Same as this computer", "Follows the computer's light or dark setting"]], now, pick, "Light or dark"));
}

// ---------- advanced ----------
async function advancedPart(st) {
  const parts = [];
  parts.push(card("Folders", h("p", {}, "New projects are made in: ", h("b", { title: st.projects_dir }, st.projects_dir.split(/[\\/]/).slice(-2).join(" › "))),
    st.desktop ? h("div", { class: "row" }, h("a", { class: "btn", href: "#/setup" }, "Run the set-up again")) : null));
  const editor = async (which, label, about) => {
    if (!(st.config_exists || {})[which]) return h("details", { class: "fold" }, h("summary", {}, label, h("span", { class: "muted small" }, " · not set up yet")),
      h("p", { class: "muted small" }, which === "hub" ? "There's no hub yet: set it up under Hub." : "Run the set-up again to make it."));
    const box = h("div");
    const d = h("details", { class: "fold", ontoggle: async () => {
      if (!d.open || box.firstChild) return;
      try {
        const c = await get(`/api/config?which=${which}`);
        const ta = h("textarea", { class: "code", rows: 24, spellcheck: "false", "aria-label": label }, c.text);
        fill(box, h("p", { class: "muted small" }, about), ta, h("div", { class: "row" },
          h("button", { class: "primary", onclick: (ev) => act(ev.currentTarget, () => post("/api/config", { which, text: ta.value }), "Saved: the old one is kept as a copy") }, "Save"),
          h("span", { class: "muted small" }, "It's checked before it's saved, and the old one is kept.")));
      } catch (e) { fill(box, h("p", {}, e.message)); }
    } }, h("summary", {}, label), box);
    return d;
  };
  parts.push(card("Settings files", h("p", { class: "muted small" }, "Everything here can be changed on the other pages. These are the files behind them, for when you're asked to look."),
    await editor("harness", "Roundtable's settings", "AI services, who does each job, prices and limits."),
    await editor("hub", "The hub's settings", "The projects in the hub, and who may read or write to whom.")));
  return parts;
}

function needsSetup() {
  return card("Roundtable can't build on this computer yet", h("p", {}, "Its settings are missing or have a problem. Run the set-up to make them."),
    S.setup && S.setup.desktop ? h("a", { class: "btn primary", href: "#/setup" }, "Run the set-up") : null);
}

// ---------- first run ----------
export async function viewSetup() {
  const st = S.setup = await get("/api/setup");
  const folder = h("input", { class: "grow", value: st.projects_dir, "aria-label": "Projects folder", title: "Where new projects are made" });
  const me = st.agents.length > 1 ? h("select", { "aria-label": "You are" }, st.agents.map((a) => h("option", { value: a, selected: a === (st.agent || st.agents[0]) }, (S.ov.agents || []).find((x) => x.id === a)?.name || a))) : null;
  return page("Welcome to Roundtable Hold", "Three quick steps: your keys, your hub, and where projects go. You can change all of it later in Settings.",
    h("h2", { class: "step" }, "1. Your keys"), ...(await keysPart(st)).slice(0, 1),
    h("h2", { class: "step" }, "2. Your hub"), await hubPart(st),
    h("h2", { class: "step" }, "3. Where projects go"),
    card(null, h("label", { class: "field" }, h("span", { class: "label" }, "Projects folder"), folder),
      me ? h("label", { class: "field", title: "Your own name in the hub: your notes and letters" }, h("span", { class: "label" }, "You are"), me) : null,
      h("div", { class: "row" },
        h("button", { class: "primary", onclick: (ev) => act(ev.currentTarget, () => post("/api/setup/done", { projects_dir: folder.value, agent: me ? me.value : null }), "All set", () => { location.hash = "#/"; location.reload(); }) }, "Start using Roundtable Hold"),
        h("button", { title: "A short check that each model answers (a few cents)", onclick: (ev) => act(ev.currentTarget, () => post("/api/probes", {}), "Checking your models…", (j) => { if (j && j.id) location.hash = `#/activity/work/${j.id}`; }) }, "Check my models first"))));
}
