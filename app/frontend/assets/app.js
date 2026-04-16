// MailCraft — dark modern minimal SPA.
// No framework; one module, no build step. Renders strictly as text (never as HTML).

const API = {
  meta: "/v1/meta",
  generate: "/v1/generate",
  regenerate: "/v1/regenerate",
};

const el = (id) => document.getElementById(id);
const state = { currentDraft: null, tone: "formal" };

// ── Boot ──────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
  initCharCounter();
  initTonePills();
  initFactsList();
  initForm();
  initRegen();
  initCopy();
  loadMeta();
});

async function loadMeta() {
  try {
    const res = await fetch(API.meta);
    if (!res.ok) return;
    const data = await res.json();
    el("provider-badge").textContent = `provider: ${data.provider}`;
    const modelShort = data.model_primary.split(".").pop().split("-").slice(0, 3).join("-");
    el("model-badge").textContent = `model: ${modelShort}`;
  } catch { /* non-critical */ }
}

// ── Character counter ─────────────────────────
function initCharCounter() {
  const input = el("intent");
  const counter = el("intent-count");
  const update = () => {
    const len = input.value.length;
    counter.textContent = `${len} / 400`;
    counter.classList.toggle("near-limit", len > 350);
    counter.classList.toggle("at-limit", len >= 400);
  };
  input.addEventListener("input", update);
  update();
}

