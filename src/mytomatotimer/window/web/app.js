"use strict";

// pywebview injects window.pywebview.api once the page is ready.
const api = () => window.pywebview.api;
const $ = (id) => document.getElementById(id);

const PALETTE = ["#d9453b", "#e6932e", "#4c9f70", "#3b82c4", "#8e5bc2", "#c2578f", "#6b7a8f"];
let weekChart = null, subjectChart = null;
let subjectRange = "week";

function fmt(seconds) {
  const m = Math.round(seconds / 60);
  return m >= 60 ? `${Math.floor(m / 60)}h ${String(m % 60).padStart(2, "0")}m` : `${m}m`;
}

function say(text, ok = false) {
  const el = $("message");
  el.textContent = text;
  el.className = ok ? "ok" : "";
}

// --- tabs -------------------------------------------------------------------

document.querySelectorAll("nav button").forEach((btn) => {
  btn.onclick = () => {
    document.querySelectorAll("nav button").forEach((b) => b.classList.toggle("active", b === btn));
    document.querySelectorAll("main > section").forEach((s) => (s.hidden = s.id !== btn.dataset.tab));
    say("");
    ({ stats: loadStats, sessions: loadSessions, subjects: loadSubjects, settings: loadSettings })[btn.dataset.tab]();
  };
});

// --- stats ------------------------------------------------------------------

function setProgress(barId, textId, seconds, goal) {
  $(barId).style.width = goal ? `${Math.min(100, (seconds / goal) * 100)}%` : "0";
  $(textId).textContent = goal ? `of ${fmt(goal)} goal` : "no goal set";
}

function heatLevel(seconds, goal) {
  if (!seconds) return 0;
  const ratio = goal ? seconds / goal : 1;
  return ratio >= 1 ? 4 : ratio >= 0.5 ? 3 : ratio >= 0.25 ? 2 : 1;
}

async function loadStats() {
  const s = await api().get_stats(subjectRange);
  $("today").textContent = fmt(s.today_seconds);
  $("week").textContent = fmt(s.week_seconds);
  $("streak").textContent = s.streak_days;
  setProgress("today-bar", "today-goal", s.today_seconds, s.daily_goal_seconds);
  setProgress("week-bar", "week-goal", s.week_seconds, s.weekly_goal_seconds);

  const labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
  const hours = s.week_days.map((d) => +(d.seconds / 3600).toFixed(2));
  weekChart?.destroy();
  weekChart = new Chart($("week-chart"), {
    type: "bar",
    data: { labels, datasets: [{ data: hours, backgroundColor: PALETTE[0], borderRadius: 4 }] },
    options: {
      maintainAspectRatio: false,
      plugins: { legend: { display: false }, tooltip: { callbacks: { label: (c) => fmt(c.raw * 3600) } } },
      scales: { y: { beginAtZero: true, title: { display: true, text: "hours" } } },
    },
  });

  $("heatmap").replaceChildren(...s.heatmap.map((d) => {
    const cell = document.createElement("div");
    if (d.seconds === null) cell.className = "future";
    else {
      cell.className = `l${heatLevel(d.seconds, s.daily_goal_seconds)}`;
      cell.title = `${d.date}: ${fmt(d.seconds)}`;
    }
    return cell;
  }));

  $("no-subjects").hidden = s.subjects.length > 0;
  subjectChart?.destroy();
  subjectChart = new Chart($("subject-chart"), {
    type: "bar",
    data: {
      labels: s.subjects.map((x) => x.name),
      datasets: [{
        data: s.subjects.map((x) => +(x.seconds / 3600).toFixed(2)),
        backgroundColor: s.subjects.map((x, i) => x.color || PALETTE[i % PALETTE.length]),
        borderRadius: 4,
      }],
    },
    options: {
      indexAxis: "y",
      maintainAspectRatio: false,
      plugins: { legend: { display: false }, tooltip: { callbacks: { label: (c) => fmt(c.raw * 3600) } } },
      scales: { x: { beginAtZero: true, title: { display: true, text: "hours" } } },
    },
  });
}

