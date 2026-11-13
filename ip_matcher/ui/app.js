import { I18N } from "./i18n.js";

let appState = null;
let currentLang = "fa";
let activePanel = "dashboard";
let countriesLoaded = false;

const $ = (sel) => document.querySelector(sel);
const t = (key) => (I18N[currentLang] && I18N[currentLang][key]) || I18N.fa[key] || key;

function toLocalizedDigits(val) {
  const s = String(val ?? "");
  if (currentLang !== "fa") return s;
  return s.replace(/\d/g, (d) => "۰۱۲۳۴۵۶۷۸۹"[Number(d)]);
}

async function api(path, method = "GET", body = null) {
  const opts = { method, headers: {} };
  if (body !== null) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(path, opts);
  const text = await res.text();
  try {
    return JSON.parse(text);
  } catch {
    return { ok: res.ok, raw: text };
  }
}

function showToast(message, variant = "ok") {
  const region = $("#toast-region");
  const toast = document.createElement("div");
  toast.className = `toast-item toast-${variant}`;
  toast.setAttribute("popover", "manual");

  const span = document.createElement("span");
  span.textContent = message;

  const closeBtn = document.createElement("button");
  closeBtn.type = "button";
  closeBtn.className = "btn btn-ghost btn-sm";
  closeBtn.textContent = "✕";
  closeBtn.setAttribute("aria-label", currentLang === "fa" ? "بستن پیام" : "Close");
  closeBtn.addEventListener("click", () => {
    try {
      toast.hidePopover?.();
    } catch {}
    toast.remove();
  });

  toast.append(span, closeBtn);
  region.append(toast);

  if (typeof toast.showPopover === "function") {
    try {
      toast.showPopover();
    } catch {
      toast.classList.add(":popover-open");
    }
  } else {
    toast.classList.add(":popover-open");
  }

  setTimeout(() => {
    try {
      toast.hidePopover?.();
    } catch {}
    toast.remove();
  }, 4200);
}

function applyTheme(theme) {
  const meta = document.querySelector('meta[name="color-scheme"]');
  if (theme === "dark" || theme === "light") {
    meta.content = theme;
    try {
      localStorage.setItem("color-scheme", theme);
    } catch {}
  } else {
    meta.content = "light dark";
    try {
      localStorage.removeItem("color-scheme");
    } catch {}
  }
}

function applyLanguage(lang) {
  currentLang = lang === "en" ? "en" : "fa";
  document.documentElement.lang = currentLang;
  document.documentElement.dir = currentLang === "fa" ? "rtl" : "ltr";

  document.querySelectorAll("[data-i18n]").forEach((el) => {
    const key = el.getAttribute("data-i18n");
    if (key) el.textContent = t(key);
  });

  const activeTabBtn = document.querySelector(`.nav-btn[data-panel="${activePanel}"]`);
  if (activeTabBtn) {
    const labelEl = activeTabBtn.querySelector("[data-i18n]");
    if (labelEl) $("#page-heading").textContent = labelEl.textContent;
  }

  if (appState) renderAll(appState);
}

function switchTab(panelName) {
  activePanel = panelName;
  const tabs = Array.from(document.querySelectorAll('.nav-btn[role="tab"]'));
  tabs.forEach((btn) => {
    const isSel = btn.dataset.panel === panelName;
    btn.setAttribute("aria-selected", String(isSel));
    btn.tabIndex = isSel ? 0 : -1;
    if (isSel) {
      const span = btn.querySelector("[data-i18n]");
      if (span) $("#page-heading").textContent = span.textContent;
    }
  });

  document.querySelectorAll('.tab-panel[role="tabpanel"]').forEach((panel) => {
    const active = panel.id === `panel-${panelName}`;
    panel.hidden = !active;
    panel.classList.toggle("active", active);
  });

  if (panelName === "profiles" && !countriesLoaded) {
    loadCountries();
  }
}

function setupTabsKeyboard() {
  const tablist = document.querySelector('.nav-list[role="tablist"]');
  const tabs = Array.from(tablist.querySelectorAll('[role="tab"]'));
  tabs.forEach((tab) => {
    tab.addEventListener("click", () => switchTab(tab.dataset.panel));
    tab.addEventListener("keydown", (e) => {
      const idx = tabs.indexOf(tab);
      let next = -1;
      if (e.key === "ArrowDown" || e.key === "ArrowRight") next = (idx + 1) % tabs.length;
      if (e.key === "ArrowUp" || e.key === "ArrowLeft") next = (idx - 1 + tabs.length) % tabs.length;
      if (next >= 0) {
        e.preventDefault();
        tabs[next].focus();
        switchTab(tabs[next].dataset.panel);
      }
    });
  });
}

