/**
 * FeeReconcile Frontend Application
 * Vanilla JavaScript (Zero build tools, Zero external dependencies)
 * Strict UI/UX Specification Implementation
 */

document.addEventListener("DOMContentLoaded", () => {
  // Global State
  const state = {
    currentView: "dashboard",
    currentTab: "students",
    students: [],
    invoices: [],
    payments: [],
    exceptions: [],
    allExceptionsForTab: [],
    exceptionReasonFilter: "",
    exceptionSearchQuery: "",
    exceptionSortField: "default", // 'default' | 'amount' | 'reason'
    exceptionSortDirection: "asc", // 'asc' | 'desc'
    resolvedFilter: false,
    summary: null,
    batches: [],
    selectedPayment: null,
    activeResolvingRow: null,
  };

  // =========================================================================
  // UTILITIES & HELPERS
  // =========================================================================

  function formatRupees(paise) {
    if (paise === null || paise === undefined || isNaN(paise)) return "—";
    const paiseNum = Number(paise);
    if (paiseNum === 0) return "₹0.00";
    const rupees = paiseNum / 100.0;
    try {
      return new Intl.NumberFormat("en-IN", {
        style: "currency",
        currency: "INR",
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      }).format(rupees);
    } catch {
      return `₹${rupees.toLocaleString("en-IN", { minimumFractionDigits: 2 })}`;
    }
  }

  function formatDisplayDate(dateStr) {
    if (!dateStr) return "—";
    try {
      const d = new Date(dateStr);
      if (isNaN(d.getTime())) return String(dateStr);
      return d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
    } catch {
      return String(dateStr);
    }
  }

  function getRelativeTimeString(dateStr) {
    if (!dateStr) return "recently";
    try {
      const d = new Date(dateStr);
      if (isNaN(d.getTime())) return String(dateStr);
      const diffMs = Date.now() - d.getTime();
      const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));
      if (diffDays <= 0) return "today";
      if (diffDays === 1) return "1 day ago";
      if (diffDays < 30) return `${diffDays} days ago`;
      const diffMonths = Math.floor(diffDays / 30);
      return diffMonths === 1 ? "1 month ago" : `${diffMonths} months ago`;
    } catch {
      return "recently";
    }
  }

  function formatMatchReason(str) {
    if (!str || str === "—") return "—";
    const s = String(str);
    if (s.includes("Exact invoice_ref match") || s.includes("Exact invoice ID match")) {
      return "Exact invoice and student ID match";
    }
    if (s.includes("Fuzzy name match")) {
      const pct = s.match(/(\d+)%/);
      return `Name similarity match ${pct ? `(${pct[1]}%)` : ''}`.trim();
    }
    if (s.includes("Duplicate txn_ref") || s.includes("Duplicate transaction")) {
      return "Duplicate transaction reference";
    }
    if (s.includes("Suspected duplicate")) {
      return "Identical student, amount, and method within 24 hours";
    }
    return s
      .replace(/_ref/gi, " ID")
      .replace(/_/g, " ")
      .replace(/Base:\s*/i, "")
      .replace(/\s*\(\d+\)/g, "")
      .replace(/\.\s*Total score:\s*\d+\/\d+/i, "")
      .trim();
  }

  function escapeHtml(str) {
    if (str === null || str === undefined) return "";
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function showToast(message, type = "success") {
    const container = document.getElementById("toast-container");
    if (!container) return;
    const toast = document.createElement("div");
    toast.className = `toast toast-${type}`;
    
    let iconSvg = `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M20 6L9 17l-5-5"/></svg>`;
    if (type === "error") {
      iconSvg = `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>`;
    } else if (type === "warning") {
      iconSvg = `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><line x1="12" y1="9" x2="12" y2="13"/></svg>`;
    }

    toast.innerHTML = `
      <div style="color:${type === 'error' ? '#ef4444' : type === 'warning' ? '#f59e0b' : '#10b981'}">
        ${iconSvg}
      </div>
      <div>${escapeHtml(message)}</div>
    `;

    container.appendChild(toast);
    setTimeout(() => {
      toast.style.opacity = "0";
      toast.style.transition = "opacity 0.25s ease";
      setTimeout(() => toast.remove(), 260);
    }, 3800);
  }

  async function apiFetch(url, options = {}) {
    const errorBanner = document.getElementById("global-error-banner");
    try {
      const response = await fetch(url, options);
      if (errorBanner) errorBanner.style.display = "none";
      if (!response.ok) {
        let errData = {};
        try {
          errData = await response.json();
        } catch {
          errData = { detail: response.statusText };
        }
        const msg = errData.detail || errData.error || `HTTP error ${response.status}`;
        const err = new Error(msg);
        err.status = response.status;
        throw err;
      }
      const contentType = response.headers.get("content-type");
      if (contentType && contentType.includes("application/json")) {
        return await response.json();
      }
      return await response.text();
    } catch (err) {
      console.error("API Fetch Error:", err);
      if (errorBanner) {
        const errorText = document.getElementById("global-error-text");
        if (errorText) errorText.textContent = err.message || "Failed to communicate with server.";
        errorBanner.style.display = "flex";
      }
      if (!options.silentError) {
        showToast(err.message || "Failed to communicate with server", "error");
      }
      throw err;
    }
  }

  // Reason configuration with semantic colors, human labels and icons
  const REASON_CONFIG = {
    AMBIGUOUS_MATCH: {
      label: "Ambiguous match",
      chipLabel: "Ambiguous",
      colorClass: "reason-ambiguous",
      sortPriority: 3,
      iconSvg: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/><line x1="12" x2="12.01" y1="17" y2="17"/></svg>`
    },
    PARTIAL: {
      label: "Partial",
      chipLabel: "Partial",
      colorClass: "reason-partial",
      sortPriority: 6,
      iconSvg: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M21.21 15.89A10 10 0 1 1 8 2.83"/><path d="M22 12A10 10 0 0 0 12 2v10z"/></svg>`
    },
    DUPLICATE: {
      label: "Duplicate",
      chipLabel: "Duplicate",
      colorClass: "reason-duplicate",
      sortPriority: 4,
      iconSvg: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><rect width="14" height="14" x="8" y="8" rx="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/></svg>`
    },
    OVERPAID: {
      label: "Overpaid",
      chipLabel: "Overpaid",
      colorClass: "reason-overpaid",
      sortPriority: 5,
      iconSvg: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="12" cy="12" r="10"/><polyline points="16 12 12 8 8 12"/><line x1="12" x2="12" y1="16" y2="8"/></svg>`
    },
    UNMATCHED: {
      label: "Unmatched",
      chipLabel: "Unmatched",
      colorClass: "reason-unmatched",
      sortPriority: 2,
      iconSvg: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><line x1="17" x2="22" y1="8" y2="13"/><line x1="22" x2="17" y1="8" y2="13"/></svg>`
    },
    INVALID_ROW: {
      label: "Invalid row",
      chipLabel: "Invalid",
      colorClass: "reason-invalid",
      sortPriority: 1,
      iconSvg: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polygon points="7.86 2 16.14 2 22 7.86 22 16.14 16.14 22 7.86 22 2 16.14 2 7.86 7.86 2"/><line x1="12" x2="12" y1="8" y2="12"/><line x1="12" x2="12.01" y1="16" y2="16"/></svg>`
    }
  };

  function humanizeReason(code) {
    if (!code) return "Unknown";
    const upper = String(code).toUpperCase();
    if (REASON_CONFIG[upper]) return REASON_CONFIG[upper].label;
    if (upper === "REVIEW_REQUIRED") return "Awaiting review";
    if (upper === "SETTLED_INVOICE") return "Settled invoice";
    return upper.replace(/_/g, " ").toLowerCase().replace(/^\w/, c => c.toUpperCase());
  }

  function getBadgeClass(status) {
    if (!status) return "badge-neutral";
    const s = String(status).toLowerCase();
    switch (s) {
      case "paid":
      case "matched":
        return "badge-paid";
      case "partial":
        return "badge-partial";
      case "review":
      case "ambiguous_match":
      case "ambiguous":
        return "badge-review";
      case "overdue":
        return "badge-overdue";
      case "unmatched":
        return "badge-unmatched";
      case "duplicate":
        return "badge-duplicate";
      case "overpaid":
        return "badge-overpaid";
      case "invalid_row":
      case "invalid":
        return "badge-invalid";
      case "pending":
        return "badge-pending";
      default:
        return "badge-neutral";
    }
  }

  function renderConfidenceMeter(score) {
    const s = Math.max(0, Math.min(100, Number(score) || 0));
    let colorClass = "#f59e0b";
    if (s >= 80) colorClass = "#10b981";
    else if (s < 50) colorClass = "#ef4444";

    return `
      <div class="confidence-bar-mini" title="Confidence: ${s}%">
        <div class="confidence-track">
          <div class="confidence-fill" style="width: ${s}%; background-color: ${colorClass};"></div>
        </div>
        <span class="tabular-nums font-semibold" style="font-size:12px;color:var(--text-muted);">${s}%</span>
      </div>
    `;
  }

  // =========================================================================
  // THEME (DARK / LIGHT)
  // =========================================================================

  function initTheme() {
    try {
      const saved = localStorage.getItem("feereconcile_theme");
      if (saved === "dark") {
        document.documentElement.classList.add("dark");
        document.body.classList.add("theme-dark");
        document.body.classList.remove("theme-light");
      } else {
        document.documentElement.classList.remove("dark");
        document.body.classList.remove("theme-dark");
        document.body.classList.add("theme-light");
      }
    } catch {
      // Ignore localStorage issues
    }
  }

  function toggleTheme() {
    try {
      const isDark = document.documentElement.classList.toggle("dark");
      document.body.classList.toggle("theme-dark", isDark);
      document.body.classList.toggle("theme-light", !isDark);
      localStorage.setItem("feereconcile_theme", isDark ? "dark" : "light");
      if (state.currentView === "dashboard" && state.summary) {
        renderDashboardCharts(state.summary);
      }
    } catch {
      // Ignore localStorage issues
    }
  }

  const themeToggleBtn = document.getElementById("btn-theme-toggle");
  if (themeToggleBtn) {
    themeToggleBtn.addEventListener("click", toggleTheme);
  }
  initTheme();

  // Mobile Hamburger Menu
  const sidebar = document.getElementById("sidebar");
  const hamburgerBtn = document.getElementById("btn-hamburger");
  if (hamburgerBtn && sidebar) {
    hamburgerBtn.addEventListener("click", () => {
      sidebar.classList.toggle("open");
    });
  }

  // =========================================================================
  // ROUTING & VIEW NAVIGATION
  // =========================================================================

  const viewTitles = {
    dashboard: { title: "Dashboard", sub: "College fee reconciliation overview" },
    obligations: { title: "Fee Obligations", sub: "Students registry and invoices management" },
    payments: { title: "Payments", sub: "Bank statements and transaction feeds" },
    reconciliation: { title: "Reconciliation", sub: "Automated cascade rules and matching ledger" },
    exceptions: { title: "Exceptions", sub: "Payments that need a decision before invoices are updated." },
    reports: { title: "Reports", sub: "Financial audit and reconciliation progress" },
  };

  function updateHeaderExportBtn(viewName) {
    const exportBtn = document.getElementById("btn-header-export-csv");
    if (!exportBtn) return;
    if (viewName === "exceptions") {
      exportBtn.style.display = "inline-flex";
      exportBtn.onclick = () => {
        window.location.href = "/api/reports/export/exceptions.csv";
      };
    } else if (viewName === "reports") {
      exportBtn.style.display = "inline-flex";
      exportBtn.onclick = () => {
        window.location.href = "/api/reports/export/reconciliation.csv";
      };
    } else {
      exportBtn.style.display = "none";
      exportBtn.onclick = null;
    }
  }

  function switchView(viewName) {
    state.currentView = viewName;
    if (sidebar) sidebar.classList.remove("open");

    // Close any open popovers or drawers
    closeAllPopoversAndDrawers();

    // Update active nav button
    document.querySelectorAll(".sidebar-nav .nav-item").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.view === viewName);
    });

    // Update title and subtitle
    const meta = viewTitles[viewName] || { title: "FeeReconcile", sub: "" };
    const titleEl = document.getElementById("page-title");
    const subEl = document.getElementById("page-subtitle");
    if (titleEl) titleEl.textContent = meta.title;
    if (subEl) subEl.textContent = meta.sub;

    // Toggle view sections
    document.querySelectorAll(".view-section").forEach((sec) => {
      sec.classList.remove("active");
    });
    const targetSec = document.getElementById(`view-${viewName}`);
    if (targetSec) targetSec.classList.add("active");

    // Update header export button
    updateHeaderExportBtn(viewName);

    // Refresh view data
    loadViewData(viewName);
  }

  document.querySelectorAll(".sidebar-nav .nav-item").forEach((btn) => {
    btn.addEventListener("click", () => switchView(btn.dataset.view));
  });

  const dashViewExceptionsBtn = document.getElementById("btn-dash-view-exceptions");
  if (dashViewExceptionsBtn) dashViewExceptionsBtn.addEventListener("click", () => switchView("exceptions"));
  const dashGoPaymentsBtn = document.getElementById("btn-dash-go-payments");
  if (dashGoPaymentsBtn) dashGoPaymentsBtn.addEventListener("click", () => switchView("payments"));

  // =========================================================================
  // DATA LOADING DISPATCHER
  // =========================================================================

  async function loadViewData(viewName) {
    try {
      if (viewName === "dashboard") {
        await fetchDashboardData();
      } else if (viewName === "obligations") {
        if (state.currentTab === "students") {
          await fetchStudents();
        } else {
          await fetchInvoices();
        }
      } else if (viewName === "payments") {
        await fetchPayments();
      } else if (viewName === "reconciliation") {
        await fetchReconciliationData();
      } else if (viewName === "exceptions") {
        await fetchExceptions();
      } else if (viewName === "reports") {
        await fetchReportsData();
      }
    } catch (err) {
      console.error(`Error loading data for ${viewName}:`, err);
    }
  }

  // =========================================================================
  // PAGE 1: DASHBOARD
  // =========================================================================

  async function fetchDashboardData() {
    const summary = await apiFetch("/api/reports/summary");
    state.summary = summary;

    // Update KPI values
    const kpiDue = document.getElementById("kpi-total-due");
    const kpiRec = document.getElementById("kpi-total-received");
    const kpiOut = document.getElementById("kpi-total-outstanding");
    const kpiRate = document.getElementById("kpi-collection-rate");
    const kpiProg = document.getElementById("kpi-collection-progress");
    const kpiInvs = document.getElementById("kpi-total-invoices");

    if (kpiDue) kpiDue.textContent = formatRupees(summary.total_due);
    if (kpiRec) kpiRec.textContent = formatRupees(summary.total_received);
    if (kpiOut) kpiOut.textContent = formatRupees(summary.total_outstanding);

    // Single source for collection %: Labelled "Collected 42.1%" with tooltip "Total received / total due"
    if (kpiRate) {
      kpiRate.textContent = `Collected ${summary.collection_rate || 0.0}%`;
      kpiRate.title = "Total received / total due";
    }
    if (kpiProg) kpiProg.style.width = `${Math.min(100, summary.collection_rate || 0)}%`;
    if (kpiInvs) kpiInvs.textContent = summary.total_invoices || 0;

    // Update sidebar exceptions badge (the ONLY place open count appears in sidebar)
    updateSidebarExceptionsBadge(summary.open_exceptions_count || 0);

    // Render Charts
    renderDashboardCharts(summary);

    // Exceptions summary list in Dashboard
    const pillsContainer = document.getElementById("dash-exceptions-pills");
    if (pillsContainer) {
      pillsContainer.innerHTML = "";
      const excByReason = summary.open_exceptions_by_reason || {};
      let totalOpen = 0;
      for (const [code, count] of Object.entries(excByReason)) {
        if (count > 0) {
          totalOpen += count;
          const cfg = REASON_CONFIG[code] || {};
          const humanLabel = cfg.label || humanizeReason(code);
          const colorClass = cfg.colorClass || getBadgeClass(code.toLowerCase());
          const row = document.createElement("div");
          row.style.display = "flex";
          row.style.alignItems = "center";
          row.style.justifyContent = "space-between";
          row.style.padding = "10px 0";
          row.style.borderBottom = "1px solid var(--border-color)";
          row.innerHTML = `
            <span style="font-weight:600;font-size:13.5px;color:var(--text-main);">${escapeHtml(humanLabel)}</span>
            <span class="reason-pill ${colorClass}" style="font-variant-numeric:tabular-nums;">${count} open</span>
          `;
          pillsContainer.appendChild(row);
        }
      }
      if (totalOpen === 0) {
        pillsContainer.innerHTML = `
          <div class="empty-state-box" style="padding:24px 12px;">
            <span class="empty-state-title">All payments are reconciled.</span>
            <span class="empty-state-sub">No outstanding exceptions require action.</span>
          </div>
        `;
      }
    }

    // Fetch batches table
    await fetchRecentBatches();
  }

  function updateSidebarExceptionsBadge(count) {
    const excBadge = document.getElementById("sidebar-exceptions-badge");
    if (!excBadge) return;
    if (count > 0) {
      excBadge.textContent = count;
      excBadge.style.display = "inline-block";
    } else {
      excBadge.style.display = "none";
    }
  }

  async function fetchRecentBatches() {
    const payments = await apiFetch("/api/payments?page=1&page_size=100");
    const tbody = document.getElementById("dash-batches-tbody");
    if (!tbody) return;

    if (!payments || payments.length === 0) {
      tbody.innerHTML = `
        <tr>
          <td colspan="6" class="text-center py-4">
            <div class="empty-state-box" style="padding:20px;">
              <span class="empty-state-title">No import batches recorded yet.</span>
              <span class="empty-state-sub">Load demo data to explore the reconciliation pipeline.</span>
              <button class="btn btn-primary btn-sm mt-3 btn-load-demo-data">Load demo data</button>
            </div>
          </td>
        </tr>
      `;
      const btn = tbody.querySelector(".btn-load-demo-data");
      if (btn) btn.onclick = triggerLoadDemo;
      return;
    }

    const batchesMap = {};
    payments.forEach((p) => {
      const bId = p.batch_id || "Manual";
      if (!batchesMap[bId]) {
        batchesMap[bId] = {
          id: bId,
          total: 0,
          matched: 0,
          exceptions: 0,
          date: p.payment_date || "-",
        };
      }
      batchesMap[bId].total += 1;
      if (p.match_status === "Matched") batchesMap[bId].matched += 1;
      else batchesMap[bId].exceptions += 1;
    });

    tbody.innerHTML = "";
    Object.values(batchesMap).forEach((b) => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td class="tabular-nums font-semibold">#${escapeHtml(b.id)}</td>
        <td>${b.id === "Manual" ? "Direct manual entry" : "payments_demo.csv"}</td>
        <td class="tabular-nums">${b.total}</td>
        <td><span class="badge badge-paid tabular-nums">${b.matched} matched</span></td>
        <td><span class="badge ${b.exceptions > 0 ? 'badge-review' : 'badge-neutral'} tabular-nums">${b.exceptions} exceptions</span></td>
        <td class="text-muted tabular-nums">${escapeHtml(formatDisplayDate(b.date))}</td>
      `;
      tbody.appendChild(tr);
    });
  }

  function renderDashboardCharts(summary) {
    const svg = document.getElementById("donut-svg");
    const legend = document.getElementById("donut-legend");
    if (!svg || !legend) return;
    svg.innerHTML = "";
    legend.innerHTML = "";

    const invCounts = summary.invoice_status_counts || {};
    const totalInvoices = Object.values(invCounts).reduce((a, b) => a + b, 0);
    const centerTotal = document.getElementById("donut-center-total");
    if (centerTotal) centerTotal.textContent = totalInvoices;

    // Semantic status colors matching section 1
    const invColors = {
      Paid: "#15803d",
      Partial: "#a16207",
      Pending: "#64748b",
      Overdue: "#b91c1c",
      Overpaid: "#6d28d9",
    };

    if (totalInvoices === 0) {
      svg.innerHTML = `<circle cx="110" cy="110" r="75" fill="none" stroke="var(--border-color)" stroke-width="26" />`;
      legend.innerHTML = `<span class="text-muted text-sm">No invoices recorded</span>`;
    } else {
      let cumulativePercent = 0;
      const radius = 75;
      const circumference = 2 * Math.PI * radius;

      for (const [status, count] of Object.entries(invCounts)) {
        if (count === 0) continue;
        const color = invColors[status] || "#94a3b8";
        const percent = count / totalInvoices;
        const strokeDasharray = `${percent * circumference} ${circumference}`;
        const strokeDashoffset = -cumulativePercent * circumference;

        const circle = document.createElementNS("http://www.w3.org/2000/svg", "circle");
        circle.setAttribute("cx", "110");
        circle.setAttribute("cy", "110");
        circle.setAttribute("r", radius);
        circle.setAttribute("fill", "none");
        circle.setAttribute("stroke", color);
        circle.setAttribute("stroke-width", "26");
        circle.setAttribute("stroke-dasharray", strokeDasharray);
        circle.setAttribute("stroke-dashoffset", strokeDashoffset);
        circle.setAttribute("transform", "rotate(-90 110 110)");
        svg.appendChild(circle);

        cumulativePercent += percent;

        const legItem = document.createElement("div");
        legItem.className = "legend-item";
        legItem.innerHTML = `
          <div class="legend-color" style="background-color: ${color}"></div>
          <span>${escapeHtml(status)}: <strong class="tabular-nums">${count}</strong> (${Math.round(percent * 100)}%)</span>
        `;
        legend.appendChild(legItem);
      }
    }

    // 2. Bar Chart for Payment Match Statuses
    const barContainer = document.getElementById("bar-chart-container");
    if (!barContainer) return;
    barContainer.innerHTML = "";
    const pmtCounts = summary.payment_status_counts || {};
    const filteredPmtCounts = {};
    // Don't show redundant duplicate alias "Awaiting review" inside raw chart
    for (const [k, v] of Object.entries(pmtCounts)) {
      if (k !== "Awaiting review") filteredPmtCounts[k] = v;
    }
    const totalPayments = Object.values(filteredPmtCounts).reduce((a, b) => a + b, 0);

    // Semantic reason colors strictly matching section 1
    const barColors = {
      Matched: "#15803d",
      Partial: "#a16207",
      Review: "#c2410c",
      Duplicate: "#1d4ed8",
      Overpaid: "#6d28d9",
      Unmatched: "#b91c1c",
      Invalid: "#be185d",
    };

    if (totalPayments === 0) {
      barContainer.innerHTML = `<div class="empty-state-box" style="padding:24px;"><span class="empty-state-sub">No payment transactions recorded.</span></div>`;
    } else {
      for (const [status, count] of Object.entries(filteredPmtCounts)) {
        const pct = totalPayments > 0 ? (count / totalPayments) * 100 : 0;
        const color = barColors[status] || "#94a3b8";

        const row = document.createElement("div");
        row.className = "match-bar-row";
        row.innerHTML = `
          <div class="match-bar-label">
            <span class="match-bar-dot" style="background-color:${color};"></span>
            <span>${escapeHtml(status)}</span>
          </div>
          <div class="match-bar-track">
            <div class="match-bar-fill" style="width:${pct.toFixed(1)}%;background-color:${color};"></div>
          </div>
          <div class="match-bar-stat">
            <span class="match-bar-count tabular-nums">${count}</span>
            <span class="match-bar-pct tabular-nums">(${Math.round(pct)}%)</span>
          </div>
        `;
        barContainer.appendChild(row);
      }
    }
  }

  // =========================================================================
  // PAGE 2: FEE OBLIGATIONS (STUDENTS & INVOICES)
  // =========================================================================

  const tabBtnStudents = document.getElementById("tab-btn-students");
  const tabBtnInvoices = document.getElementById("tab-btn-invoices");
  const tabPanelStudents = document.getElementById("tab-panel-students");
  const tabPanelInvoices = document.getElementById("tab-panel-invoices");
  const studentsActions = document.getElementById("students-actions");
  const invoicesActions = document.getElementById("invoices-actions");

  if (tabBtnStudents && tabBtnInvoices) {
    tabBtnStudents.addEventListener("click", () => {
      state.currentTab = "students";
      tabBtnStudents.classList.add("active");
      tabBtnInvoices.classList.remove("active");
      if (tabPanelStudents) tabPanelStudents.classList.add("active");
      if (tabPanelInvoices) tabPanelPanelInvoices && tabPanelInvoices.classList.remove("active");
      if (studentsActions) studentsActions.style.display = "flex";
      if (invoicesActions) invoicesActions.style.display = "none";
      fetchStudents();
    });

    tabBtnInvoices.addEventListener("click", () => {
      state.currentTab = "invoices";
      tabBtnInvoices.classList.add("active");
      tabBtnStudents.classList.remove("active");
      if (tabPanelInvoices) tabPanelInvoices.classList.add("active");
      if (tabPanelStudents) tabPanelStudents.classList.remove("active");
      if (studentsActions) studentsActions.style.display = "none";
      if (invoicesActions) invoicesActions.style.display = "flex";
      fetchInvoices();
    });
  }

  // Students Table
  async function fetchStudents() {
    const qInp = document.getElementById("students-search-input");
    const q = qInp ? qInp.value.trim() : "";
    const students = await apiFetch(`/api/students?q=${encodeURIComponent(q)}`);
    state.students = students;

    const countEl = document.getElementById("students-count-text");
    if (countEl) countEl.textContent = `${students.length} ${students.length === 1 ? 'student' : 'students'}`;

    const tbody = document.getElementById("students-tbody");
    if (!tbody) return;
    tbody.innerHTML = "";

    if (students.length === 0) {
      tbody.innerHTML = `
        <tr>
          <td colspan="8" class="text-center py-4">
            <div class="empty-state-box" style="padding:24px;">
              <span class="empty-state-title">No student records found.</span>
              <span class="empty-state-sub">Add a student or load demo data to populate registry.</span>
              <button class="btn btn-primary btn-sm mt-3 btn-load-demo-data">Load demo data</button>
            </div>
          </td>
        </tr>
      `;
      const btn = tbody.querySelector(".btn-load-demo-data");
      if (btn) btn.onclick = triggerLoadDemo;
      return;
    }

    students.forEach((s) => {
      const tr = document.createElement("tr");
      tr.className = "clickable-row";
      tr.tabIndex = 0;
      tr.innerHTML = `
        <td class="tabular-nums"><strong>${escapeHtml(s.student_id)}</strong></td>
        <td class="font-semibold">${escapeHtml(s.name)}</td>
        <td class="text-muted">${escapeHtml(s.email || '—')}</td>
        <td class="text-muted tabular-nums">${escapeHtml(s.phone || '—')}</td>
        <td class="text-right tabular-nums">${formatRupees(s.total_due)}</td>
        <td class="text-right text-success tabular-nums font-semibold">${s.total_paid > 0 ? formatRupees(s.total_paid) : '—'}</td>
        <td class="text-right tabular-nums font-semibold ${s.total_outstanding > 0 ? 'text-danger' : 'text-muted'}">${s.total_outstanding > 0 ? formatRupees(s.total_outstanding) : '—'}</td>
        <td class="text-right">
          <button class="btn btn-sm btn-outline-secondary btn-view-student" data-id="${s.id}">View card</button>
        </td>
      `;

      tr.addEventListener("click", (e) => {
        if (e.target.closest("button")) return;
        openStudentDetailCard(s.id);
      });
      tr.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          openStudentDetailCard(s.id);
        }
      });
      const viewBtn = tr.querySelector(".btn-view-student");
      if (viewBtn) viewBtn.onclick = () => openStudentDetailCard(s.id);

      tbody.appendChild(tr);
    });
  }

  const studentsSearchInp = document.getElementById("students-search-input");
  if (studentsSearchInp) {
    studentsSearchInp.addEventListener("input", debounce(fetchStudents, 250));
  }

  // Invoices Table
  async function fetchInvoices() {
    const qInp = document.getElementById("invoices-search-input");
    const statusInp = document.getElementById("invoices-status-filter");
    const q = qInp ? qInp.value.trim() : "";
    const statusVal = statusInp ? statusInp.value.trim() : "";

    let url = `/api/invoices?q=${encodeURIComponent(q)}`;
    if (statusVal) url += `&status=${encodeURIComponent(statusVal)}`;

    const invoices = await apiFetch(url);
    state.invoices = invoices;

    const countEl = document.getElementById("invoices-count-text");
    if (countEl) countEl.textContent = `${invoices.length} ${invoices.length === 1 ? 'invoice' : 'invoices'}`;

    const tbody = document.getElementById("invoices-tbody");
    if (!tbody) return;
    tbody.innerHTML = "";

    if (invoices.length === 0) {
      tbody.innerHTML = `
        <tr>
          <td colspan="9" class="text-center py-4">
            <div class="empty-state-box" style="padding:24px;">
              <span class="empty-state-title">No invoice obligations found.</span>
              <span class="empty-state-sub">Create an invoice or load demo data to populate records.</span>
              <button class="btn btn-primary btn-sm mt-3 btn-load-demo-data">Load demo data</button>
            </div>
          </td>
        </tr>
      `;
      const btn = tbody.querySelector(".btn-load-demo-data");
      if (btn) btn.onclick = triggerLoadDemo;
      return;
    }

    invoices.forEach((inv) => {
      const tr = document.createElement("tr");
      tr.className = "clickable-row";
      tr.tabIndex = 0;
      tr.innerHTML = `
        <td class="tabular-nums"><strong>${escapeHtml(inv.invoice_id)}</strong></td>
        <td>
          <div class="font-semibold">${escapeHtml(inv.student_name || inv.student_id)}</div>
          <span class="text-muted text-sm tabular-nums">${escapeHtml(inv.student_id)}</span>
        </td>
        <td class="text-muted">${escapeHtml(inv.description)}</td>
        <td class="text-muted tabular-nums">${formatDisplayDate(inv.due_date)}</td>
        <td class="text-center"><span class="badge ${getBadgeClass(inv.status)}">${escapeHtml(inv.status)}</span></td>
        <td class="text-right tabular-nums">${formatRupees(inv.amount_due)}</td>
        <td class="text-right text-success tabular-nums font-semibold">${inv.paid_amount > 0 ? formatRupees(inv.paid_amount) : '—'}</td>
        <td class="text-right tabular-nums font-semibold ${inv.outstanding_amount > 0 ? 'text-danger' : 'text-muted'}">${inv.outstanding_amount > 0 ? formatRupees(inv.outstanding_amount) : '—'}</td>
        <td class="text-right">
          <button class="btn btn-sm btn-outline-secondary btn-view-invoice" data-id="${inv.id}">View card</button>
        </td>
      `;

      tr.addEventListener("click", (e) => {
        if (e.target.closest("button")) return;
        openInvoiceDetailCard(inv.id);
      });
      tr.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          openInvoiceDetailCard(inv.id);
        }
      });
      const viewBtn = tr.querySelector(".btn-view-invoice");
      if (viewBtn) viewBtn.onclick = () => openInvoiceDetailCard(inv.id);

      tbody.appendChild(tr);
    });
  }

  const invoicesSearchInp = document.getElementById("invoices-search-input");
  if (invoicesSearchInp) invoicesSearchInp.addEventListener("input", debounce(fetchInvoices, 250));
  const invoicesStatusFilter = document.getElementById("invoices-status-filter");
  if (invoicesStatusFilter) invoicesStatusFilter.addEventListener("change", fetchInvoices);

  // Student Detail Modal
  let activeDetailStudent = null;
  const modalStudentDetail = document.getElementById("modal-student-detail-overlay");

  async function openStudentDetailCard(studentId) {
    const student = await apiFetch(`/api/students/${studentId}`);
    activeDetailStudent = student;

    const words = (student.name || "").trim().split(/\s+/);
    const initials = words.length > 1 ? words[0][0] + words[1][0] : (words[0] ? words[0].substring(0, 2) : "ST");
    const avatarEl = document.getElementById("detail-student-avatar");
    if (avatarEl) avatarEl.textContent = initials.toUpperCase();
    const nameEl = document.getElementById("detail-student-name");
    if (nameEl) nameEl.textContent = student.name;
    const sidEl = document.getElementById("detail-student-id");
    if (sidEl) sidEl.textContent = student.student_id;

    const dueEl = document.getElementById("detail-student-due");
    const paidEl = document.getElementById("detail-student-paid");
    const outEl = document.getElementById("detail-student-outstanding");
    const creditEl = document.getElementById("detail-student-credit");
    if (dueEl) dueEl.textContent = formatRupees(student.total_due);
    if (paidEl) paidEl.textContent = formatRupees(student.total_paid);
    if (outEl) outEl.textContent = formatRupees(student.total_outstanding);
    if (creditEl) creditEl.textContent = formatRupees(student.advance_credit || 0);

    const emailEl = document.getElementById("detail-student-email");
    const phoneEl = document.getElementById("detail-student-phone");
    if (emailEl) emailEl.textContent = student.email || "—";
    if (phoneEl) phoneEl.textContent = student.phone || "—";

    const invTbody = document.getElementById("detail-student-invoices-tbody");
    if (invTbody) {
      invTbody.innerHTML = "";
      const invs = await apiFetch(`/api/invoices?student_id=${encodeURIComponent(student.student_id)}`);
      if (!invs || invs.length === 0) {
        invTbody.innerHTML = `<tr><td colspan="6" class="text-center text-muted py-3">No fee invoices issued yet.</td></tr>`;
      } else {
        invs.forEach((inv) => {
          invTbody.innerHTML += `
            <tr>
              <td class="tabular-nums"><strong>${escapeHtml(inv.invoice_id)}</strong></td>
              <td>${escapeHtml(inv.description)}</td>
              <td class="text-muted tabular-nums">${formatDisplayDate(inv.due_date)}</td>
              <td class="text-center"><span class="badge ${getBadgeClass(inv.status)}">${escapeHtml(inv.status)}</span></td>
              <td class="text-right tabular-nums">${formatRupees(inv.amount_due)}</td>
              <td class="text-right text-success tabular-nums font-semibold">${formatRupees(inv.paid_amount)}</td>
            </tr>
          `;
        });
      }
    }

    if (modalStudentDetail) modalStudentDetail.classList.add("active");
  }

  const closeStudentDetailBtn = document.getElementById("btn-close-student-detail");
  if (closeStudentDetailBtn) closeStudentDetailBtn.onclick = () => modalStudentDetail.classList.remove("active");
  const detailStudentCloseBtn = document.getElementById("btn-detail-student-close");
  if (detailStudentCloseBtn) detailStudentCloseBtn.onclick = () => modalStudentDetail.classList.remove("active");

  // Invoice Detail Modal
  let activeDetailInvoice = null;
  const modalInvoiceDetail = document.getElementById("modal-invoice-detail-overlay");

  async function openInvoiceDetailCard(invoiceId) {
    const invoice = await apiFetch(`/api/invoices/${invoiceId}`);
    activeDetailInvoice = invoice;

    const idEl = document.getElementById("detail-invoice-id");
    const stEl = document.getElementById("detail-invoice-status");
    if (idEl) idEl.textContent = invoice.invoice_id;
    if (stEl) {
      stEl.textContent = invoice.status;
      stEl.className = `badge ${getBadgeClass(invoice.status)}`;
    }

    const dueEl = document.getElementById("detail-invoice-due");
    const paidEl = document.getElementById("detail-invoice-paid");
    const outEl = document.getElementById("detail-invoice-outstanding");
    if (dueEl) dueEl.textContent = formatRupees(invoice.amount_due);
    if (paidEl) paidEl.textContent = formatRupees(invoice.paid_amount);
    if (outEl) outEl.textContent = formatRupees(invoice.outstanding_amount);

    const descEl = document.getElementById("detail-invoice-desc");
    const dateEl = document.getElementById("detail-invoice-date");
    const sidEl = document.getElementById("detail-invoice-student-id");
    const snameEl = document.getElementById("detail-invoice-student-name");
    if (descEl) descEl.textContent = invoice.description;
    if (dateEl) dateEl.textContent = formatDisplayDate(invoice.due_date);
    if (sidEl) sidEl.textContent = invoice.student_id;
    if (snameEl) snameEl.textContent = invoice.student_name || "—";

    // Itemized fee heads
    const headsTbody = document.getElementById("detail-invoice-fee-heads-tbody");
    if (headsTbody) {
      headsTbody.innerHTML = "";
      if (invoice.fee_items && invoice.fee_items.length > 0) {
        invoice.fee_items.forEach((item) => {
          const applied = item.amount_applied || 0;
          const isSatisfied = applied >= item.amount;
          headsTbody.innerHTML += `
            <tr>
              <td><strong>${escapeHtml(item.fee_head)}</strong></td>
              <td class="text-center tabular-nums">Priority ${item.priority}</td>
              <td class="text-right tabular-nums">${formatRupees(item.amount)}</td>
              <td class="text-right text-success tabular-nums font-semibold">${formatRupees(applied)}</td>
              <td class="text-center"><span class="badge ${isSatisfied ? 'badge-paid' : (applied > 0 ? 'badge-partial' : 'badge-neutral')}">${isSatisfied ? 'Satisfied' : (applied > 0 ? 'Partial' : 'Pending')}</span></td>
            </tr>
          `;
        });
      } else {
        headsTbody.innerHTML = `<tr><td colspan="5" class="text-center text-muted py-3">No itemized fee heads configured.</td></tr>`;
      }
    }

    if (modalInvoiceDetail) modalInvoiceDetail.classList.add("active");
  }

  const closeInvoiceDetailBtn = document.getElementById("btn-close-invoice-detail");
  if (closeInvoiceDetailBtn) closeInvoiceDetailBtn.onclick = () => modalInvoiceDetail.classList.remove("active");
  const detailInvoiceCloseBtn = document.getElementById("btn-detail-invoice-close");
  if (detailInvoiceCloseBtn) detailInvoiceCloseBtn.onclick = () => modalInvoiceDetail.classList.remove("active");

  // =========================================================================
  // PAGE 3: PAYMENTS (Fix Section 9 Bug: never overpaid on review/unmatched)
  // =========================================================================

  async function fetchPayments() {
    const qInp = document.getElementById("payments-search-input");
    const statusInp = document.getElementById("payments-status-filter");
    const methodInp = document.getElementById("payments-method-filter");

    const q = qInp ? qInp.value.trim() : "";
    const statusVal = statusInp ? statusInp.value.trim() : "";
    const methodVal = methodInp ? methodInp.value.trim() : "";

    let url = `/api/payments?q=${encodeURIComponent(q)}`;
    if (statusVal) url += `&match_status=${encodeURIComponent(statusVal)}`;
    if (methodVal) url += `&method=${encodeURIComponent(methodVal)}`;

    const payments = await apiFetch(url);
    state.payments = payments;

    const countEl = document.getElementById("payments-count-text");
    if (countEl) countEl.textContent = `${payments.length} ${payments.length === 1 ? 'payment' : 'payments'}`;

    renderPaymentsTable(payments);
  }

  function renderPaymentsTable(payments) {
    const tbody = document.getElementById("payments-tbody");
    if (!tbody) return;
    tbody.innerHTML = "";

    if (!payments || payments.length === 0) {
      tbody.innerHTML = `
        <tr>
          <td colspan="9" class="text-center py-4">
            <div class="empty-state-box" style="padding:24px;">
              <span class="empty-state-title">No payment records found.</span>
              <span class="empty-state-sub">Upload a bank feed or load demo data to view payments.</span>
              <button class="btn btn-primary btn-sm mt-3 btn-load-demo-data">Load demo data</button>
            </div>
          </td>
        </tr>
      `;
      const btn = tbody.querySelector(".btn-load-demo-data");
      if (btn) btn.onclick = triggerLoadDemo;
      return;
    }

    payments.forEach((p) => {
      // SECTION 9 FIX: Only mark as Overpaid if match_status is strictly "Overpaid"
      const isOverpaid = (p.match_status === "Overpaid");
      let excess = 0;
      if (isOverpaid) {
        const applied = (p.allocations || []).reduce((sum, a) => sum + (a.amount_applied || 0), 0);
        excess = Math.max(0, (p.amount || 0) - applied);
      }

      const tr = document.createElement("tr");
      tr.className = "clickable-row";
      tr.tabIndex = 0;
      tr.innerHTML = `
        <td class="tabular-nums monospace-font"><strong>${escapeHtml(p.txn_ref || `PMT-${p.id}`)}</strong></td>
        <td class="text-muted tabular-nums">${formatDisplayDate(p.payment_date)}</td>
        <td>
          <div class="font-semibold">${escapeHtml(p.payer_name || '—')}</div>
          <span class="text-muted text-sm tabular-nums">${p.student_ref ? `ID: ${escapeHtml(p.student_ref)}` : '<span class="text-subtle">No student ID</span>'}</span>
        </td>
        <td><span class="badge badge-neutral">${escapeHtml(p.method === 'OTHER' ? 'Other' : (p.method || 'Other'))}</span></td>
        <td class="text-right tabular-nums">
          <div class="font-semibold">${formatRupees(p.amount)}</div>
          ${isOverpaid && excess > 0 ? `<div class="amount-sub text-muted">${formatRupees(excess)} excess</div>` : ''}
        </td>
        <td class="text-center"><span class="badge ${getBadgeClass(p.match_status)}">${escapeHtml(p.match_status)}</span></td>
        <td class="text-center">${renderConfidenceMeter(p.confidence_score)}</td>
        <td class="text-sm text-muted">${escapeHtml(formatMatchReason(p.match_reason))}</td>
        <td class="text-right">
          <button class="btn btn-sm btn-outline-secondary btn-view-payment" data-id="${p.id}">View card</button>
        </td>
      `;

      tr.addEventListener("click", (e) => {
        if (e.target.closest("button")) return;
        openPaymentDetailCard(p.id);
      });
      tr.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          openPaymentDetailCard(p.id);
        }
      });
      const viewBtn = tr.querySelector(".btn-view-payment");
      if (viewBtn) viewBtn.onclick = () => openPaymentDetailCard(p.id);

      tbody.appendChild(tr);
    });
  }

  const pmtSearchInp = document.getElementById("payments-search-input");
  if (pmtSearchInp) pmtSearchInp.addEventListener("input", debounce(fetchPayments, 250));
  const pmtStatusFilter = document.getElementById("payments-status-filter");
  if (pmtStatusFilter) pmtStatusFilter.addEventListener("change", fetchPayments);
  const pmtMethodFilter = document.getElementById("payments-method-filter");
  if (pmtMethodFilter) pmtMethodFilter.addEventListener("change", fetchPayments);

  // Payment Detail Modal
  const modalPaymentDetail = document.getElementById("modal-payment-detail-overlay");
  async function openPaymentDetailCard(paymentId) {
    const pmt = await apiFetch(`/api/payments/${paymentId}`);
    state.selectedPayment = pmt;

    const titleEl = document.getElementById("payment-card-title");
    const statusEl = document.getElementById("payment-card-status-badge");
    if (titleEl) titleEl.textContent = `Payment #${pmt.id}`;
    if (statusEl) {
      statusEl.textContent = pmt.match_status;
      statusEl.className = `badge ${getBadgeClass(pmt.match_status)}`;
    }

    const bodyEl = document.getElementById("payment-card-body");
    if (bodyEl) {
      const isOverpaid = (pmt.match_status === "Overpaid");
      const appliedTotal = (pmt.allocations || []).reduce((sum, a) => sum + (a.amount_applied || 0), 0);
      const excess = isOverpaid ? Math.max(0, (pmt.amount || 0) - appliedTotal) : 0;

      bodyEl.innerHTML = `
        <div class="metrics-strip mb-4" style="display:grid;grid-template-columns:repeat(3, 1fr);gap:12px;">
          <div class="card p-3">
            <span class="text-muted text-xs">Payment amount</span>
            <div class="kpi-value font-semibold">${formatRupees(pmt.amount)}</div>
          </div>
          <div class="card p-3">
            <span class="text-muted text-xs">Amount applied</span>
            <div class="kpi-value text-success font-semibold">${formatRupees(appliedTotal)}</div>
          </div>
          <div class="card p-3">
            <span class="text-muted text-xs">Decision confidence</span>
            <div class="kpi-value font-semibold">${pmt.confidence_score}%</div>
          </div>
        </div>

        ${isOverpaid && excess > 0 ? `
          <div class="card p-3 mb-4" style="background:var(--reason-overpaid-bg);border-color:var(--reason-overpaid-border);">
            <div style="font-weight:600;color:var(--reason-overpaid-text);">Excess payment balance</div>
            <div class="amount-val" style="color:var(--reason-overpaid-text);">${formatRupees(excess)} excess above obligation</div>
          </div>
        ` : ''}

        <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:16px;">
          <div><span class="text-muted text-xs">Transaction ID</span><div class="monospace-font">${escapeHtml(pmt.txn_ref || `PMT-${pmt.id}`)}</div></div>
          <div><span class="text-muted text-xs">Payer name</span><div>${escapeHtml(pmt.payer_name || '—')}</div></div>
          <div><span class="text-muted text-xs">Payment date</span><div>${formatDisplayDate(pmt.payment_date)}</div></div>
          <div><span class="text-muted text-xs">Method</span><div>${escapeHtml(pmt.method || 'OTHER')}</div></div>
          <div><span class="text-muted text-xs">Student ID reference</span><div>${escapeHtml(pmt.student_ref || 'None')}</div></div>
          <div><span class="text-muted text-xs">Matched student</span><div>${escapeHtml(pmt.matched_student_name || pmt.matched_student_id || 'Unmatched')}</div></div>
        </div>
      `;
    }

    if (modalPaymentDetail) modalPaymentDetail.classList.add("active");
  }

  const closePmtCardBtn = document.getElementById("btn-close-payment-card");
  if (closePmtCardBtn) closePmtCardBtn.onclick = () => modalPaymentDetail.classList.remove("active");
  const closePmtCardFooterBtn = document.getElementById("btn-close-payment-card-footer");
  if (closePmtCardFooterBtn) closePmtCardFooterBtn.onclick = () => modalPaymentDetail.classList.remove("active");

  // =========================================================================
  // PAGE 4: RECONCILIATION CASCADE LEDGER
  // =========================================================================

  async function fetchReconciliationData() {
    const payments = await apiFetch("/api/payments?page=1&page_size=100");
    const tbody = document.getElementById("reconciliation-tbody");
    if (!tbody) return;
    tbody.innerHTML = "";

    // Update reconciliation summary counts
    let matched = 0, partial = 0, review = 0, duplicate = 0, overpaid = 0, unmatched = 0, invalid = 0;
    payments.forEach((p) => {
      switch (p.match_status) {
        case "Matched": matched++; break;
        case "Partial": partial++; break;
        case "Review": review++; break;
        case "Duplicate": duplicate++; break;
        case "Overpaid": overpaid++; break;
        case "Unmatched": unmatched++; break;
        case "Invalid": invalid++; break;
      }
    });

    const cMatched = document.getElementById("recon-count-matched");
    const cPartial = document.getElementById("recon-count-partial");
    const cReview = document.getElementById("recon-count-review");
    const cDuplicate = document.getElementById("recon-count-duplicate");
    const cOverpaid = document.getElementById("recon-count-overpaid");
    const cUnmatched = document.getElementById("recon-count-unmatched");
    const cInvalid = document.getElementById("recon-count-invalid");

    if (cMatched) cMatched.textContent = matched;
    if (cPartial) cPartial.textContent = partial;
    if (cReview) cReview.textContent = review;
    if (cDuplicate) cDuplicate.textContent = duplicate;
    if (cOverpaid) cOverpaid.textContent = overpaid;
    if (cUnmatched) cUnmatched.textContent = unmatched;
    if (cInvalid) cInvalid.textContent = invalid;

    if (payments.length === 0) {
      tbody.innerHTML = `
        <tr>
          <td colspan="8" class="text-center py-4">
            <div class="empty-state-box" style="padding:24px;">
              <span class="empty-state-title">No reconciliation records found.</span>
              <span class="empty-state-sub">Load demo data to run the automated cascade rule engine.</span>
              <button class="btn btn-primary btn-sm mt-3 btn-load-demo-data">Load demo data</button>
            </div>
          </td>
        </tr>
      `;
      const btn = tbody.querySelector(".btn-load-demo-data");
      if (btn) btn.onclick = triggerLoadDemo;
      return;
    }

    payments.forEach((p) => {
      const tr = document.createElement("tr");
      tr.className = "clickable-row";
      tr.tabIndex = 0;
      tr.innerHTML = `
        <td class="tabular-nums monospace-font"><strong>${escapeHtml(p.txn_ref || `PMT-${p.id}`)}</strong></td>
        <td>${escapeHtml(p.payer_name || '—')}</td>
        <td>${escapeHtml(p.student_ref || p.invoice_ref || '—')}</td>
        <td class="text-right tabular-nums font-semibold">${formatRupees(p.amount)}</td>
        <td class="text-center"><span class="badge ${getBadgeClass(p.match_status)}">${escapeHtml(p.match_status)}</span></td>
        <td class="text-center">${renderConfidenceMeter(p.confidence_score)}</td>
        <td class="text-sm text-muted">${escapeHtml(formatMatchReason(p.match_reason))}</td>
        <td class="text-right">
          <button class="btn btn-sm btn-outline-secondary btn-view-recon" data-id="${p.id}">View details</button>
        </td>
      `;

      tr.addEventListener("click", (e) => {
        if (e.target.closest("button")) return;
        openPaymentDetailCard(p.id);
      });
      tr.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          openPaymentDetailCard(p.id);
        }
      });
      const viewBtn = tr.querySelector(".btn-view-recon");
      if (viewBtn) viewBtn.onclick = () => openPaymentDetailCard(p.id);

      tbody.appendChild(tr);
    });
  }

  // =========================================================================
  // PAGE 5: EXCEPTIONS (Full Section 3, 4, 5, 6, 7 Implementation)
  // =========================================================================

  const tabOpenExceptions = document.getElementById("tab-btn-open-exceptions");
  const tabResolvedExceptions = document.getElementById("tab-btn-resolved-exceptions");
  const exceptionsSearchInput = document.getElementById("exceptions-search-input");
  const chipsRow = document.getElementById("exception-chips-row");

  if (tabOpenExceptions && tabResolvedExceptions) {
    tabOpenExceptions.addEventListener("click", () => {
      state.resolvedFilter = false;
      tabOpenExceptions.classList.add("active");
      tabResolvedExceptions.classList.remove("active");
      fetchExceptions();
    });

    tabResolvedExceptions.addEventListener("click", () => {
      state.resolvedFilter = true;
      tabResolvedExceptions.classList.add("active");
      tabOpenExceptions.classList.remove("active");
      fetchExceptions();
    });
  }

  // Chip buttons click handlers
  if (chipsRow) {
    chipsRow.querySelectorAll(".chip").forEach((chip) => {
      chip.addEventListener("click", () => {
        chipsRow.querySelectorAll(".chip").forEach(c => {
          c.classList.remove("active");
          c.setAttribute("aria-selected", "false");
        });
        chip.classList.add("active");
        chip.setAttribute("aria-selected", "true");
        state.exceptionReasonFilter = chip.dataset.reason || "";
        filterAndRenderExceptions();
      });
    });
  }

  if (exceptionsSearchInput) {
    exceptionsSearchInput.addEventListener("input", debounce(() => {
      state.exceptionSearchQuery = exceptionsSearchInput.value.trim();
      filterAndRenderExceptions();
    }, 200));
  }

  // Table header sorting
  const thReason = document.querySelector(".th-reason.sortable");
  const thAmount = document.querySelector(".th-amount.sortable");
  const arrowReason = document.getElementById("sort-arrow-reason");
  const arrowAmount = document.getElementById("sort-arrow-amount");

  if (thReason) {
    thReason.addEventListener("click", () => {
      if (state.exceptionSortField === "reason") {
        state.exceptionSortDirection = state.exceptionSortDirection === "asc" ? "desc" : "asc";
      } else {
        state.exceptionSortField = "reason";
        state.exceptionSortDirection = "asc";
      }
      updateSortArrows();
      filterAndRenderExceptions();
    });
    thReason.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        thReason.click();
      }
    });
  }

  if (thAmount) {
    thAmount.addEventListener("click", () => {
      if (state.exceptionSortField === "amount") {
        state.exceptionSortDirection = state.exceptionSortDirection === "asc" ? "desc" : "asc";
      } else {
        state.exceptionSortField = "amount";
        state.exceptionSortDirection = "asc";
      }
      updateSortArrows();
      filterAndRenderExceptions();
    });
    thAmount.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        thAmount.click();
      }
    });
  }

  function updateSortArrows() {
    if (arrowReason) arrowReason.textContent = state.exceptionSortField === "reason" ? (state.exceptionSortDirection === "asc" ? "▲" : "▼") : "";
    if (arrowAmount) arrowAmount.textContent = state.exceptionSortField === "amount" ? (state.exceptionSortDirection === "asc" ? "▲" : "▼") : "";
  }

  async function fetchExceptions() {
    // Show 5 skeleton rows while loading
    renderSkeletonExceptions();

    const allExceptions = await apiFetch(`/api/exceptions?resolved=${state.resolvedFilter}`);
    state.allExceptionsForTab = allExceptions;

    // Update chip counts
    updateChipCounts(allExceptions);

    // If on open exceptions tab, update sidebar badge too
    if (!state.resolvedFilter) {
      updateSidebarExceptionsBadge(allExceptions.length);
    }

    filterAndRenderExceptions();
  }

  function updateChipCounts(allExceptions) {
    const counts = {
      all: allExceptions.length,
      ambiguous: 0,
      partial: 0,
      duplicate: 0,
      overpaid: 0,
      unmatched: 0,
      invalid: 0,
    };

    allExceptions.forEach((e) => {
      const code = (e.reason_code || "").toUpperCase();
      switch (code) {
        case "AMBIGUOUS_MATCH": counts.ambiguous++; break;
        case "PARTIAL": counts.partial++; break;
        case "DUPLICATE": counts.duplicate++; break;
        case "OVERPAID": counts.overpaid++; break;
        case "UNMATCHED": counts.unmatched++; break;
        case "INVALID_ROW": counts.invalid++; break;
      }
    });

    const setChip = (id, cnt) => {
      const el = document.getElementById(id);
      if (el) el.textContent = cnt;
      const btn = el ? el.closest(".chip") : null;
      if (btn) btn.classList.toggle("count-zero", cnt === 0);
    };

    setChip("chip-count-all", counts.all);
    setChip("chip-count-ambiguous", counts.ambiguous);
    setChip("chip-count-partial", counts.partial);
    setChip("chip-count-duplicate", counts.duplicate);
    setChip("chip-count-overpaid", counts.overpaid);
    setChip("chip-count-unmatched", counts.unmatched);
    setChip("chip-count-invalid", counts.invalid);
  }

  function renderSkeletonExceptions() {
    const tbody = document.getElementById("exceptions-tbody");
    if (!tbody) return;
    tbody.innerHTML = "";
    for (let i = 0; i < 5; i++) {
      const tr = document.createElement("tr");
      tr.className = "skeleton-row";
      tr.innerHTML = `
        <td style="width:14%;"><div class="skeleton-cell" style="width:90px;height:24px;border-radius:12px;"></div></td>
        <td style="width:24%;"><div class="skeleton-cell" style="width:140px;height:16px;margin-bottom:6px;"></div><div class="skeleton-cell" style="width:100px;height:12px;"></div></td>
        <td style="width:13%;text-align:right;"><div class="skeleton-cell" style="width:70px;height:16px;margin-left:auto;"></div></td>
        <td style="width:33%;"><div class="skeleton-cell" style="width:200px;height:14px;margin-bottom:6px;"></div><div class="skeleton-cell" style="width:150px;height:12px;"></div></td>
        <td style="width:16%;text-align:right;"><div class="skeleton-cell" style="width:110px;height:32px;margin-left:auto;border-radius:6px;"></div></td>
      `;
      tbody.appendChild(tr);
    }
  }

  function filterAndRenderExceptions() {
    const reasonFilter = state.exceptionReasonFilter;
    const q = state.exceptionSearchQuery.toLowerCase();
    let list = [...state.allExceptionsForTab];

    // Filter by reason chip
    if (reasonFilter) {
      list = list.filter(e => (e.reason_code || "").toUpperCase() === reasonFilter.toUpperCase());
    }

    const totalBeforeSearch = list.length;

    // Filter by search query
    if (q) {
      list = list.filter(e => {
        const pmt = e.payment || {};
        const detail = (e.detail || "").toLowerCase();
        const txn = (pmt.txn_ref || `PMT-${pmt.id || ''}`).toLowerCase();
        const sref = (pmt.student_ref || "").toLowerCase();
        const payer = (pmt.payer_name || "").toLowerCase();
        const sid = (pmt.matched_student_id || "").toLowerCase();
        const sname = (pmt.matched_student_name || "").toLowerCase();
        return detail.includes(q) || txn.includes(q) || sref.includes(q) || payer.includes(q) || sid.includes(q) || sname.includes(q);
      });
    }

    // Update result count: ONLY shown when search query is active
    const resultCountEl = document.getElementById("exceptions-result-count");
    if (resultCountEl) {
      if (q) {
        resultCountEl.textContent = `Showing ${list.length} of ${totalBeforeSearch}`;
        resultCountEl.style.display = "inline-block";
      } else {
        resultCountEl.style.display = "none";
      }
    }

    // Sorting
    if (state.exceptionSortField === "amount") {
      list.sort((a, b) => {
        const amtA = (a.payment && a.payment.amount) ? a.payment.amount : 0;
        const amtB = (b.payment && b.payment.amount) ? b.payment.amount : 0;
        return state.exceptionSortDirection === "asc" ? amtA - amtB : amtB - amtA;
      });
    } else if (state.exceptionSortField === "reason") {
      list.sort((a, b) => {
        const rA = humanizeReason(a.reason_code);
        const rB = humanizeReason(b.reason_code);
        return state.exceptionSortDirection === "asc" ? rA.localeCompare(rB) : rB.localeCompare(rA);
      });
    } else {
      // Default Sort per Section 4: Invalid (1), Unmatched (2), Ambiguous (3), Duplicate (4), Overpaid (5), Partial (6), then oldest first
      list.sort((a, b) => {
        const prioA = (REASON_CONFIG[a.reason_code] && REASON_CONFIG[a.reason_code].sortPriority) || 99;
        const prioB = (REASON_CONFIG[b.reason_code] && REASON_CONFIG[b.reason_code].sortPriority) || 99;
        if (prioA !== prioB) return prioA - prioB;
        return (a.id || 0) - (b.id || 0);
      });
    }

    state.exceptions = list;
    renderExceptionsTable(list);
  }

  function renderExceptionsTable(exceptions) {
    const tbody = document.getElementById("exceptions-tbody");
    if (!tbody) return;
    tbody.innerHTML = "";

    if (exceptions.length === 0) {
      const activeReason = state.exceptionReasonFilter;
      let emptyTitle = "All payments are reconciled.";
      let emptySub = "No outstanding exceptions require action.";

      if (activeReason) {
        const cfg = REASON_CONFIG[activeReason] || {};
        const label = (cfg.label || activeReason).toLowerCase();
        emptyTitle = `No ${label} exceptions`;
        emptySub = `No pending ${label} payments in queue.`;
      } else if (state.resolvedFilter) {
        emptyTitle = "No resolved exceptions recorded";
        emptySub = "Exceptions resolved by operators will appear here.";
      }

      tbody.innerHTML = `
        <tr>
          <td colspan="5" class="text-center py-5">
            <div class="empty-state-box">
              <svg class="empty-state-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="12" r="10"/><path d="m9 12 2 2 4-4"/></svg>
              <h4 class="empty-state-title">${escapeHtml(emptyTitle)}</h4>
              <p class="empty-state-sub">${escapeHtml(emptySub)}</p>
              ${(!state.resolvedFilter && state.allExceptionsForTab.length === 0 && (!state.payments || state.payments.length === 0)) ? `
                <button class="btn btn-primary btn-sm mt-3 btn-load-demo-data">Load demo data</button>
              ` : ''}
            </div>
          </td>
        </tr>
      `;
      const btn = tbody.querySelector(".btn-load-demo-data");
      if (btn) btn.onclick = triggerLoadDemo;
      return;
    }

    exceptions.forEach((e, index) => {
      const pmt = e.payment || {};
      const applied = (pmt.allocations || []).reduce((sum, a) => sum + (a.amount_applied || 0), 0);

      // Section 9 Bug Fix: ONLY true for reason OVERPAID or payment status Overpaid
      const isOverpaid = (e.reason_code === "OVERPAID" || pmt.match_status === "Overpaid");
      const excess = isOverpaid ? Math.max(0, (pmt.amount || 0) - applied) : 0;

      const cfg = REASON_CONFIG[e.reason_code] || {
        label: humanizeReason(e.reason_code),
        colorClass: "reason-neutral",
        iconSvg: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/></svg>`
      };

      const relativeTime = getRelativeTimeString(pmt.payment_date || e.created_at);

      // Candidate student info for Ambiguous
      const candidateName = pmt.matched_student_name || pmt.matched_student_id || "suggested student";
      const candidateId = pmt.matched_student_id || "";

      // Amount Column formatting
      let amtMain = "";
      let amtSub = "";
      if (e.reason_code === "INVALID_ROW" && (!pmt.amount || pmt.amount <= 0)) {
        amtMain = "—";
        amtSub = "Missing";
      } else if (isOverpaid) {
        amtMain = formatRupees(pmt.amount);
        amtSub = `${formatRupees(excess)} excess`;
      } else if (e.reason_code === "PARTIAL") {
        amtMain = formatRupees(pmt.amount);
        // Extract or estimate remaining balance
        const remMatch = (e.detail || "").match(/Remaining balance on [^:]+:\s*(₹[\d,]+\.?\d*)/i);
        const remStr = remMatch ? remMatch[1] : (applied > 0 ? "Remaining due" : "Balance due");
        amtSub = `${remStr} remaining`;
      } else {
        amtMain = formatRupees(pmt.amount);
        amtSub = "Not applied";
      }

      // Issue line 1 and line 2 formatting
      let issueLine1 = "";
      let issueLine2Text = "";
      const arrowIcon = `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M5 12h14M12 5l7 7-7 7"/></svg>`;

      if (e.reason_code === "INVALID_ROW") {
        issueLine1 = (pmt.amount <= 0 || !pmt.amount) ? "Amount is missing or invalid" : "Unparsed payment format in record";
        issueLine2Text = "Fix the row, then re-enter it";
      } else if (isOverpaid) {
        issueLine1 = `Paid ${formatRupees(excess)} more than ${pmt.matched_invoice_id || 'invoice obligation'}`;
        issueLine2Text = "Keep the excess as credit or dismiss";
      } else if (e.reason_code === "AMBIGUOUS_MATCH") {
        const quoted = pmt.student_ref || pmt.payer_name || "Reference";
        issueLine1 = `'${escapeHtml(quoted)}' looks like ${escapeHtml(candidateName)} (${escapeHtml(candidateId)}) ${renderConfidenceMeter(pmt.confidence_score)}`;
        issueLine2Text = "Confirm this student or pick another";
      } else if (e.reason_code === "PARTIAL") {
        issueLine1 = `${formatRupees(pmt.amount)} paid on ${pmt.matched_invoice_id || 'invoice obligation'}`;
        issueLine2Text = "Wait for the balance or accept as partial";
      } else if (e.reason_code === "DUPLICATE") {
        issueLine1 = `Same transaction ID as ${escapeHtml(pmt.txn_ref || 'prior entry')}`;
        issueLine2Text = "Confirm it is a repeat";
      } else if (e.reason_code === "UNMATCHED") {
        issueLine1 = `No student found for ID '${escapeHtml(pmt.student_ref || 'unknown')}'`;
        issueLine2Text = "Assign to a student";
      } else {
        issueLine1 = escapeHtml(e.detail || "Action required");
        issueLine2Text = "Review and resolve";
      }

      // Actions Column: Single filled Indigo button per row + "⋯" Menu
      let primaryAction = "dismiss";
      let primaryLabel = "Dismiss";
      let hasMoreMenu = true;
      let menuItems = [];

      if (e.resolved) {
        primaryAction = "view_details";
        primaryLabel = "View details";
        hasMoreMenu = false;
      } else if (e.reason_code === "AMBIGUOUS_MATCH") {
        primaryAction = "assign_to_student";
        primaryLabel = `Confirm ${candidateName}`;
        menuItems = [
          { action: "choose_another_student", label: "Choose another student" },
          { action: "view_details", label: "View details" },
          { action: "dismiss", label: "Dismiss" },
        ];
      } else if (e.reason_code === "UNMATCHED") {
        primaryAction = "assign_to_student";
        primaryLabel = "Assign to student";
        menuItems = [
          { action: "view_details", label: "View details" },
          { action: "dismiss", label: "Dismiss" },
        ];
      } else if (e.reason_code === "PARTIAL") {
        primaryAction = "accept_partial";
        primaryLabel = "Accept partial";
        menuItems = [
          { action: "view_details", label: "View details" },
          { action: "dismiss", label: "Dismiss" },
        ];
      } else if (e.reason_code === "DUPLICATE") {
        primaryAction = "mark_duplicate";
        primaryLabel = "Confirm duplicate";
        menuItems = [
          { action: "view_details", label: "View details" },
          { action: "dismiss", label: "Dismiss" },
        ];
      } else if (e.reason_code === "OVERPAID") {
        primaryAction = "roll_advance_credit";
        primaryLabel = "Keep as credit";
        menuItems = [
          { action: "view_details", label: "View details" },
          { action: "dismiss", label: "Dismiss" },
        ];
      } else if (e.reason_code === "INVALID_ROW") {
        primaryAction = "reenter_payment";
        primaryLabel = "Re-enter payment";
        menuItems = [
          { action: "view_details", label: "View details" },
          { action: "dismiss", label: "Dismiss" },
        ];
      }

      const tr = document.createElement("tr");
      tr.className = "clickable-row";
      tr.id = `exc-row-${e.id}`;
      tr.tabIndex = 0;
      tr.dataset.id = e.id;
      tr.dataset.index = index;

      tr.innerHTML = `
        <td class="td-reason" style="width: 14%;">
          <span class="reason-pill ${cfg.colorClass}">
            ${cfg.iconSvg}
            <span>${escapeHtml(cfg.label)}</span>
          </span>
          <div class="sub-muted-line tabular-nums">Payment #${pmt.id || e.payment_id} · ${escapeHtml(relativeTime)}</div>
        </td>
        <td class="td-payment" style="width: 24%;">
          <div class="payment-payer font-semibold">${escapeHtml(pmt.payer_name || 'Unknown payer')}</div>
          <div class="payment-txnid monospace-font text-muted">${escapeHtml(pmt.txn_ref || `PMT-${pmt.id}`)}</div>
          <div class="payment-meta text-muted">
            <span class="nowrap-item tabular-nums">${pmt.student_ref ? `ID ${escapeHtml(pmt.student_ref)}` : '<span style="font-style:italic;">No student ID</span>'}</span> ·
            <span class="nowrap-item">${escapeHtml(pmt.method || 'OTHER')}</span> ·
            <span class="nowrap-item tabular-nums">${escapeHtml(formatDisplayDate(pmt.payment_date))}</span>
          </div>
        </td>
        <td class="td-amount text-right" style="width: 13%;">
          <span class="amount-val tabular-nums">${amtMain}</span>
          <span class="amount-sub tabular-nums text-muted">${amtSub}</span>
        </td>
        <td class="td-issue" style="width: 33%;">
          <div class="issue-text-wrap">
            <div class="issue-line-1">${issueLine1}</div>
            <div class="issue-line-2">${arrowIcon} <span>${escapeHtml(issueLine2Text)}</span></div>
          </div>
        </td>
        <td class="td-actions text-right" style="width: 16%;">
          <div class="row-actions-group">
            <button type="button" class="btn btn-sm btn-primary btn-row-primary" data-id="${e.id}" data-action="${primaryAction}">${escapeHtml(primaryLabel)}</button>
            ${hasMoreMenu ? `
              <div class="more-menu-wrapper">
                <button type="button" class="btn-more-actions" data-id="${e.id}" aria-label="More actions" title="More actions">
                  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="12" cy="12" r="1.5"/><circle cx="19" cy="12" r="1.5"/><circle cx="5" cy="12" r="1.5"/></svg>
                </button>
                <div class="more-menu-dropdown" style="display:none;" role="menu">
                  ${menuItems.map(m => `
                    <button type="button" class="menu-item ${m.action === 'dismiss' ? 'neutral-dismiss' : ''}" data-id="${e.id}" data-action="${m.action}" role="menuitem">
                      ${escapeHtml(m.label)}
                    </button>
                  `).join('')}
                </div>
              </div>
            ` : ''}
          </div>
        </td>
      `;

      // Entire row is clickable and keyboard-focusable (Enter opens details drawer)
      tr.addEventListener("click", (evt) => {
        if (evt.target.closest("button") || evt.target.closest(".more-menu-dropdown")) return;
        openExceptionDrawer(e.id);
      });

      tr.addEventListener("keydown", (evt) => {
        if (evt.key === "Enter" || evt.key === " ") {
          if (evt.target === tr) {
            evt.preventDefault();
            openExceptionDrawer(e.id);
          }
        }
      });

      // Primary Button Handler
      const primBtn = tr.querySelector(".btn-row-primary");
      if (primBtn) {
        primBtn.addEventListener("click", (evt) => {
          evt.stopPropagation();
          handleExceptionAction(e, primaryAction);
        });
      }

      // "⋯" Menu button toggle
      const moreBtn = tr.querySelector(".btn-more-actions");
      const dropdown = tr.querySelector(".more-menu-dropdown");
      if (moreBtn && dropdown) {
        moreBtn.addEventListener("click", (evt) => {
          evt.stopPropagation();
          // Close other open menus
          document.querySelectorAll(".more-menu-dropdown").forEach(d => {
            if (d !== dropdown) d.style.display = "none";
          });
          dropdown.style.display = dropdown.style.display === "none" ? "flex" : "none";
        });

        dropdown.querySelectorAll(".menu-item").forEach((item) => {
          item.addEventListener("click", (evt) => {
            evt.stopPropagation();
            dropdown.style.display = "none";
            const action = item.dataset.action;
            if (action === "view_details") {
              openExceptionDrawer(e.id);
            } else if (action === "choose_another_student") {
              openResolveDialog(e, "assign_to_student", true);
            } else {
              handleExceptionAction(e, action);
            }
          });
        });
      }

      tbody.appendChild(tr);
    });
  }

  // Close menus on outside click or escape
  document.addEventListener("click", () => {
    document.querySelectorAll(".more-menu-dropdown").forEach(d => d.style.display = "none");
    const demoPopover = document.getElementById("demo-popover-menu");
    if (demoPopover) demoPopover.style.display = "none";
    const demoTrigger = document.getElementById("btn-sidebar-demo-menu");
    if (demoTrigger) demoTrigger.setAttribute("aria-expanded", "false");
  });

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      closeAllPopoversAndDrawers();
    }
  });

  function closeAllPopoversAndDrawers() {
    document.querySelectorAll(".more-menu-dropdown").forEach(d => d.style.display = "none");
    const demoPopover = document.getElementById("demo-popover-menu");
    if (demoPopover) demoPopover.style.display = "none";
    const demoTrigger = document.getElementById("btn-sidebar-demo-menu");
    if (demoTrigger) demoTrigger.setAttribute("aria-expanded", "false");

    const excDrawer = document.getElementById("exception-drawer");
    const excDrawerOverlay = document.getElementById("exception-drawer-overlay");
    if (excDrawer) excDrawer.classList.remove("active");
    if (excDrawerOverlay) excDrawerOverlay.classList.remove("active");

    const pmtDrawer = document.getElementById("payment-drawer");
    const pmtDrawerOverlay = document.getElementById("payment-drawer-overlay");
    if (pmtDrawer) pmtDrawer.classList.remove("active");
    if (pmtDrawerOverlay) pmtDrawerOverlay.classList.remove("active");
  }

  // =========================================================================
  // EXCEPTION ACTION DISPATCHER & CONFIRMATION DIALOG (Section 5 & 6)
  // =========================================================================

  function handleExceptionAction(exc, action) {
    if (action === "view_details") {
      openExceptionDrawer(exc.id);
      return;
    }
    if (action === "reenter_payment") {
      // Open manual payment entry modal prefilled with this row's values
      openManualPaymentModalPrefilled(exc);
      return;
    }
    // Open confirmation preview dialog
    openResolveDialog(exc, action);
  }

  function openManualPaymentModalPrefilled(exc) {
    const pmt = exc.payment || {};
    const modalPmt = document.getElementById("modal-payment-overlay");
    if (!modalPmt) return;

    const inpTxn = document.getElementById("inp-pmt-txn");
    const inpMethod = document.getElementById("inp-pmt-method");
    const inpStudent = document.getElementById("inp-pmt-student");
    const inpInvoice = document.getElementById("inp-pmt-invoice");
    const inpPayer = document.getElementById("inp-pmt-payer");
    const inpAmount = document.getElementById("inp-pmt-amount");
    const inpDate = document.getElementById("inp-pmt-date");

    if (inpTxn) inpTxn.value = pmt.txn_ref || "";
    if (inpMethod) inpMethod.value = pmt.method || "UPI";
    if (inpStudent) inpStudent.value = pmt.student_ref || "";
    if (inpInvoice) inpInvoice.value = pmt.invoice_ref || "";
    if (inpPayer) inpPayer.value = pmt.payer_name || "";
    if (inpAmount) inpAmount.value = (pmt.amount && pmt.amount > 0) ? (pmt.amount / 100.0).toFixed(2) : "";
    if (inpDate) inpDate.value = pmt.payment_date || new Date().toISOString().split("T")[0];

    modalPmt.classList.add("active");
  }

  // Exception Resolution Confirmation Dialog
  const modalResolve = document.getElementById("modal-resolve-overlay");
  const formResolve = document.getElementById("form-resolve-exception");

  async function openResolveDialog(exc, actionType, forcePicker = false) {
    state.activeResolvingRow = document.getElementById(`exc-row-${exc.id}`);

    const idInput = document.getElementById("resolve-exception-id");
    const actInput = document.getElementById("resolve-action-type");
    const titleEl = document.getElementById("modal-resolve-title");
    const previewEl = document.getElementById("resolve-preview-text");
    const pickerGroup = document.getElementById("resolve-student-picker-group");
    const noteInp = document.getElementById("resolve-note-input");
    const confirmBtn = document.getElementById("btn-confirm-resolve");

    if (idInput) idInput.value = exc.id;
    if (actInput) actInput.value = actionType;

    const pmt = exc.payment || {};
    const applied = (pmt.allocations || []).reduce((sum, a) => sum + (a.amount_applied || 0), 0);
    const excess = Math.max(0, (pmt.amount || 0) - applied);
    const candidateName = pmt.matched_student_name || pmt.matched_student_id || "the student";
    const targetInvoice = pmt.matched_invoice_id || "INV-006";

    // Build plain English preview effect
    let previewText = "";
    let btnLabel = "Confirm";

    if (actionType === "assign_to_student") {
      if (forcePicker || !pmt.matched_student_id) {
        if (titleEl) titleEl.textContent = "Assign to student";
        btnLabel = "Assign to student";
        previewText = `Select a student to map this transaction of ${formatRupees(pmt.amount)}. It will be allocated across the student's open invoices.`;
        if (pickerGroup) pickerGroup.style.display = "block";
      } else {
        if (titleEl) titleEl.textContent = `Confirm ${candidateName}`;
        btnLabel = `Confirm ${candidateName}`;
        previewText = `Apply ${formatRupees(pmt.amount)} to ${targetInvoice} for ${candidateName}. The invoice will become Paid.`;
        if (pickerGroup) pickerGroup.style.display = "none";
      }

      // Populate students in picker dropdown if picker is needed
      if (pickerGroup && (forcePicker || !pmt.matched_student_id)) {
        await populateStudentPicker(pmt.matched_student_id || pmt.student_ref);
      }
    } else if (actionType === "accept_partial") {
      if (titleEl) titleEl.textContent = "Accept partial payment";
      btnLabel = "Accept partial";
      previewText = `Accept partial payment of ${formatRupees(pmt.amount)} on ${pmt.matched_invoice_id || 'the invoice'}. The remaining balance stays due.`;
      if (pickerGroup) pickerGroup.style.display = "none";
    } else if (actionType === "mark_duplicate") {
      if (titleEl) titleEl.textContent = "Confirm duplicate";
      btnLabel = "Confirm duplicate";
      previewText = `Confirm transaction ${escapeHtml(pmt.txn_ref || '#' + pmt.id)} as a duplicate payment. It will not be applied to any invoice.`;
      if (pickerGroup) pickerGroup.style.display = "none";
    } else if (actionType === "roll_advance_credit") {
      if (titleEl) titleEl.textContent = "Keep as advance credit";
      btnLabel = "Keep as credit";
      previewText = `Roll forward ${formatRupees(excess > 0 ? excess : pmt.amount)} excess payment as advance credit balance for ${candidateName}.`;
      if (pickerGroup) pickerGroup.style.display = "none";
    } else if (actionType === "dismiss") {
      if (titleEl) titleEl.textContent = "Dismiss exception";
      btnLabel = "Dismiss";
      previewText = `Dismiss this exception record. The transaction will be marked as dismissed and remain unapplied.`;
      if (pickerGroup) pickerGroup.style.display = "none";
    }

    if (previewEl) previewEl.innerHTML = previewText;
    if (confirmBtn) confirmBtn.textContent = btnLabel;
    if (noteInp) noteInp.value = "";

    if (modalResolve) modalResolve.classList.add("active");
  }

  async function populateStudentPicker(preselectId) {
    const sSelect = document.getElementById("resolve-student-select");
    const iSelect = document.getElementById("resolve-invoice-select");
    if (!sSelect) return;

    const students = await apiFetch("/api/students");
    sSelect.innerHTML = `<option value="">Choose student...</option>`;
    students.forEach((s) => {
      sSelect.innerHTML += `<option value="${escapeHtml(s.student_id)}">${escapeHtml(s.student_id)} — ${escapeHtml(s.name)}</option>`;
    });

    if (preselectId) {
      const match = students.find(s => String(s.student_id).toUpperCase() === String(preselectId).toUpperCase());
      if (match) sSelect.value = match.student_id;
    }

    const loadStudentInvoices = async () => {
      if (!iSelect) return;
      const sid = sSelect.value;
      iSelect.innerHTML = `<option value="">Auto-allocate across oldest open invoices</option>`;
      if (sid) {
        const invs = await apiFetch(`/api/invoices?student_id=${encodeURIComponent(sid)}`);
        invs.forEach((inv) => {
          iSelect.innerHTML += `<option value="${escapeHtml(inv.invoice_id)}">${escapeHtml(inv.invoice_id)} (${escapeHtml(inv.description)} — Due: ${formatRupees(inv.outstanding_amount)})</option>`;
        });
      }
    };

    sSelect.onchange = loadStudentInvoices;
    if (sSelect.value) await loadStudentInvoices();
  }

  const cancelResolveBtn = document.getElementById("btn-cancel-resolve");
  if (cancelResolveBtn && modalResolve) cancelResolveBtn.onclick = () => modalResolve.classList.remove("active");
  const closeResolveBtn = document.getElementById("btn-close-resolve-modal");
  if (closeResolveBtn && modalResolve) closeResolveBtn.onclick = () => modalResolve.classList.remove("active");

  if (formResolve) {
    formResolve.addEventListener("submit", async (e) => {
      e.preventDefault();
      const excId = document.getElementById("resolve-exception-id").value;
      const action = document.getElementById("resolve-action-type").value;
      const note = document.getElementById("resolve-note-input").value.trim();
      const sSelect = document.getElementById("resolve-student-select");
      const iSelect = document.getElementById("resolve-invoice-select");
      const studentId = sSelect ? sSelect.value : null;
      const invoiceId = iSelect ? (iSelect.value || null) : null;

      const exc = state.allExceptionsForTab.find(item => String(item.id) === String(excId));
      const pmt = exc ? (exc.payment || {}) : {};

      if (action === "assign_to_student" && !studentId && (!pmt.matched_student_id)) {
        showToast("Please choose a student to assign", "warning");
        return;
      }

      const assignedStudentId = studentId || pmt.matched_student_id;

      try {
        if (action === "roll_advance_credit") {
          await apiFetch(`/api/payments/${pmt.id || exc.payment_id}/overpaid-action`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ action_type: "roll_advance_credit", note: note || "Rolled forward as advance credit" }),
          });
        } else {
          await apiFetch(`/api/exceptions/${excId}/resolve`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              action: action,
              note: note || "Operator resolution action",
              student_id: assignedStudentId || null,
              invoice_id: invoiceId || null,
            }),
          });
        }

        if (modalResolve) modalResolve.classList.remove("active");

        // Close details drawer if open for this exception
        const excDrawer = document.getElementById("exception-drawer");
        if (excDrawer && excDrawer.classList.contains("active")) {
          closeAllPopoversAndDrawers();
        }

        // Section 6: Row animates out (150ms) and focus moves to next row
        const targetRow = state.activeResolvingRow || document.getElementById(`exc-row-${excId}`);
        let nextFocusTarget = null;
        if (targetRow) {
          const sibling = targetRow.nextElementSibling || targetRow.previousElementSibling;
          if (sibling && sibling.classList.contains("clickable-row")) {
            nextFocusTarget = sibling;
          }
          targetRow.classList.add("row-resolving");
        }

        setTimeout(() => {
          // Toast: "Resolved: payment #4 applied to INV-006"
          const targetRef = pmt.matched_invoice_id || (pmt.txn_ref ? pmt.txn_ref : `payment #${pmt.id || excId}`);
          showToast(`Resolved: payment #${pmt.id || exc.payment_id} applied to ${targetRef}`);

          // Remove from local tab state immediately without full page reload
          state.allExceptionsForTab = state.allExceptionsForTab.filter(item => String(item.id) !== String(excId));
          updateChipCounts(state.allExceptionsForTab);
          if (!state.resolvedFilter) {
            updateSidebarExceptionsBadge(state.allExceptionsForTab.length);
          }

          // Re-render table with updated list
          filterAndRenderExceptions();

          // Move keyboard focus
          if (nextFocusTarget) {
            try { nextFocusTarget.focus(); } catch {}
          }
        }, 150);

      } catch {
        // Handled in apiFetch
      }
    });
  }

  // =========================================================================
  // RIGHT-SIDE SLIDE-IN DETAILS DRAWER FOR EXCEPTIONS (Section 4)
  // =========================================================================

  const excDrawer = document.getElementById("exception-drawer");
  const excDrawerOverlay = document.getElementById("exception-drawer-overlay");
  const closeExcDrawerBtn = document.getElementById("btn-close-exc-drawer");

  if (closeExcDrawerBtn) closeExcDrawerBtn.onclick = closeAllPopoversAndDrawers;
  if (excDrawerOverlay) excDrawerOverlay.onclick = closeAllPopoversAndDrawers;

  async function openExceptionDrawer(excId) {
    let exc = state.allExceptionsForTab.find(item => String(item.id) === String(excId));
    if (!exc) {
      try {
        exc = await apiFetch(`/api/exceptions/${excId}`, { silentError: true });
      } catch {
        showToast("Exception record not found.", "warning");
        return;
      }
    }
    if (!exc) return;

    const pmt = exc.payment || {};
    const applied = (pmt.allocations || []).reduce((sum, a) => sum + (a.amount_applied || 0), 0);
    const isOverpaid = (exc.reason_code === "OVERPAID" || pmt.match_status === "Overpaid");
    const excess = isOverpaid ? Math.max(0, (pmt.amount || 0) - applied) : 0;

    const cfg = REASON_CONFIG[exc.reason_code] || {
      label: humanizeReason(exc.reason_code),
      colorClass: "reason-neutral",
      iconSvg: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/></svg>`
    };

    // Update Drawer Header
    const titleEl = document.getElementById("exc-drawer-title");
    const reasonBadge = document.getElementById("exc-drawer-reason-badge");
    const statusBadge = document.getElementById("exc-drawer-status-badge");
    const subEl = document.getElementById("exc-drawer-subtitle");

    if (titleEl) titleEl.textContent = `Exception #${exc.id}`;
    if (reasonBadge) {
      reasonBadge.className = `reason-pill ${cfg.colorClass}`;
      reasonBadge.innerHTML = `${cfg.iconSvg} <span>${escapeHtml(cfg.label)}</span>`;
    }
    if (statusBadge) {
      statusBadge.textContent = exc.resolved ? "Resolved" : "Open";
      statusBadge.className = exc.resolved ? "badge badge-paid" : "badge badge-neutral";
    }
    if (subEl) subEl.textContent = `Payment #${pmt.id || exc.payment_id} · ${formatDisplayDate(pmt.payment_date)}`;

    // Build Drawer Body Content
    const bodyEl = document.getElementById("exc-drawer-content");
    const footerEl = document.getElementById("exc-drawer-footer");

    if (bodyEl) {
      bodyEl.innerHTML = `
        <!-- Metrics Summary -->
        <div style="display:grid;grid-template-columns:repeat(2, 1fr);gap:12px;margin-bottom:20px;">
          <div class="card p-3">
            <span class="text-muted text-xs">Payment amount</span>
            <div class="tabular-nums font-semibold" style="font-size:18px;margin-top:2px;">${formatRupees(pmt.amount)}</div>
          </div>
          <div class="card p-3">
            <span class="text-muted text-xs">Matching confidence</span>
            <div style="margin-top:6px;">${renderConfidenceMeter(pmt.confidence_score)}</div>
          </div>
        </div>

        ${isOverpaid && excess > 0 ? `
          <div class="card p-3 mb-4" style="background:var(--reason-overpaid-bg);border-color:var(--reason-overpaid-border);">
            <div style="font-weight:600;font-size:13px;color:var(--reason-overpaid-text);">Excess payment amount</div>
            <div class="tabular-nums font-semibold" style="font-size:16px;color:var(--reason-overpaid-text);">${formatRupees(excess)} over obligation</div>
          </div>
        ` : ''}

        <!-- Full Issue Text & Resolution Prompt -->
        <div class="card p-3 mb-4" style="background:var(--bg-subtle);">
          <span class="text-muted text-xs" style="font-weight:600;">Issue details</span>
          <p style="font-size:14px;line-height:22px;color:var(--text-main);margin-top:4px;">${escapeHtml(exc.detail || 'No detailed log recorded.')}</p>
          ${exc.suggested_action ? `
            <div style="margin-top:8px;font-size:13px;color:var(--primary);font-weight:500;">
              Suggested: ${escapeHtml(exc.suggested_action)}
            </div>
          ` : ''}
        </div>

        <!-- Mapped Student / Target Invoice -->
        <div class="card p-3 mb-4">
          <span class="text-muted text-xs" style="font-weight:600;margin-bottom:8px;display:block;">Identification</span>
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;font-size:13px;">
            <div>
              <span class="text-muted text-xs">Payer name</span>
              <div class="font-semibold">${escapeHtml(pmt.payer_name || '—')}</div>
            </div>
            <div>
              <span class="text-muted text-xs">Transaction reference</span>
              <div class="monospace-font">${escapeHtml(pmt.txn_ref || `PMT-${pmt.id}`)}</div>
            </div>
            <div>
              <span class="text-muted text-xs">Quoted student ref</span>
              <div class="tabular-nums">${escapeHtml(pmt.student_ref || 'None')}</div>
            </div>
            <div>
              <span class="text-muted text-xs">Target / matched student</span>
              <div class="font-semibold">${escapeHtml(pmt.matched_student_name || pmt.matched_student_id || 'Unmatched')}</div>
            </div>
          </div>
        </div>

        <!-- Payment Allocations if present -->
        ${pmt.allocations && pmt.allocations.length > 0 ? `
          <div class="card p-0 mb-4">
            <div class="card-header py-2 px-3">
              <h4 style="font-size:13px;margin:0;">Allocated invoice obligations</h4>
            </div>
            <table class="data-table" style="font-size:13px;">
              <thead>
                <tr>
                  <th>Invoice ID</th>
                  <th class="text-right">Applied</th>
                </tr>
              </thead>
              <tbody>
                ${pmt.allocations.map(a => `
                  <tr>
                    <td class="tabular-nums"><strong>${escapeHtml(a.invoice_ref || `INV-${a.invoice_id}`)}</strong></td>
                    <td class="text-right text-success tabular-nums font-semibold">${formatRupees(a.amount_applied)}</td>
                  </tr>
                `).join('')}
              </tbody>
            </table>
          </div>
        ` : ''}

        <!-- Resolution Note History -->
        ${exc.resolution_note ? `
          <div class="card p-3 mb-4" style="border-left:3px solid var(--status-paid-text);">
            <span class="text-muted text-xs" style="font-weight:600;">Resolution record</span>
            <p style="font-size:13px;color:var(--text-main);margin-top:4px;">${escapeHtml(exc.resolution_note)}</p>
          </div>
        ` : ''}
      `;
    }

    if (footerEl) {
      if (exc.resolved) {
        footerEl.innerHTML = `<button type="button" class="btn btn-outline-secondary btn-sm" id="btn-drawer-close-ft">Close</button>`;
        const btn = footerEl.querySelector("#btn-drawer-close-ft");
        if (btn) btn.onclick = closeAllPopoversAndDrawers;
      } else {
        const candidateName = pmt.matched_student_name || pmt.matched_student_id || "student";
        let primAction = "dismiss";
        let primText = "Dismiss";

        if (exc.reason_code === "AMBIGUOUS_MATCH") {
          primAction = "assign_to_student";
          primText = `Confirm ${candidateName}`;
        } else if (exc.reason_code === "UNMATCHED") {
          primAction = "assign_to_student";
          primText = "Assign to student";
        } else if (exc.reason_code === "PARTIAL") {
          primAction = "accept_partial";
          primText = "Accept partial";
        } else if (exc.reason_code === "DUPLICATE") {
          primAction = "mark_duplicate";
          primText = "Confirm duplicate";
        } else if (exc.reason_code === "OVERPAID") {
          primAction = "roll_advance_credit";
          primText = "Keep as credit";
        } else if (exc.reason_code === "INVALID_ROW") {
          primAction = "reenter_payment";
          primText = "Re-enter payment";
        }

        footerEl.innerHTML = `
          <button type="button" class="btn btn-outline-secondary btn-sm btn-drawer-dismiss">Dismiss</button>
          <button type="button" class="btn btn-primary btn-sm btn-drawer-primary">${escapeHtml(primText)}</button>
        `;

        const primBtn = footerEl.querySelector(".btn-drawer-primary");
        const disBtn = footerEl.querySelector(".btn-drawer-dismiss");
        if (primBtn) {
          primBtn.onclick = () => {
            handleExceptionAction(exc, primAction);
          };
        }
        if (disBtn) {
          disBtn.onclick = () => {
            handleExceptionAction(exc, "dismiss");
          };
        }
      }
    }

    if (excDrawer) excDrawer.classList.add("active");
    if (excDrawerOverlay) excDrawerOverlay.classList.add("active");
  }

  // =========================================================================
  // PAGE 6: REPORTS & EXPORTS
  // =========================================================================

  async function fetchReportsData() {
    const summary = await apiFetch("/api/reports/summary");

    const timeEl = document.getElementById("report-timestamp");
    if (timeEl) timeEl.textContent = new Date().toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });

    // Section 1: Institutional specs & profile
    const repStudents = document.getElementById("rep-student-count");
    const repInvoices = document.getElementById("rep-invoice-count");
    const repContract = document.getElementById("rep-contract-total");
    if (repStudents) repStudents.textContent = summary.total_students || 0;
    if (repInvoices) repInvoices.textContent = summary.total_invoices || 0;
    if (repContract) repContract.textContent = formatRupees(summary.total_due);

    const repProfileRec = document.getElementById("rep-profile-received");
    const repProfileOut = document.getElementById("rep-profile-outstanding");
    const repProfileRate = document.getElementById("rep-profile-rate");
    const repProfileReview = document.getElementById("rep-profile-review");
    const repProfileExc = document.getElementById("rep-profile-exceptions");

    if (repProfileRec) repProfileRec.textContent = formatRupees(summary.total_received);
    if (repProfileOut) repProfileOut.textContent = formatRupees(summary.total_outstanding);
    if (repProfileRate) repProfileRate.textContent = `${summary.collection_rate || 0.0}%`;

    // Section 9 Bug Fix: Review amounts appear in reports as "Awaiting review"
    if (repProfileReview) {
      const revCnt = summary.awaiting_review_count || 0;
      const revAmt = summary.awaiting_review_amount || 0;
      repProfileReview.textContent = revAmt > 0 ? `${revCnt} (${formatRupees(revAmt)})` : `${revCnt}`;
    }
    if (repProfileExc) repProfileExc.textContent = summary.open_exceptions_count || 0;

    // Section 2: Realization breakdown
    const repDue = document.getElementById("rep-total-due");
    const repRec = document.getElementById("rep-total-received");
    const repOut = document.getElementById("rep-total-outstanding");
    const repRate = document.getElementById("rep-collection-rate");
    const repAcc = document.getElementById("rep-account-status");

    if (repDue) repDue.textContent = formatRupees(summary.total_due);
    if (repRec) repRec.textContent = formatRupees(summary.total_received);
    if (repOut) repOut.textContent = formatRupees(summary.total_outstanding);
    if (repRate) repRate.textContent = `${summary.collection_rate || 0.0}% completed`;
    if (repAcc) repAcc.textContent = (summary.total_outstanding <= 0 && summary.total_due > 0) ? "Obligations satisfied" : "Collections in progress";

    // Section 3: Payments Log
    const payments = await apiFetch("/api/payments?page=1&page_size=50");
    const pmtTbody = document.getElementById("rep-payments-log-tbody");
    if (pmtTbody) {
      pmtTbody.innerHTML = "";
      if (!payments || payments.length === 0) {
        pmtTbody.innerHTML = `<tr><td colspan="5" class="text-center text-muted py-3">No payments recorded yet.</td></tr>`;
      } else {
        payments.forEach((p, idx) => {
          pmtTbody.innerHTML += `
            <tr>
              <td class="tabular-nums font-semibold">${idx + 1}</td>
              <td class="tabular-nums">${formatDisplayDate(p.payment_date)}</td>
              <td>
                <div class="font-semibold">${escapeHtml(p.txn_ref || `PMT-${p.id}`)}</div>
                <span class="text-muted text-sm">${escapeHtml(p.payer_name || '—')}</span>
              </td>
              <td class="text-center"><span class="badge ${getBadgeClass(p.match_status)}">${escapeHtml(p.match_status)}</span></td>
              <td class="text-right tabular-nums font-semibold">${formatRupees(p.amount)}</td>
            </tr>
          `;
        });
      }
    }

    // Section 4: Exceptions breakdown in report
    const excTbody = document.getElementById("rep-exceptions-tbody");
    if (excTbody) {
      excTbody.innerHTML = "";
      const excReasons = summary.open_exceptions_by_reason || {};
      let totalOpen = 0;
      for (const [code, cnt] of Object.entries(excReasons)) {
        if (cnt > 0) {
          totalOpen += cnt;
          const cfg = REASON_CONFIG[code] || {};
          const humanLabel = cfg.label || humanizeReason(code);
          excTbody.innerHTML += `
            <tr>
              <td><span class="reason-pill ${cfg.colorClass || 'reason-neutral'}">${escapeHtml(humanLabel)}</span></td>
              <td>${escapeHtml(code === 'OVERPAID' ? 'Excess payment received beyond invoice obligation' : (code === 'AMBIGUOUS_MATCH' ? 'Candidate matches requiring operator confirmation' : 'Requires review before ledger update'))}</td>
              <td class="text-right font-semibold tabular-nums">${cnt}</td>
            </tr>
          `;
        }
      }
      if (totalOpen === 0) {
        excTbody.innerHTML = `<tr><td colspan="3" class="text-center text-muted py-3">No open exceptions. All payments reconciled!</td></tr>`;
      }
    }
  }

  const printReportBtn = document.getElementById("btn-print-report");
  if (printReportBtn) {
    printReportBtn.addEventListener("click", () => window.print());
  }

  // =========================================================================
  // DEMO DATA POPOVER & SAFE DATABASE RESET (Section 2)
  // =========================================================================

  const demoTriggerBtn = document.getElementById("btn-sidebar-demo-menu");
  const demoPopover = document.getElementById("demo-popover-menu");
  const sidebarLoadDemoBtn = document.getElementById("btn-sidebar-load-demo");
  const sidebarResetDbBtn = document.getElementById("btn-sidebar-reset-db");

  if (demoTriggerBtn && demoPopover) {
    demoTriggerBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      const isOpen = demoPopover.style.display !== "none";
      demoPopover.style.display = isOpen ? "none" : "flex";
      demoTriggerBtn.setAttribute("aria-expanded", !isOpen ? "true" : "false");
    });
  }

  if (sidebarLoadDemoBtn) {
    sidebarLoadDemoBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      closeAllPopoversAndDrawers();
      triggerLoadDemo();
    });
  }

  if (sidebarResetDbBtn) {
    sidebarResetDbBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      closeAllPopoversAndDrawers();
      openResetConfirmModal();
    });
  }

  async function triggerLoadDemo() {
    try {
      showToast("Loading demo dataset...", "info");
      const res = await apiFetch("/api/demo/load", { method: "POST" });
      showToast(`Loaded demo data: ${res.students_loaded} students, ${res.invoices_loaded} invoices, ${res.payments_processed} payments.`);
      await loadViewData(state.currentView);
    } catch {
      // Handled in apiFetch
    }
  }

  const modalResetDb = document.getElementById("modal-reset-db-overlay");
  const confirmResetDbBtn = document.getElementById("btn-confirm-reset-db");
  const cancelResetDbBtn = document.getElementById("btn-cancel-reset-db");
  const closeResetDbBtn = document.getElementById("btn-close-reset-db");

  function openResetConfirmModal() {
    if (modalResetDb) modalResetDb.classList.add("active");
  }

  if (cancelResetDbBtn && modalResetDb) cancelResetDbBtn.onclick = () => modalResetDb.classList.remove("active");
  if (closeResetDbBtn && modalResetDb) closeResetDbBtn.onclick = () => modalResetDb.classList.remove("active");

  if (confirmResetDbBtn) {
    confirmResetDbBtn.addEventListener("click", async () => {
      if (modalResetDb) modalResetDb.classList.remove("active");
      try {
        await apiFetch("/api/demo/reset", { method: "POST" });
        showToast("All data has been deleted. Schema is clean.");
        await loadViewData(state.currentView);
      } catch {
        // Handled in apiFetch
      }
    });
  }

  // Global Retry Button
  const globalRetryBtn = document.getElementById("btn-global-retry");
  if (globalRetryBtn) {
    globalRetryBtn.addEventListener("click", () => {
      loadViewData(state.currentView);
    });
  }

  // =========================================================================
  // ADDITIONAL MODAL HANDLERS (Manual Entry, Add Student, Add Invoice, CSV Import)
  // =========================================================================

  // Manual payment modal
  const modalManualPmt = document.getElementById("modal-payment-overlay");
  const btnManualEntry = document.getElementById("btn-manual-payment-entry");
  const btnCancelPmt = document.getElementById("btn-cancel-pmt");
  const btnClosePmt = document.getElementById("btn-close-payment-modal");
  const formManualPayment = document.getElementById("form-manual-payment");

  if (btnManualEntry && modalManualPmt) {
    btnManualEntry.addEventListener("click", () => modalManualPmt.classList.add("active"));
  }
  if (btnCancelPmt && modalManualPmt) btnCancelPmt.onclick = () => modalManualPmt.classList.remove("active");
  if (btnClosePmt && modalManualPmt) btnClosePmt.onclick = () => modalManualPmt.classList.remove("active");

  if (formManualPayment) {
    formManualPayment.addEventListener("submit", async (e) => {
      e.preventDefault();
      const txnRef = document.getElementById("inp-pmt-txn").value.trim() || null;
      const method = document.getElementById("inp-pmt-method").value;
      const studentRef = document.getElementById("inp-pmt-student").value.trim() || null;
      const invoiceRef = document.getElementById("inp-pmt-invoice").value.trim() || null;
      const payerName = document.getElementById("inp-pmt-payer").value.trim() || null;
      const amountRupees = parseFloat(document.getElementById("inp-pmt-amount").value);
      const dateVal = document.getElementById("inp-pmt-date").value;

      if (isNaN(amountRupees) || amountRupees <= 0) {
        showToast("Please enter a valid payment amount", "warning");
        return;
      }

      try {
        const amountPaise = Math.round(amountRupees * 100);
        await apiFetch("/api/payments", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            txn_ref: txnRef,
            method: method,
            student_ref: studentRef,
            invoice_ref: invoiceRef,
            payer_name: payerName,
            amount: amountPaise,
            payment_date: dateVal,
          }),
        });

        showToast("Payment recorded and reconciled successfully");
        if (modalManualPmt) modalManualPmt.classList.remove("active");
        formManualPayment.reset();
        await loadViewData(state.currentView);
      } catch {
        // Handled in apiFetch
      }
    });
  }

  // Add student modal
  const modalStudent = document.getElementById("modal-student-overlay");
  const btnAddStudent = document.getElementById("btn-add-student");
  const btnCancelStudent = document.getElementById("btn-cancel-student");
  const btnCloseStudentModal = document.getElementById("btn-close-student-modal");
  const formStudent = document.getElementById("form-student");

  if (btnAddStudent && modalStudent) btnAddStudent.onclick = () => modalStudent.classList.add("active");
  if (btnCancelStudent && modalStudent) btnCancelStudent.onclick = () => modalStudent.classList.remove("active");
  if (btnCloseStudentModal && modalStudent) btnCloseStudentModal.onclick = () => modalStudent.classList.remove("active");

  if (formStudent) {
    formStudent.addEventListener("submit", async (e) => {
      e.preventDefault();
      const sid = document.getElementById("inp-student-id").value.trim();
      const name = document.getElementById("inp-student-name").value.trim();
      const email = document.getElementById("inp-student-email").value.trim() || null;
      const phone = document.getElementById("inp-student-phone").value.trim() || null;

      try {
        await apiFetch("/api/students", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ student_id: sid, name: name, email: email, phone: phone }),
        });
        showToast("Student created successfully");
        if (modalStudent) modalStudent.classList.remove("active");
        formStudent.reset();
        fetchStudents();
      } catch {
        // Handled
      }
    });
  }

  // Add invoice modal
  const modalInvoice = document.getElementById("modal-invoice-overlay");
  const btnAddInvoice = document.getElementById("btn-add-invoice");
  const btnCancelInvoice = document.getElementById("btn-cancel-invoice");
  const btnCloseInvoiceModal = document.getElementById("btn-close-invoice-modal");
  const formInvoice = document.getElementById("form-invoice");

  if (btnAddInvoice && modalInvoice) {
    btnAddInvoice.addEventListener("click", async () => {
      const sSelect = document.getElementById("inp-invoice-student");
      if (sSelect) {
        const students = await apiFetch("/api/students");
        sSelect.innerHTML = `<option value="">Select student</option>`;
        students.forEach((s) => {
          sSelect.innerHTML += `<option value="${escapeHtml(s.student_id)}">${escapeHtml(s.student_id)} — ${escapeHtml(s.name)}</option>`;
        });
      }
      modalInvoice.classList.add("active");
    });
  }
  if (btnCancelInvoice && modalInvoice) btnCancelInvoice.onclick = () => modalInvoice.classList.remove("active");
  if (btnCloseInvoiceModal && modalInvoice) btnCloseInvoiceModal.onclick = () => modalInvoice.classList.remove("active");

  if (formInvoice) {
    formInvoice.addEventListener("submit", async (e) => {
      e.preventDefault();
      const invId = document.getElementById("inp-invoice-id").value.trim();
      const sid = document.getElementById("inp-invoice-student").value;
      const desc = document.getElementById("inp-invoice-desc").value.trim();
      const amt = parseFloat(document.getElementById("inp-invoice-amount").value);
      const dateVal = document.getElementById("inp-invoice-date").value;

      try {
        await apiFetch("/api/invoices", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            invoice_id: invId,
            student_id: sid,
            description: desc,
            amount_due: Math.round(amt * 100),
            due_date: dateVal,
          }),
        });
        showToast("Invoice created successfully");
        if (modalInvoice) modalInvoice.classList.remove("active");
        formInvoice.reset();
        fetchInvoices();
      } catch {
        // Handled
      }
    });
  }

  // CSV Drag and drop file ingestion for Payments
  const dropzone = document.getElementById("payments-dropzone");
  const fileInput = document.getElementById("payments-file-input");
  const browseBtn = document.getElementById("btn-browse-payments");

  if (browseBtn && fileInput) browseBtn.onclick = () => fileInput.click();
  if (dropzone && fileInput) {
    dropzone.addEventListener("dragover", (e) => { e.preventDefault(); dropzone.classList.add("dragover"); });
    dropzone.addEventListener("dragleave", () => dropzone.classList.remove("dragover"));
    dropzone.addEventListener("drop", (e) => {
      e.preventDefault();
      dropzone.classList.remove("dragover");
      if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
        uploadPaymentsCsv(e.dataTransfer.files[0]);
      }
    });
    fileInput.addEventListener("change", () => {
      if (fileInput.files && fileInput.files.length > 0) {
        uploadPaymentsCsv(fileInput.files[0]);
      }
    });
  }

  async function uploadPaymentsCsv(file) {
    const formData = new FormData();
    formData.append("file", file);
    try {
      showToast("Ingesting payments CSV...", "info");
      const res = await apiFetch("/api/payments/import", {
        method: "POST",
        body: formData,
      });
      showToast(`Ingested ${res.total_rows || 'records'}. Reconciled: ${res.matched || 0} matched, ${res.exceptions || 0} exceptions.`);
      fetchPayments();
    } catch {
      // Handled
    }
  }

  // Generic CSV upload modal for Students & Invoices
  let csvImportTarget = "students";
  const modalCsv = document.getElementById("modal-csv-overlay");
  const btnImportStudents = document.getElementById("btn-import-students");
  const btnImportInvoices = document.getElementById("btn-import-invoices");
  const btnCancelGenericCsv = document.getElementById("btn-cancel-generic-csv");
  const btnCloseCsvModal = document.getElementById("btn-close-csv-modal");
  const btnSubmitGenericCsv = document.getElementById("btn-submit-generic-csv");
  const inpGenericCsv = document.getElementById("inp-generic-csv-file");

  if (btnImportStudents && modalCsv) {
    btnImportStudents.onclick = () => {
      csvImportTarget = "students";
      document.getElementById("modal-csv-title").textContent = "Import students CSV";
      modalCsv.classList.add("active");
    };
  }
  if (btnImportInvoices && modalCsv) {
    btnImportInvoices.onclick = () => {
      csvImportTarget = "invoices";
      document.getElementById("modal-csv-title").textContent = "Import invoices CSV";
      modalCsv.classList.add("active");
    };
  }
  if (btnCancelGenericCsv && modalCsv) btnCancelGenericCsv.onclick = () => modalCsv.classList.remove("active");
  if (btnCloseCsvModal && modalCsv) btnCloseCsvModal.onclick = () => modalCsv.classList.remove("active");

  if (btnSubmitGenericCsv && inpGenericCsv) {
    btnSubmitGenericCsv.onclick = async () => {
      if (!inpGenericCsv.files || inpGenericCsv.files.length === 0) {
        showToast("Please choose a CSV file to upload", "warning");
        return;
      }
      const formData = new FormData();
      formData.append("file", inpGenericCsv.files[0]);
      const endpoint = csvImportTarget === "students" ? "/api/students/import" : "/api/invoices/import";
      try {
        await apiFetch(endpoint, { method: "POST", body: formData });
        showToast(`${csvImportTarget === 'students' ? 'Students' : 'Invoices'} imported successfully`);
        if (modalCsv) modalCsv.classList.remove("active");
        inpGenericCsv.value = "";
        if (csvImportTarget === "students") fetchStudents();
        else fetchInvoices();
      } catch {
        // Handled
      }
    };
  }

  // Helper debounce
  function debounce(fn, ms) {
    let timer;
    return function (...args) {
      clearTimeout(timer);
      timer = setTimeout(() => fn.apply(this, args), ms);
    };
  }

  // =========================================================================
  // INITIALIZATION
  // =========================================================================
  switchView("dashboard");
});