document.querySelectorAll(".seg button").forEach((btn) => {
  btn.onclick = () => {
    subjectRange = btn.dataset.range;
    document.querySelectorAll(".seg button").forEach((b) => b.classList.toggle("active", b === btn));
    loadStats();
  };
});

// --- sessions ---------------------------------------------------------------

let editing = null; // null = adding, else the session being edited

function nowLocal() {
  const d = new Date();
  d.setMinutes(d.getMinutes() - d.getTimezoneOffset());
  return d.toISOString().slice(0, 16);
}

async function fillSubjectSelect(selectedId) {
  const subjects = (await api().get_subjects()).filter((s) => !s.archived || s.id === selectedId);
  $("sf-subject").replaceChildren(
    new Option("No subject", ""),
    ...subjects.map((s) => new Option(s.name, s.id, false, s.id === selectedId)),
  );
}

async function openSessionForm(session) {
  editing = session;
  await fillSubjectSelect(session?.subject_id ?? null);
  const timesEditable = !session || session.source === "manual";
  $("sf-start").value = session?.started_at ?? nowLocal();
  $("sf-end").value = session?.ended_at ?? nowLocal();
  $("sf-start").disabled = $("sf-end").disabled = !timesEditable;
  $("sf-note").value = session?.note ?? "";
  $("session-form").hidden = false;
}

async function loadSessions() {
  $("session-form").hidden = true;
  const sessions = await api().get_sessions();
  $("no-sessions").hidden = sessions.length > 0;
  $("session-table").tBodies[0].replaceChildren(...sessions.map((s) => {
    const tr = document.createElement("tr");
    const day = s.started_at.replace("T", " ");
    const end = s.ended_at ? s.ended_at.slice(11) : "running";
    const cells = [`${day} – ${end}`, fmt(s.focus_seconds), s.subject || "No subject",
                   s.source === "manual" ? "manual" : "timer", s.note];
    tr.append(...cells.map((t) => Object.assign(document.createElement("td"), { textContent: t })));
    const actions = document.createElement("td");
    if (!s.running) {
      const edit = Object.assign(document.createElement("button"), { className: "act", textContent: "Edit" });
      edit.onclick = () => openSessionForm(s);
      const del = Object.assign(document.createElement("button"), { className: "act", textContent: "Delete" });
      del.onclick = () => {
        if (del.dataset.armed) return api().delete_session(s.id).then((r) => (r.ok ? loadSessions() : say(r.error)));
        // No confirm() dialog: ask by changing the button, click again to confirm.
        del.dataset.armed = "1"; del.textContent = "Sure?";
        setTimeout(() => { delete del.dataset.armed; del.textContent = "Delete"; }, 3000);
      };
      actions.append(edit, del);
    }
    tr.append(actions);
    return tr;
  }));
}

$("new-session").onclick = () => openSessionForm(null);
$("sf-cancel").onclick = () => ($("session-form").hidden = true);
$("session-form").onsubmit = async (e) => {
  e.preventDefault();
  const subject = $("sf-subject").value ? +$("sf-subject").value : null;
  const note = $("sf-note").value;
  const r = editing
    ? await api().update_session(editing.id, subject, note,
        editing.source === "manual" ? $("sf-start").value : null,
        editing.source === "manual" ? $("sf-end").value : null)
    : await api().add_session(subject, $("sf-start").value, $("sf-end").value, note);
  if (!r.ok) return say(r.error);
  say("Saved.", true);
  loadSessions();
};

$("export-csv").onclick = async () => {
  const r = await api().export_csv();
  if (r.cancelled) return;
  r.ok ? say(`Exported ${r.count} sessions to ${r.path}`, true) : say(r.error);
};

// --- subjects ---------------------------------------------------------------

async function loadSubjects() {
  const subjects = await api().get_subjects();
  $("subject-list").replaceChildren(...subjects.map((s, i) => {
    const li = document.createElement("li");
    li.className = s.archived ? "archived" : "";

    const color = Object.assign(document.createElement("input"), {
      type: "color", value: s.color || PALETTE[i % PALETTE.length],
    });
    color.onchange = () => api().set_subject_color(s.id, color.value);

    const name = Object.assign(document.createElement("input"), { type: "text", value: s.name });
    name.onchange = async () => {
      const r = await api().rename_subject(s.id, name.value);
      if (r.ok) say("Renamed.", true);
      else { say(r.error); name.value = s.name; }
    };

    const toggle = Object.assign(document.createElement("button"), {
      className: "act", textContent: s.archived ? "Restore" : "Archive",
    });
    toggle.onclick = async () => { await api().set_subject_archived(s.id, !s.archived); loadSubjects(); };

    li.append(color, name, toggle);
    return li;
  }));
}