function makeBdi(text, extraClass = "") {
  const bdi = document.createElement("bdi");
  bdi.dir = "ltr";
  if (extraClass) bdi.className = extraClass;
  bdi.textContent = text;
  return bdi;
}

function renderAll(state) {
  appState = state;
  const { settings, ip_info, sys_state, alignment, snapshots, logs, is_admin } = state;

  // Sync language & theme from settings on initial load
  if (settings.ui_language && settings.ui_language !== currentLang) {
    currentLang = settings.ui_language;
    document.documentElement.lang = currentLang;
    document.documentElement.dir = currentLang === "fa" ? "rtl" : "ltr";
    document.querySelectorAll("[data-i18n]").forEach((el) => {
      const k = el.getAttribute("data-i18n");
      if (k) el.textContent = t(k);
    });
  }
  applyTheme(settings.theme || "system");

  // Sidebar status pills
  const smartBtn = $("#btn-smart-toggle");
  smartBtn.setAttribute("aria-pressed", String(Boolean(settings.smart_auto_sync)));
  $("#smart-toggle-label").textContent = settings.smart_auto_sync ? t("smartAutoOn") : t("smartAutoOff");

  const adminBtn = $("#btn-admin-badge");
  adminBtn.classList.toggle("is-admin", Boolean(is_admin));
  $("#admin-badge-label").textContent = is_admin ? t("adminActive") : t("adminNeeded");

  // Score Gauge
  const score = alignment.ready ? alignment.score : 0;
  const risk = alignment.risk_level || "unknown";
  const gaugeCard = document.querySelector(".gauge-card");
  gaugeCard.dataset.risk = risk;
  $("#score-value").textContent = alignment.ready ? toLocalizedDigits(score) : "--";
  const circumference = 314.16;
  const offset = circumference - (circumference * score) / 100;
  $("#score-ring-fill").style.strokeDashoffset = String(offset);

  const riskHeadMap = {
    safe: t("statusSafe"),
    warning: t("statusWarning"),
    critical: t("statusCritical"),
    unknown: t("statusUnknown"),
  };
  $("#risk-headline").textContent = riskHeadMap[risk] || t("statusUnknown");

  if (!ip_info.ok && ip_info.error) {
    $("#risk-subline").textContent = t("noIpError");
  } else if (alignment.ready) {
    const count = alignment.mismatch_count || 0;
    $("#risk-subline").textContent =
      currentLang === "fa"
        ? count === 0
          ? "همه فاکتورهای اصلی ویندوز با موقعیت آی‌پی هماهنگ هستند."
          : `${toLocalizedDigits(count)} مورد ناهماهنگی شناسایی شد که قابل رفع است.`
        : count === 0
        ? "All monitored Windows properties match your public IP."
        : `${count} mismatch(es) detected and ready to align.`;
  }

  // Telemetry Card
  $("#val-ip").textContent = ip_info.ip || "--";
  const ipBadge = $("#val-ip-badge");
  if (!ip_info.ok) {
    ipBadge.className = "badge badge-danger";
    ipBadge.textContent = "Offline / Error";
  } else if (ip_info.is_hosting || ip_info.is_proxy) {
    ipBadge.className = "badge badge-warning";
    ipBadge.textContent = t("datacenterIp");
  } else {
    ipBadge.className = "badge badge-safe";
    ipBadge.textContent = t("residentialIp");
  }

  const locParts = [ip_info.country_name, ip_info.city].filter(Boolean);
  $("#val-location").textContent = locParts.length ? locParts.join(" — ") : "--";
  $("#val-coords").textContent =
    ip_info.latitude != null ? `${ip_info.latitude}, ${ip_info.longitude}` : "--";
  $("#val-ip-tz").textContent = ip_info.iana_timezone || "--";
  $("#val-ip-currency").textContent = ip_info.currency
    ? `${currentLang === "fa" ? "واحد پول" : "Currency"}: ${ip_info.currency}`
    : "--";

  $("#val-sys-tz").textContent = `${sys_state.timezone_id || "--"} (${sys_state.utc_offset_str || ""})`;
  $("#val-sys-time").textContent = sys_state.local_time || "--";
  $("#val-isp").textContent = [ip_info.isp, ip_info.asn].filter(Boolean).join(" • ") || "--";
  $("#last-checked-badge").textContent = ip_info.checked_at
    ? `${currentLang === "fa" ? "آخرین بررسی:" : "Last check:"} ${ip_info.checked_at}`
    : "";

  // Planned Changes Pills
  const diffContainer = $("#planned-changes-list");
  diffContainer.replaceChildren();
  const planned = alignment.planned_changes || [];
  if (planned.length === 0) {
    const okMsg = document.createElement("span");
    okMsg.className = "badge badge-safe";
    okMsg.textContent = t("noPendingChanges");
    diffContainer.append(okMsg);
  } else {
    planned.forEach((ch) => {
      const pill = document.createElement("div");
      pill.className = "diff-pill";
      const label = document.createElement("strong");
      label.textContent = currentLang === "fa" ? ch.label_fa : ch.label_en;
      const arrow = document.createElement("span");
      arrow.textContent = ": ";
      pill.append(label, arrow, makeBdi(`${ch.from} → ${ch.to}`, "mono"));
      diffContainer.append(pill);
    });
  }

  // Audit Table
  const tbody = $("#checks-tbody");
  tbody.replaceChildren();
  (alignment.checks || []).forEach((chk) => {
    const tr = document.createElement("tr");

    const tdFactor = document.createElement("td");
    const titleDiv = document.createElement("div");
    titleDiv.className = "factor-title";
    titleDiv.textContent = currentLang === "fa" ? chk.title_fa : chk.title_en;
    const descDiv = document.createElement("div");
    descDiv.className = "factor-desc";
    descDiv.textContent = currentLang === "fa" ? chk.detail_fa : chk.detail_en;
    tdFactor.append(titleDiv, descDiv);

    const tdCur = document.createElement("td");
    tdCur.append(makeBdi(chk.current || "--", "mono"));

    const tdExp = document.createElement("td");
    tdExp.append(makeBdi(chk.expected || "--", "mono"));

    const tdStatus = document.createElement("td");
    const badge = document.createElement("span");
    badge.className = chk.matched
      ? "badge badge-safe"
      : chk.severity === "high"
      ? "badge badge-danger"
      : "badge badge-warning";
    badge.textContent = chk.matched ? `✓ ${t("matched")}` : `! ${t("mismatch")}`;
    tdStatus.append(badge);

    tr.append(tdFactor, tdCur, tdExp, tdStatus);
    tbody.append(tr);
  });

  // Render Profiles & Snapshots
  renderSnapshots(snapshots || []);

  // Render Diagnostics & Logs
  renderDiagnostics(ip_info, sys_state, logs || []);

  // Sync Settings form controls
  syncSettingsForm(settings);
}