// ── Tone pills ────────────────────────────────
function initTonePills() {
  const container = el("tone-pills");
  const pills = () => [...container.querySelectorAll(".tone-pill")];

  container.addEventListener("click", (e) => {
    const pill = e.target.closest(".tone-pill");
    if (!pill) return;
    selectPill(pill, pills());
  });

  container.addEventListener("keydown", (e) => {
    if (!["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(e.key)) return;
    e.preventDefault();
    const all = pills();
    const current = all.findIndex((p) => p.classList.contains("active"));
    let next;
    if (e.key === "ArrowRight" || e.key === "ArrowDown") {
      next = (current + 1) % all.length;
    } else {
      next = (current - 1 + all.length) % all.length;
    }
    selectPill(all[next], all);
    all[next].focus();
  });
}

function selectPill(pill, allPills) {
  allPills.forEach((p) => {
    p.classList.remove("active");
    p.setAttribute("aria-checked", "false");
    p.setAttribute("tabindex", "-1");
  });
  pill.classList.add("active");
  pill.setAttribute("aria-checked", "true");
  pill.setAttribute("tabindex", "0");
  state.tone = pill.dataset.tone;
  el("tone").value = pill.dataset.tone;
}

// ── Facts list ────────────────────────────────
function initFactsList() {
  el("add-fact").addEventListener("click", () => addFactRow(""));
  addFactRow("");
  addFactRow("");
  addFactRow("");
  renumberFacts();
}

function addFactRow(value) {
  const wrap = document.createElement("div");
  wrap.className = "fact-row";

  const num = document.createElement("span");
  num.className = "fact-num";

  const input = document.createElement("input");
  input.type = "text";
  input.maxLength = 400;
  input.placeholder = "E.g. Proposal due by April 30";
  input.value = value || "";

  const del = document.createElement("button");
  del.type = "button";
  del.setAttribute("aria-label", "Remove this fact");
  del.textContent = "\u00d7";
  del.addEventListener("click", () => {
    const list = el("facts-list");
    if (list.children.length > 1) {
      wrap.remove();
      renumberFacts();
    }
  });

  wrap.appendChild(num);
  wrap.appendChild(input);
  wrap.appendChild(del);
  el("facts-list").appendChild(wrap);
  renumberFacts();
}

function renumberFacts() {
  el("facts-list").querySelectorAll(".fact-num").forEach((n, i) => {
    n.textContent = String(i + 1);
  });
}

function collectFacts() {
  return Array.from(document.querySelectorAll("#facts-list input"))
    .map((i) => i.value.trim())
    .filter(Boolean);
}

// ── Form ──────────────────────────────────────
function initForm() {
  el("compose-form").addEventListener("submit", onGenerate);
}

async function onGenerate(evt) {
  evt.preventDefault();
  const intent = el("intent").value.trim();
  const facts = collectFacts();
  const baseTone = state.tone;
  const modifier = el("tone-modifier").value.trim();
  const tone = modifier ? `${baseTone} — ${modifier}`.slice(0, 40) : baseTone;
  const prompt_version = el("prompt-version").value;

  hideFormError();
  if (intent.length < 3) return showFormError("Intent must be at least 3 characters.");
  if (facts.length === 0) return showFormError("Add at least one key fact.");

  setStatus("Generating your email…", "loading");
  setGenerating(true);
  try {
    const res = await fetch(API.generate, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ intent, key_facts: facts, tone, prompt_version }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data?.error?.message || `Request failed (${res.status})`);
    renderDraft(data);
    setStatus(`Draft ready in ${(data.latency_ms / 1000).toFixed(1)}s`, "ok");
    scrollToResult();
  } catch (err) {
    setStatus(err.message, "err");
  } finally {
    setGenerating(false);
  }
}

function showFormError(msg) {
  const box = el("form-error");
  box.textContent = msg;
  box.hidden = false;
}

function hideFormError() {
  const box = el("form-error");
  box.hidden = true;
  box.textContent = "";
}

// ── Regenerate ────────────────────────────────
function initRegen() {
  const dialog = el("regen-dialog");
  el("regen-btn").addEventListener("click", () => dialog.showModal());
  dialog.addEventListener("close", async () => {
    if (dialog.returnValue !== "confirm") return;
    const instruction = el("regen-instruction").value.trim();
    if (!instruction || !state.currentDraft) return;
    setStatus("Regenerating…", "loading");
    setGenerating(true);
    try {
      const res = await fetch(API.regenerate, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          draft_id: state.currentDraft.draft_id,
          revision_instruction: instruction,
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data?.error?.message || `Request failed (${res.status})`);
      renderDraft(data);
      setStatus(`Revision ready in ${(data.latency_ms / 1000).toFixed(1)}s`, "ok");
    } catch (err) {
      setStatus(err.message, "err");
    } finally {
      setGenerating(false);
      el("regen-instruction").value = "";
    }
  });
}

// ── Copy ──────────────────────────────────────
function initCopy() {
  el("copy-btn").addEventListener("click", async () => {
    if (!state.currentDraft) return;
    const { subject_suggestion, email_body } = state.currentDraft;
    const text = `Subject: ${subject_suggestion}\n\n${email_body}`;
    try {
      await navigator.clipboard.writeText(text);
      const label = el("copy-btn").querySelector(".copy-label");
      const btn = el("copy-btn");
      label.textContent = "Copied!";
      btn.classList.add("copied");
      setTimeout(() => {
        label.textContent = "Copy";
        btn.classList.remove("copied");
      }, 2000);
      setStatus("Copied to clipboard.", "ok");
    } catch {
      setStatus("Unable to access clipboard.", "err");
    }
  });
}

// ── Render ────────────────────────────────────
function renderDraft(data) {
  state.currentDraft = data;
  el("regen-btn").disabled = false;
  el("copy-btn").disabled = false;

  // Show email output
  const emailOut = el("email-output");
  emailOut.hidden = false;
  emailOut.classList.remove("animate-in");
  void emailOut.offsetWidth;
  emailOut.classList.add("animate-in");

  // Show insights, hide empty state
  el("insights-empty").hidden = true;
  const insightsOut = el("insights-content");
  insightsOut.hidden = false;
  insightsOut.classList.remove("animate-in");
  void insightsOut.offsetWidth;
  insightsOut.classList.add("animate-in");

  // textContent only — model output is untrusted.
  el("subject-out").textContent = data.subject_suggestion || "(no subject)";
  el("body-out").textContent = data.email_body || "";

  // Update preview description
  el("preview-desc").textContent = `Draft ${data.draft_id.slice(0, 8)}`;

  // Meta badges
  const meta = el("result-meta");
  meta.replaceChildren(
    badge(`model: ${data.model_id.split(".").pop()}`),
    badge(`prompt: ${data.prompt_version}`),
    badge(`${(data.latency_ms / 1000).toFixed(1)}s`),
    badge(data.draft_id),
  );

  // Coverage bar + list
  const coverage = data.fact_coverage || [];
  const included = coverage.filter((c) => c.included).length;
  const total = coverage.length;
  const pct = total > 0 ? Math.round((included / total) * 100) : 100;
  el("coverage-bar-fill").style.width = `${pct}%`;
  el("coverage-pct").textContent = `${included}/${total} (${pct}%)`;

  const list = el("coverage-list");
  list.replaceChildren();
  coverage.forEach((entry) => {
    const li = document.createElement("li");
    li.classList.add(entry.included ? "included" : "missing");

    const icon = document.createElement("span");
    icon.className = "status-icon";
    icon.textContent = entry.included ? "\u2713" : "\u2717";

    const fact = document.createElement("span");
    fact.className = "fact";
    fact.textContent = entry.fact;

    li.appendChild(icon);
    li.appendChild(fact);
    list.appendChild(li);
  });
}

function badge(text) {
  const s = document.createElement("span");
  s.textContent = text;
  return s;
}

function setStatus(message, kind) {
  const node = el("status");
  node.textContent = message;
  node.className = `status status--${kind}`;
}

function setGenerating(active) {
  const btn = el("generate-btn");
  const text = btn.querySelector(".btn-text");
  const spinner = btn.querySelector(".btn-spinner");
  btn.disabled = active;
  text.textContent = active ? "Generating…" : "Generate email";
  if (active) {
    spinner.removeAttribute("hidden");
  } else {
    spinner.setAttribute("hidden", "");
  }

  el("regen-btn").disabled = active || !state.currentDraft;
  el("copy-btn").disabled = active || !state.currentDraft;
}

function scrollToResult() {
  if (window.innerWidth <= 768) {
    el("email-output").scrollIntoView({ behavior: "smooth", block: "start" });
  }
}