$("add-subject").onsubmit = async (e) => {
  e.preventDefault();
  const r = await api().add_subject($("new-subject").value);
  if (!r.ok) return say(r.error);
  $("new-subject").value = "";
  say("");
  loadSubjects();
};

// --- settings ---------------------------------------------------------------

// kind: min = minutes, hm = hours + minutes (stored as minutes), num, bool, choice
const FIELDS = [
  { group: "Timer" },
  { key: "focus_minutes", label: "Focus block", kind: "min" },
  { key: "break_minutes", label: "Short break", kind: "min" },
  { key: "long_break_minutes", label: "Long break", kind: "min" },
  { key: "blocks_before_long_break", label: "Blocks before long break", kind: "num" },
  { key: "auto_start_next_block", label: "Auto-start next block", kind: "bool" },
  { key: "idle_timeout_minutes", label: "Idle timeout (auto-start off)", kind: "min" },
  { group: "Display and alerts" },
  { key: "break_display_mode", label: "Break display", kind: "choice",
    choices: [["countdown", "Time remaining"], ["elapsed", "Time elapsed"]] },
  { key: "beep_seconds", label: "Beep seconds (0 = silent)", kind: "num" },
  { key: "beeps_at_focus_end", label: "Beeps at end of focus block", kind: "bool" },
  { group: "Goals" },
  { key: "daily_goal_minutes", label: "Daily goal", kind: "hm" },
  { key: "weekly_goal_minutes", label: "Weekly goal", kind: "hm" },
];

function numberInput(value, min = 0) {
  return Object.assign(document.createElement("input"), { type: "number", min, step: 1, value });
}

async function loadSettings() {
  const cur = await api().get_settings();
  const form = $("settings-form");
  const readers = {}; // key -> () => value to save
  form.replaceChildren();

  for (const f of FIELDS) {
    if (f.group) {
      form.append(Object.assign(document.createElement("div"), { className: "group", textContent: f.group }));
      continue;
    }
    form.append(Object.assign(document.createElement("label"), { textContent: f.label }));
    const cell = document.createElement("div");
    cell.className = "pair";
    if (f.kind === "bool") {
      const box = Object.assign(document.createElement("input"), { type: "checkbox", checked: cur[f.key] === "1" });
      cell.append(box);
      readers[f.key] = () => box.checked;
    } else if (f.kind === "choice") {
      const sel = document.createElement("select");
      for (const [v, text] of f.choices) sel.add(new Option(text, v, false, v === cur[f.key]));
      cell.append(sel);
      readers[f.key] = () => sel.value;
    } else if (f.kind === "hm") {
      const total = +cur[f.key];
      const h = numberInput(Math.floor(total / 60)), m = numberInput(total % 60);
      cell.append(h, "h", m, "min");
      readers[f.key] = () => (+h.value || 0) * 60 + (+m.value || 0);
    } else {
      const input = numberInput(cur[f.key], f.kind === "num" && f.key !== "beep_seconds" ? 1 : f.kind === "min" ? 1 : 0);
      cell.append(input);
      if (f.kind === "min") cell.append("min");
      readers[f.key] = () => input.value;
    }
    form.append(cell);
  }

  const row = document.createElement("div");
  row.className = "save-row";
  row.append(Object.assign(document.createElement("button"), { className: "act", textContent: "Save" }));
  form.append(row);

  form.onsubmit = async (e) => {
    e.preventDefault();
    const values = Object.fromEntries(Object.entries(readers).map(([k, read]) => [k, read()]));
    const r = await api().save_settings(values);
    r.ok ? say("Saved. Applies from the next session.", true) : say(r.error);
  };
}

window.addEventListener("pywebviewready", loadStats);