function renderSnapshots(snapshots) {
  const grid = $("#snapshots-grid");
  grid.replaceChildren();
  snapshots.forEach((snap) => {
    const card = document.createElement("article");
    card.className = `snapshot-card ${snap.kind === "baseline" ? "is-baseline" : ""}`;

    const header = document.createElement("div");
    header.className = "card-header";
    const h3 = document.createElement("h3");
    h3.textContent = snap.name;

    const badge = document.createElement("span");
    badge.className =
      snap.kind === "baseline"
        ? "badge badge-safe"
        : snap.kind === "custom"
        ? "badge badge-warning"
        : "badge badge-neutral";
    badge.textContent =
      snap.kind === "baseline"
        ? t("badgeBaseline")
        : snap.kind === "custom"
        ? t("badgeCustom")
        : t("badgeAuto");
    header.append(h3, badge);

    const meta = document.createElement("div");
    meta.className = "snapshot-meta";
    const st = snap.state || {};
    meta.append(
      makeBdi(`TZ: ${st.timezone_id || "-"}`),
      makeBdi(`GeoID: ${st.geo_id ?? "-"}`),
      makeBdi(`Culture: ${st.culture || "-"}`),
      makeBdi(snap.created_at || "")
    );

    const notes = document.createElement("p");
    notes.className = "muted-text";
    notes.textContent = snap.notes || "";

    const actions = document.createElement("div");
    actions.className = "snapshot-actions";
    const restoreBtn = document.createElement("button");
    restoreBtn.type = "button";
    restoreBtn.className = "btn btn-primary btn-sm";
    restoreBtn.textContent = t("restore");
    restoreBtn.addEventListener("click", () => handleRestore(snap.id));
    actions.append(restoreBtn);

    if (snap.kind !== "baseline") {
      const delBtn = document.createElement("button");
      delBtn.type = "button";
      delBtn.className = "btn btn-danger btn-sm";
      delBtn.textContent = t("delete");
      delBtn.addEventListener("click", async () => {
        const res = await api(`/api/snapshots/${snap.id}`, "DELETE");
        if (res.ok && res.state) {
          renderAll(res.state);
          showToast(currentLang === "fa" ? "پروفایل حذف شد." : "Snapshot deleted.");
        }
      });
      actions.append(delBtn);
    }

    card.append(header, meta, notes, actions);
    grid.append(card);
  });
}

function renderDiagnostics(ip_info, sys_state, logs) {
  const dnsBody = $("#diag-dns-body");
  dnsBody.replaceChildren();
  const dns = sys_state.dns || {};
  const dnsRiskBadge = document.createElement("span");
  dnsRiskBadge.className =
    dns.risk === "safe"
      ? "badge badge-safe"
      : dns.risk === "high"
      ? "badge badge-danger"
      : "badge badge-warning";
  dnsRiskBadge.textContent = `DNS Risk: ${(dns.risk || "unknown").toUpperCase()}`;
  dnsBody.append(dnsRiskBadge);

  const dnsList = document.createElement("div");
  dnsList.append(makeBdi((dns.all_dns || []).join(", ") || "Auto / Unknown", "mono"));
  dnsBody.append(dnsList);
  (dns.notes || []).forEach((n) => {
    const p = document.createElement("p");
    p.className = "muted-text";
    p.textContent = n;
    dnsBody.append(p);
  });

  const v6Body = $("#diag-ipv6-body");
  v6Body.replaceChildren();
  const v6Badge = document.createElement("span");
  v6Badge.className = ip_info.ipv6_leak ? "badge badge-danger" : "badge badge-safe";
  v6Badge.textContent = ip_info.ipv6_leak ? "IPv6 Leak Detected" : "No IPv6 Leak";
  v6Body.append(v6Badge, makeBdi(ip_info.ipv6 || "IPv6 Not Reachable", "mono"));

  const repBody = $("#diag-reputation-body");
  repBody.replaceChildren();
  const repBadge = document.createElement("span");
  repBadge.className = ip_info.is_hosting || ip_info.is_proxy ? "badge badge-warning" : "badge badge-safe";
  repBadge.textContent = ip_info.is_hosting || ip_info.is_proxy ? t("datacenterIp") : t("residentialIp");
  repBody.append(repBadge, makeBdi(`${ip_info.isp || "-"} (${ip_info.provider || "-"})`));

  const logsList = $("#logs-list");
  logsList.replaceChildren();
  logs.forEach((item) => {
    const li = document.createElement("li");
    li.className = "log-item";
    const msg = document.createElement("span");
    msg.textContent = item.summary;
    const meta = makeBdi(`${item.action} • ${item.timestamp}`, "muted-meta mono");
    li.append(msg, meta);
    logsList.append(li);
  });
}

function syncSettingsForm(s) {
  $("#setting-proxy-mode").value = s.proxy_mode || "system";
  $("#setting-custom-proxy").value = s.custom_proxy_url || "";
  $("#custom-proxy-wrap").hidden = s.proxy_mode !== "custom";
  $("#setting-smart-auto").checked = Boolean(s.smart_auto_sync);
  $("#setting-auto-snapshot").checked = Boolean(s.auto_snapshot_before_apply);
  $("#setting-minimize-tray").checked = Boolean(s.minimize_to_tray);
  $("#setting-watch-interval").value = String(s.watch_interval_sec || 12);
  $("#setting-sync-tz").checked = Boolean(s.sync_timezone);
  $("#setting-sync-ntp").checked = Boolean(s.sync_ntp_clock);
  $("#setting-sync-geoid").checked = Boolean(s.sync_geoid);
  $("#setting-sync-culture").checked = Boolean(s.sync_culture);
  $("#setting-sync-lang").checked = Boolean(s.sync_language_list);
  $("#setting-keep-fa").checked = Boolean(s.keep_persian_keyboard);
  $("#setting-sync-loc").checked = Boolean(s.sync_location_privacy);
  $("#setting-sync-dns").checked = Boolean(s.sync_dns);
  $("#setting-dns-provider").value = s.preferred_dns_provider || "cloudflare";
  $("#setting-theme").value = s.theme || "system";
  $("#setting-ui-lang").value = s.ui_language || "fa";
}

async function loadCountries() {
  const res = await api("/api/countries");
  const select = $("#country-select");
  select.replaceChildren();
  (res.countries || []).forEach((c) => {
    const opt = document.createElement("option");
    opt.value = c.code;
    opt.textContent = `${c.name_fa} — ${c.name} (${c.code})`;
    select.append(opt);
  });
  countriesLoaded = true;
}

async function handleSyncClick() {
  if (!appState?.alignment?.ready) {
    showToast(t("noIpError"), "error");
    return;
  }
  const planned = appState.alignment.planned_changes || [];
  if (planned.length === 0) {
    showToast(t("noPendingChanges"), "ok");
    return;
  }

  const dialog = $("#confirm-apply-dialog");
  const list = $("#confirm-diff-list");
  list.replaceChildren();
  planned.forEach((ch) => {
    const li = document.createElement("li");
    li.className = "diff-modal-item";
    const lbl = document.createElement("strong");
    lbl.textContent = currentLang === "fa" ? ch.label_fa : ch.label_en;
    li.append(lbl, makeBdi(`${ch.from} → ${ch.to}`, "mono"));
    list.append(li);
  });
  dialog.showModal();
}

async function executeApplyNow() {
  showToast(t("applying"), "ok");
  const res = await api("/api/apply", "POST");
  if (res.state) renderAll(res.state);
  const r = res.result || {};
  if (r.ok) {
    showToast(
      currentLang === "fa"
        ? `هماهنگ‌سازی کامل انجام شد (${toLocalizedDigits(r.applied_count)} مورد).`
        : `Aligned successfully (${r.applied_count} steps).`,
      "ok"
    );
  } else if (r.partial) {
    showToast(
      currentLang === "fa"
        ? `تعدادی از تغییرات اعمال شد؛ برای NTP یا DNS نیاز به دسترسی مدیر است.`
        : `Partially applied; run as Administrator for NTP/DNS.`,
      "error"
    );
  } else {
    showToast(currentLang === "fa" ? "خطا در اعمال تغییرات." : "Failed to apply changes.", "error");
  }
}

async function handleRestore(snapshotId) {
  showToast(t("restoring"), "ok");
  const res = await api("/api/restore", "POST", { snapshot_id: snapshotId });
  if (res.state) renderAll(res.state);
  if (res.ok) {
    showToast(
      currentLang === "fa"
        ? `تنظیمات به «${res.restored}» بازگردانده شد.`
        : `Restored to "${res.restored}".`,
      "ok"
    );
  } else {
    showToast(res.message || "Restore failed", "error");
  }
}

function bindEvents() {
  setupTabsKeyboard();

  $("#btn-refresh").addEventListener("click", async () => {
    const btn = $("#btn-refresh");
    btn.disabled = true;
    try {
      const state = await api("/api/refresh", "POST");
      renderAll(state);
      showToast(currentLang === "fa" ? "اطلاعات آی‌پی و سیستم به‌روزرسانی شد." : "Scan complete.");
    } finally {
      btn.disabled = false;
    }
  });

  $("#btn-sync-primary").addEventListener("click", handleSyncClick);
  $("#btn-undo-last").addEventListener("click", () => handleRestore("latest"));
  $("#btn-restore-baseline-hero").addEventListener("click", () => handleRestore("baseline"));

  $("#confirm-apply-dialog").addEventListener("close", (e) => {
    const dlg = e.currentTarget;
    const choice = dlg.returnValue;
    dlg.returnValue = "";
    if (choice === "confirm") executeApplyNow();
  });

  const openSaveDialog = () => {
    $("#input-profile-name").value = "";
    $("#input-profile-notes").value = "";
    $("#save-profile-dialog").showModal();
  };
  $("#btn-save-snapshot-hero").addEventListener("click", openSaveDialog);
  $("#btn-open-save-profile").addEventListener("click", openSaveDialog);

  $("#save-profile-dialog").addEventListener("close", async (e) => {
    const dlg = e.currentTarget;
    const choice = dlg.returnValue;
    dlg.returnValue = "";
    if (choice === "save") {
      const name = $("#input-profile-name").value.trim();
      const notes = $("#input-profile-notes").value.trim();
      if (!name) return;
      const res = await api("/api/snapshots", "POST", { name, notes });
      if (res.ok && res.state) {
        renderAll(res.state);
        showToast(currentLang === "fa" ? "پروفایل ذخیره شد." : "Profile saved.");
      }
    }
  });

  $("#btn-export-profiles").addEventListener("click", () => {
    window.location.href = "/api/snapshots/export";
  });

  $("#btn-open-import-profile").addEventListener("click", () => {
    $("#input-import-json").value = "";
    $("#import-profile-dialog").showModal();
  });

  $("#import-profile-dialog").addEventListener("close", async (e) => {
    const dlg = e.currentTarget;
    const choice = dlg.returnValue;
    dlg.returnValue = "";
    if (choice === "import") {
      const raw_json = $("#input-import-json").value.trim();
      if (!raw_json) return;
      const res = await api("/api/snapshots/import", "POST", { raw_json });
      if (res.ok && res.state) {
        renderAll(res.state);
        showToast(currentLang === "fa" ? "پروفایل‌ها وارد شدند." : "Profiles imported.");
      } else {
        showToast(res.message || "Invalid JSON", "error");
      }
    }
  });

  $("#btn-apply-country").addEventListener("click", async () => {
    const code = $("#country-select").value;
    if (!code) return;
    const res = await api("/api/apply-country", "POST", { country_code: code });
    if (res.state) renderAll(res.state);
    showToast(currentLang === "fa" ? `پروفایل کشور ${code} اعمال شد.` : `Applied ${code}.`);
  });

  const launchBrowser = async (url) => {
    const res = await api("/api/launch-browser", "POST", { url });
    showToast(res.message || "Done", res.ok ? "ok" : "error");
  };
  $("#btn-launch-browser-quick").addEventListener("click", () => launchBrowser("https://whoer.net"));
  $("#btn-launch-browser-full").addEventListener("click", () =>
    launchBrowser($("#browser-url-input").value || "https://whoer.net")
  );

  $("#btn-smart-toggle").addEventListener("click", async () => {
    const next = !appState?.settings?.smart_auto_sync;
    const res = await api("/api/settings", "POST", { smart_auto_sync: next });
    if (res.state) renderAll(res.state);
  });

  $("#btn-admin-badge").addEventListener("click", async () => {
    if (appState?.is_admin) return;
    const res = await api("/api/elevate", "POST");
    if (!res.ok) showToast("UAC elevation cancelled.", "error");
  });

  $("#btn-lang-switch").addEventListener("click", async () => {
    const next = currentLang === "fa" ? "en" : "fa";
    applyLanguage(next);
    await api("/api/settings", "POST", { ui_language: next });
  });

  $("#btn-theme-cycle").addEventListener("click", async () => {
    const cur = appState?.settings?.theme || "system";
    const order = ["system", "dark", "light"];
    const next = order[(order.indexOf(cur) + 1) % order.length];
    const res = await api("/api/settings", "POST", { theme: next });
    if (res.state) renderAll(res.state);
  });

  // Live Settings autosave
  const bindSetting = (id, key, prop = "checked") => {
    $(id).addEventListener("change", async (e) => {
      const val = e.target[prop];
      const res = await api("/api/settings", "POST", { [key]: val });
      if (res.state) renderAll(res.state);
    });
  };
  bindSetting("#setting-proxy-mode", "proxy_mode", "value");
  bindSetting("#setting-custom-proxy", "custom_proxy_url", "value");
  bindSetting("#setting-smart-auto", "smart_auto_sync", "checked");
  bindSetting("#setting-auto-snapshot", "auto_snapshot_before_apply", "checked");
  bindSetting("#setting-minimize-tray", "minimize_to_tray", "checked");
  bindSetting("#setting-watch-interval", "watch_interval_sec", "value");
  bindSetting("#setting-sync-tz", "sync_timezone", "checked");
  bindSetting("#setting-sync-ntp", "sync_ntp_clock", "checked");
  bindSetting("#setting-sync-geoid", "sync_geoid", "checked");
  bindSetting("#setting-sync-culture", "sync_culture", "checked");
  bindSetting("#setting-sync-lang", "sync_language_list", "checked");
  bindSetting("#setting-keep-fa", "keep_persian_keyboard", "checked");
  bindSetting("#setting-sync-loc", "sync_location_privacy", "checked");
  bindSetting("#setting-sync-dns", "sync_dns", "checked");
  bindSetting("#setting-dns-provider", "preferred_dns_provider", "value");
  bindSetting("#setting-theme", "theme", "value");
  bindSetting("#setting-ui-lang", "ui_language", "value");
}

async function init() {
  bindEvents();
  const state = await api("/api/state");
  renderAll(state);

  setInterval(async () => {
    try {
      const latest = await api("/api/state");
      renderAll(latest);
    } catch {}
  }, 5000);
}

init();
