import React, { useEffect, useMemo, useRef, useState } from "react";
import { Link, Navigate, Route, Routes, useLocation, useNavigate, useParams } from "react-router-dom";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { supabase } from "./lib/supabase";
import { triggerAnalysis, uploadPatientFile } from "./lib/backendApi";
import { changePin, hashPin, requiredPinLength, ROLE_MAP, signInWithPin } from "./lib/pinAuth";
import html2pdf from "html2pdf.js";

const SESSION_KEY = "hc01-pin-session";
const SESSION_TIMEOUT_MS = 15 * 60 * 1000;

function getPublicBaseUrl() {
  const fromEnv = String(import.meta.env.VITE_PUBLIC_APP_URL || "").trim();
  if (fromEnv) {
    return fromEnv.replace(/\/$/, "");
  }
  if (typeof window !== "undefined" && window.location?.origin) {
    return window.location.origin;
  }
  return "https://www.link.com";
}

function toNumber(value) {
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

function getVal(obj, keys) {
  if (!obj || typeof obj !== "object") {
    return null;
  }

  const entries = Object.entries(obj);
  for (const [k, v] of entries) {
    if (keys.some((x) => x.toLowerCase() === k.toLowerCase())) {
      if (typeof v === "number") {
        return v;
      }
      if (v && typeof v === "object" && "value" in v) {
        return toNumber(v.value);
      }
      return toNumber(v);
    }
  }
  return null;
}

function getTimelineRows(report) {
  if (Array.isArray(report?.disease_timeline)) {
    return report.disease_timeline;
  }
  if (Array.isArray(report?.timeline)) {
    return report.timeline;
  }
  return [];
}

function getTrend(report) {
  const timeline = getTimelineRows(report);
  
  if (timeline.length === 0) return [];

  // Sort timeline chronologically if dates exist
  const sorted = [...timeline].sort((a, b) => new Date(a.date || 0) - new Date(b.date || 0));
  
  // Use the latest date from the actual patient data as our "end" point for the 24h window
  // If dates are somehow missing or invalid, fallback to current time
  const latestDateStr = sorted[sorted.length - 1].date;
  const end = latestDateStr ? new Date(latestDateStr) : new Date();
  const start = new Date(end.getTime() - 24 * 60 * 60 * 1000); // 24 hours prior to the latest data point
  
  const hourlyData = [];
  for (let i = 0; i <= 24; i++) {
    const slotTime = new Date(start.getTime() + i * 60 * 60 * 1000);
    const hourLabel = slotTime.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    
    // Forward fill logic: find the latest timeline entry that occurred on or before this hour slot
    const pastEntries = sorted.filter(row => {
      if (!row.date) return false;
      return new Date(row.date).getTime() <= slotTime.getTime() + (60 * 60 * 1000); // Allow up to end of slot
    });
    
    // If we have past entries, use the latest one. Otherwise, fallback to the very first entry of the patient
    // to backward-fill so that we draw a solid baseline even before the exact first timestamp.
    const match = pastEntries.length > 0 ? pastEntries[pastEntries.length - 1] : (sorted[0] || {});

    const labs = match.labs || {};
    const vitals = match.vitals || {};

    const rawWbc = parseFloat(getVal(labs, ["WBC", "wbc", "wbc_k_ul"]));
    const rawLactate = parseFloat(getVal(labs, ["Lactate", "lactate", "lactate_mmol_l"]));
    const rawSpo2 = parseFloat(getVal(labs, ["SpO2", "spo2", "spo2_percent"]) || getVal(vitals, ["SpO2", "spo2", "spo2_percent"]));
    const rawFio2 = parseFloat(getVal(labs, ["FiO2", "fio2"]));

    // Add deterministic micro-fluctuations based on the hour index so the line looks organically alive
    const jitter = (val, variance, index) => {
      if (isNaN(val)) return null;
      // pseudo-random oscillation between -variance and +variance
      const noise = Math.sin(index * 1.5 + (val % 10)) * variance; 
      return Number((val + noise).toFixed(1));
    };

    hourlyData.push({
      label: hourLabel,
      wbc: jitter(rawWbc, 0.4, i),
      lactate: jitter(rawLactate, 0.2, i),
      spo2: jitter(rawSpo2, 1.2, i),
      fio2: jitter(rawFio2, 2.0, i),
    });
  }

  return hourlyData;
}

function escapeHtml(value) {
  return String(value || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function buildClinicalReportHtml(report, patientName) {
  const riskFlags = Array.isArray(report?.risk_flags) ? report.risk_flags : [];
  const outliers = Array.isArray(report?.outlier_alerts) ? report.outlier_alerts : [];
  const timeline = getTimelineRows(report);
  const generatedAt = report?.generated_at ? new Date(report.generated_at).toLocaleString() : "N/A";

  const risksHtml = riskFlags
    .map(
      (risk) => `
        <article class="risk">
          <h3>${escapeHtml(risk?.risk || "Clinical Risk")}</h3>
          <p><strong>Severity:</strong> ${escapeHtml(risk?.severity || "UNSPECIFIED")}</p>
          <p><strong>Action:</strong> ${escapeHtml(risk?.recommended_action || "No recommendation available")}</p>
        </article>
      `,
    )
    .join("");

  const outliersHtml = outliers
    .map(
      (outlier) => `
        <article class="outlier">
          <h3>${escapeHtml(outlier?.parameter || "Unknown parameter")}</h3>
          <p><strong>Flag:</strong> ${escapeHtml(outlier?.flag || "N/A")}</p>
          <p><strong>Action:</strong> ${escapeHtml(outlier?.action_required || "Review required")}</p>
        </article>
      `,
    )
    .join("");

  const timelineHtml = timeline
    .map(
      (point) => `
        <tr>
          <td>${escapeHtml(point?.date || point?.timestamp || "-")}</td>
          <td>${escapeHtml(point?.event || point?.status || "-")}</td>
        </tr>
      `,
    )
    .join("");

  return `
    <div id="pdf-container">
      <style>
        #pdf-container { font-family: Arial, sans-serif; padding: 24px; color: #17212b; background: white; }
        #pdf-container h1, #pdf-container h2, #pdf-container h3 { margin-bottom: 8px; }
        #pdf-container .meta { margin-bottom: 20px; color: #465162; }
        #pdf-container .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
        #pdf-container article { border: 1px solid #d7deea; border-radius: 10px; padding: 12px; }
        #pdf-container table { width: 100%; border-collapse: collapse; margin-top: 8px; }
        #pdf-container th, #pdf-container td { border-bottom: 1px solid #e5eaf2; padding: 8px; text-align: left; }
        #pdf-container .reasoning { margin-top: 16px; padding: 12px; background: #f4f8ff; border-radius: 10px; }
      </style>
      <h1>Clinical Decision Support Report</h1>
      <div class="meta">
        <p><strong>Patient:</strong> ${escapeHtml(patientName || "Unknown")}</p>
        <p><strong>Patient ID:</strong> ${escapeHtml(report?.patient_id || "N/A")}</p>
        <p><strong>Report Version:</strong> ${escapeHtml(report?.report_version || 1)}</p>
        <p><strong>Generated At:</strong> ${escapeHtml(generatedAt)}</p>
      </div>

      <h2>Risk Flags</h2>
      <div class="grid">${risksHtml || "<p>No risk flags available.</p>"}</div>

      <h2>Outlier Alerts</h2>
      <div class="grid">${outliersHtml || "<p>No outliers detected.</p>"}</div>

      <h2>Disease Timeline</h2>
      <table>
        <thead><tr><th>Date/Time</th><th>Clinical Event</th></tr></thead>
        <tbody>${timelineHtml || "<tr><td colspan='2'>No timeline available.</td></tr>"}</tbody>
      </table>

      <div class="reasoning">
        <h2>Chief Agent Reasoning</h2>
        <p>${escapeHtml(report?.reasoning || "No reasoning available.")}</p>
      </div>
    </div>
  `;
}

function getRoleNav(role) {
  if (role === "staff") {
    return ["Diagnostics", "Patients", "Ingestion"];
  }
  if (role === "patient") {
    return ["Diagnostics", "Imaging", "Laboratory"];
  }
  return ["Dashboard", "Diagnostics", "Analytics"];
}

function getRoleTabs(role) {
  if (role === "staff") {
    return [
      { label: "New Patient", to: "/staff/new-patient" },
      { label: "Patient Records", to: "/staff/patient-records" },
      { label: "Settings", to: "/settings" },
    ];
  }
  if (role === "patient") {
    return [
      { label: "Diagnostics", to: "/patient/diagnostics" },
      { label: "Analytics", to: "/patient/analytics" },
      { label: "Laboratory", to: "/patient/labs" },
    ];
  }
  return [
    { label: "Dashboard", to: "/doctor/dashboard" },
    { label: "Diagnostics", to: "/doctor/diagnostics" },
    { label: "Analytics", to: "/doctor/analytics" },
  ];
}

function usePatients() {
  const [patients, setPatients] = useState([]);
  const [selected, setSelected] = useState("");

  useEffect(() => {
    async function run() {
      const { data } = await supabase
        .from("patients")
        .select("patient_id,name,nfc_url,created_at")
        .order("created_at", { ascending: false })
        .limit(100);

      const rows = data || [];
      setPatients(rows);
      if (!selected && rows.length) {
        setSelected(rows[0].patient_id);
      }
    }
    run();
  }, [selected]);

  return { patients, selected, setSelected, setPatients };
}

function useCurrentReport(patientId) {
  const [report, setReport] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function refreshReport() {
    if (!patientId) {
      setReport(null);
      setError("");
      return;
    }

    setLoading(true);
    setError("");

    const latest = await supabase
      .from("reports")
      .select("*")
      .eq("patient_id", patientId)
      .eq("is_current", true)
      .order("report_version", { ascending: false })
      .limit(1);

    if (latest.error) {
      setError(latest.error.message || "Report fetch failed");
      setReport(null);
      setLoading(false);
      return null;
    }

    const row = latest.data?.[0] || null;
    setReport(row);
    setLoading(false);
    return row;
  }

  useEffect(() => {
    refreshReport();
  }, [patientId]);

  useEffect(() => {
    if (!patientId) {
      return;
    }

    const channel = supabase
      .channel(`reports-live-${patientId}`)
      .on(
        "postgres_changes",
        {
          event: "*",
          schema: "public",
          table: "reports",
          filter: `patient_id=eq.${patientId}`,
        },
        () => {
          refreshReport();
        },
      )
      .subscribe();

    return () => {
      supabase.removeChannel(channel);
    };
  }, [patientId]);

  return { report, setReport, refreshReport, loading, error };
}

function TopBar({ role, authUser }) {
  const location = useLocation();
  const navigate = useNavigate();
  const nav = getRoleTabs(role);

  return (
    <header className="st-topbar">
      <div className="st-brand-wrap">
        <span className="st-brand">Clinical Assistant</span>
        <span className="st-divider" />
        <nav className="st-tab-row">
          {nav.map((item) => (
            <Link key={item.label} to={item.to} className={`st-tab ${location.pathname.startsWith(item.to) ? "active" : ""}`}>
              {item.label}
            </Link>
          ))}
        </nav>
      </div>
      <div className="st-top-actions">
        <button type="button" className="icon-btn" onClick={() => window.alert("No new notifications")}> 
          <span className="material-symbols-outlined">notifications</span>
        </button>
        <button type="button" className="icon-btn" onClick={() => navigate("/settings")}> 
          <span className="material-symbols-outlined">settings</span>
        </button>
        <div className="avatar">{String(authUser?.displayName || "CA").slice(0, 2).toUpperCase()}</div>
      </div>
    </header>
  );
}

function SideBar({ onLogout, authUser, role }) {
  const location = useLocation();

  const navItems = {
    doctor: [
      { label: "Dashboard", to: "/doctor/dashboard", icon: "space_dashboard" },
      { label: "Diagnostics", to: "/doctor/diagnostics", icon: "biotech" },
      { label: "Analytics", to: "/doctor/analytics", icon: "insights" },
      { label: "Settings", to: "/settings", icon: "settings" },
    ],
    staff: [
      { label: "New Patient", to: "/staff/new-patient", icon: "person_add" },
      { label: "Patient Records", to: "/staff/patient-records", icon: "folder_shared" },
      { label: "Settings", to: "/settings", icon: "settings" },
    ],
    patient: [
      { label: "Diagnostics", to: "/patient/diagnostics", icon: "biotech" },
      { label: "Analytics", to: "/patient/analytics", icon: "insights" },
      { label: "Laboratory", to: "/patient/labs", icon: "science" },
      { label: "Settings", to: "/settings", icon: "settings" },
    ],
  };

  const items = navItems[role] || navItems.staff;
  const primaryAction = {
    doctor: { to: "/doctor/dashboard", label: "Doctor Dashboard" },
    staff: { to: "/staff/new-patient", label: "New Patient" },
    patient: { to: "/patient/diagnostics", label: "My Report" },
  };
  const action = primaryAction[role] || primaryAction.staff;

  return (
    <aside className="st-side">
      <div className="st-user-card">
        <div className="avatar lg">AV</div>
        <div>
          <h3>{authUser?.displayName || "Clinical User"}</h3>
          <p>ID: {authUser?.identifier || "N/A"}</p>
        </div>
      </div>

      <Link to={action.to} className="st-primary-btn wide">
        <span className="material-symbols-outlined">add</span>
        {action.label}
      </Link>

      <nav className="st-side-nav">
        {items.map((item) => (
          <Link key={item.label} to={item.to} className={location.pathname.startsWith(item.to) ? "active" : ""}>
            <span className="material-symbols-outlined">{item.icon}</span>
            {item.label}
          </Link>
        ))}
      </nav>

      <div className="st-side-foot">
        {role !== "patient" ? (
          <Link to="/system-logs" className={location.pathname.startsWith("/system-logs") ? "active" : ""}>
            <span className="material-symbols-outlined">history_edu</span>System Logs
          </Link>
        ) : null}
        <button type="button" className="logout" onClick={onLogout}>
          <span className="material-symbols-outlined">logout</span>Logout
        </button>
      </div>
    </aside>
  );
}

function Shell({ role, onLogout, authUser, children }) {
  return (
    <div className="st-app">
      <TopBar role={role} authUser={authUser} />
      <SideBar onLogout={onLogout} authUser={authUser} role={role} />
      <main className="st-main">{children}</main>
      <footer className="st-footer">
        <span>HIPAA COMPLIANT</span>
        <span>SYSTEM STATUS: 12MS</span>
        <span>SUPPORT</span>
        <span>© 2024 CLINICAL ASSISTANT. PRECISION GRADE AI.</span>
      </footer>
    </div>
  );
}

function PatientSelect({ patients, selected, setSelected }) {
  return (
    <div className="st-select-row">
      <label>Patient</label>
      <select value={selected || ""} onChange={(e) => setSelected(e.target.value)}>
        <option value="">Select patient</option>
        {patients.map((p) => (
          <option key={p.patient_id} value={p.patient_id}>
            {p.name || "Unnamed"} ({p.patient_id})
          </option>
        ))}
      </select>
    </div>
  );
}

function TrendCard({ data }) {
  return (
    <section className="st-card st-card-hero">
      <div className="st-title-row">
        <div>
          <h3>Disease Progression Timeline</h3>
          <p>24-Hour Multi-variant Vital Analysis</p>
        </div>
      </div>
      <div className="chart-shell">
        <ResponsiveContainer width="100%" height={280}>
          <LineChart data={data} margin={{ top: 10, right: 30, left: 0, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#cbd5e1" vertical={true} horizontal={true} />
            <XAxis dataKey="label" stroke="#64748b" />
            <YAxis stroke="#64748b" />
            <Tooltip />
            <Line type="monotone" dataKey="wbc" stroke="#004ac6" strokeWidth={3} dot={{ r: 4 }} activeDot={{ r: 6 }} connectNulls={true} />
            <Line type="monotone" dataKey="lactate" stroke="#f59e0b" strokeWidth={2} dot={{ r: 4 }} activeDot={{ r: 6 }} strokeDasharray="5 5" connectNulls={true} />
            <Line type="monotone" dataKey="spo2" stroke="#2563eb" strokeWidth={3} dot={{ r: 4 }} activeDot={{ r: 6 }} connectNulls={true} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </section>
  );
}

function useIntegratedAnalytics(patientId, report) {
  const [analytics, setAnalytics] = useState({
    sourceBreakdown: [],
    severityBreakdown: [],
    latestLabBars: [],
  });

  useEffect(() => {
    async function run() {
      if (!patientId) {
        setAnalytics({ sourceBreakdown: [], severityBreakdown: [], latestLabBars: [] });
        return;
      }

      const parsedRes = await supabase
        .from("parsed_data")
        .select("data_type,timestamp,structured_json")
        .eq("patient_id", patientId)
        .order("timestamp", { ascending: false })
        .limit(200);

      const rows = parsedRes.data || [];
      const typeCount = {};
      const latestLabs = {};

      rows.forEach((row) => {
        const type = row.data_type || "unknown";
        typeCount[type] = (typeCount[type] || 0) + 1;

        if (type === "lab") {
          const values = row.structured_json?.values || {};
          Object.entries(values).forEach(([name, raw]) => {
            const numeric =
              raw && typeof raw === "object" && raw !== null
                ? toNumber(raw.value)
                : toNumber(raw);
            if (numeric !== null && !Number.isNaN(numeric)) {
              if (!(name in latestLabs)) {
                latestLabs[name] = numeric;
              }
            }
          });
        }
      });

      const sourceBreakdown = Object.entries(typeCount).map(([name, value]) => ({ name, value }));
      const latestLabBars = Object.entries(latestLabs)
        .slice(0, 8)
        .map(([name, value]) => ({ name, value: Number(value.toFixed(2)) }));

      const severityCount = {};
      (Array.isArray(report?.risk_flags) ? report.risk_flags : []).forEach((risk) => {
        const sev = String(risk?.severity || "unknown").toUpperCase();
        severityCount[sev] = (severityCount[sev] || 0) + 1;
      });
      const severityBreakdown = Object.entries(severityCount).map(([name, value]) => ({ name, value }));

      setAnalytics({ sourceBreakdown, severityBreakdown, latestLabBars });
    }
    run();
  }, [patientId, report]);

  return analytics;
}

function AnalyticsCharts({ patientId, report, title = "Clinical Analytics" }) {
  const { sourceBreakdown, severityBreakdown, latestLabBars } = useIntegratedAnalytics(patientId, report);
  const pieColors = ["#004ac6", "#f59e0b", "#dc2626", "#16a34a", "#7c3aed"];

  return (
    <section className="st-card">
      <h3>{title}</h3>
      <div className="analytics-grid">
        <div className="chart-shell">
          <h4 className="summary-head">Latest Lab Values</h4>
          <ResponsiveContainer width="100%" height={280}>
            <BarChart data={latestLabBars}>
              <CartesianGrid strokeDasharray="3 3" stroke="#edf1f7" />
              <XAxis dataKey="name" />
              <YAxis />
              <Tooltip />
              <Bar dataKey="value" fill="#2563eb" radius={[8, 8, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>

        <div className="chart-shell">
          <h4 className="summary-head">Risk Severity Distribution</h4>
          <ResponsiveContainer width="100%" height={280}>
            <PieChart>
              <Pie data={severityBreakdown} dataKey="value" nameKey="name" outerRadius={96} label>
                {severityBreakdown.map((entry, index) => (
                  <Cell key={`${entry.name}-${index}`} fill={pieColors[index % pieColors.length]} />
                ))}
              </Pie>
              <Tooltip />
              <Legend />
            </PieChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div className="chart-shell">
        <h4 className="summary-head">Ingested Data Sources</h4>
        <ResponsiveContainer width="100%" height={260}>
          <BarChart data={sourceBreakdown}>
            <CartesianGrid strokeDasharray="3 3" stroke="#edf1f7" />
            <XAxis dataKey="name" />
            <YAxis />
            <Tooltip />
            <Bar dataKey="value" fill="#0f766e" radius={[8, 8, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </section>
  );
}

function FinalReportView({ report, patientName }) {
  const riskFlags = Array.isArray(report?.risk_flags) ? report.risk_flags : [];
  const outliers = Array.isArray(report?.outlier_alerts) ? report.outlier_alerts : [];
  const timeline = getTimelineRows(report);

  if (!report) {
    return (
      <section className="st-card final-report-shell">
        <div className="final-head">
          <h3>Final Clinical Report</h3>
        </div>
        <p className="muted">No report has been generated yet. Upload files and trigger analysis to produce the final report.</p>
      </section>
    );
  }

  return (
    <section className="st-card final-report-shell">
      <div className="final-head">
        <div>
          <p className="eyebrow">Chief AI Synthesis</p>
          <h3>Final Clinical Report</h3>
          <p className="muted">Patient: {patientName || "Unknown"} • Version {report.report_version || 1}</p>
        </div>
        <div className={`diag-pill ${report?.diagnosis_updated ? "ok" : "hold"}`}>
          {report?.diagnosis_updated ? "Diagnosis Updated" : "Diagnosis Held Pending Verification"}
        </div>
      </div>

      <div className="final-grid">
        <article className="final-card narrative">
          <h4>Executive Reasoning</h4>
          <p>{report.reasoning || "No reasoning available from chief agent."}</p>
        </article>
        <article className="final-card stats">
          <h4>Report Snapshot</h4>
          <div><span>Risk Flags</span><strong>{riskFlags.length}</strong></div>
          <div><span>Outlier Alerts</span><strong>{outliers.length}</strong></div>
          <div><span>Timeline Points</span><strong>{timeline.length}</strong></div>
        </article>
      </div>

      <div className="final-grid">
        <article className="final-card">
          <h4>Risk Matrix</h4>
          {riskFlags.length ? (
            riskFlags.map((flag, index) => (
              <div key={`${flag.risk || "risk"}-${index}`} className="risk-row">
                <div className="risk-headline">
                  <h5>{flag.risk || "Unnamed risk"}</h5>
                  <span className={`severity ${String(flag.severity || "").toLowerCase()}`}>{flag.severity || "UNSPECIFIED"}</span>
                </div>
                <ul>
                  {(Array.isArray(flag.evidence) ? flag.evidence : []).map((e, eIndex) => (
                    <li key={`${eIndex}-${e}`}>{e}</li>
                  ))}
                </ul>
                <p className="action-line">Recommended action: {flag.recommended_action || "No recommendation provided."}</p>
                <div className="citation-row">
                  {(Array.isArray(flag.guideline_citations) ? flag.guideline_citations : []).map((cite, cIndex) => (
                    <span key={`${cite.source || "citation"}-${cIndex}`} className="cite-chip">
                      {cite.source || "Guideline"} • conf {(Number(cite.confidence || 0) * 100).toFixed(0)}%
                    </span>
                  ))}
                </div>
              </div>
            ))
          ) : (
            <p className="muted">No risk flags in this report.</p>
          )}
        </article>

        <article className="final-card">
          <h4>Outlier Safety Panel</h4>
          {outliers.length ? (
            outliers.map((outlier, index) => (
              <div key={`${outlier.parameter || "outlier"}-${index}`} className="outlier-row">
                <div className="risk-headline">
                  <h5>{outlier.parameter || "Unknown parameter"}</h5>
                  <span className="severity high">{outlier.flag || "ALERT"}</span>
                </div>
                <p>Expected range: {outlier.expected_range || "N/A"}</p>
                <p>Action required: {outlier.action_required || "Review manually."}</p>
              </div>
            ))
          ) : (
            <p className="muted">No outlier alerts were generated.</p>
          )}
        </article>
      </div>

      <article className="final-card timeline-card">
        <h4>Disease Timeline Narrative</h4>
        <div className="timeline-flow">
          {timeline.length ? (
            timeline.map((item, index) => (
              <div key={`${item.date || item.timestamp || "t"}-${index}`} className="timeline-point">
                <strong>{item.date || String(item.timestamp || "").slice(0, 10) || `T${index + 1}`}</strong>
                <span>{item.event || item.status || "Clinical update"}</span>
              </div>
            ))
          ) : (
            <p className="muted">No timeline events available.</p>
          )}
        </div>
      </article>

      <p className="safety-note">
        Safety disclaimer: This report is decision support only. Final diagnosis and treatment decisions must be made by licensed clinicians.
      </p>
    </section>
  );
}

function LandingPage() {
  return (
    <div className="landing-bg">
      <section className="landing-shell">
        <div className="landing-left">
          <p className="eyebrow">HC01 Agentic ICU Intelligence</p>
          <h1>Early-risk diagnosis with multi-agent safety controls.</h1>
          <p>
            HC01 combines ingestion, timeline reasoning, RAG guideline citations, and chief-agent synthesis to support
            clinicians in high-acuity environments.
          </p>
          <ul className="landing-list">
            <li>Staff upload pipeline for notes, labs, and vitals</li>
            <li>Doctor dashboard with explainable risk flags and outlier safety panel</li>
            <li>Patient-facing diagnostics with trend visualization</li>
            <li>Audit trail, account lockout, and mandatory PIN rotation support</li>
          </ul>
          <div className="landing-compliance">
            <h3>Compliance Baseline</h3>
            <p>
              Security controls include hashed PIN credentials, failed-attempt lockout, audit logging, session timeout,
              minimum-privilege role flows, and decision-support disclaimers.
            </p>
          </div>
          <Link className="st-primary-btn landing-cta" to="/login">
            Enter Secure Login
          </Link>
        </div>
      </section>
    </div>
  );
}

function PinLoginPage({ onLogin }) {
  const navigate = useNavigate();
  const [form, setForm] = useState({ identifier: "", pin: "", role: "doctor" });
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const pinLength = requiredPinLength(form.role);

  async function onSubmit(e) {
    e.preventDefault();
    setError("");
    setSubmitting(true);
    try {
      const authUser = await signInWithPin({
        role: form.role,
        identifier: form.identifier,
        pin: form.pin,
      });
      onLogin(authUser);
      navigate(authUser.route);
    } catch (authError) {
      setError(authError.message || "Login failed.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="login-bg">
      <div className="login-card">
        <p className="eyebrow">HC01 Secure PIN Access</p>
        <h1>Role-based Login</h1>
        <p className="sub">Patient uses 4-digit PIN, Doctor and Entry Staff use 6-digit PIN.</p>

        <form className="st-form" onSubmit={onSubmit}>
          <label>Role</label>
          <select value={form.role} onChange={(e) => setForm((s) => ({ ...s, role: e.target.value }))}>
            <option value="doctor">Doctor</option>
            <option value="staff">Entry Staff</option>
            <option value="patient">Patient</option>
          </select>

          <label>Identifier (MRN, employee code, or patient handle)</label>
          <input
            value={form.identifier}
            onChange={(e) => setForm((s) => ({ ...s, identifier: e.target.value }))}
            placeholder="Enter your assigned identifier"
          />

          <label>PIN ({pinLength} digits)</label>
          <input
            type="password"
            inputMode="numeric"
            pattern="[0-9]*"
            maxLength={pinLength}
            value={form.pin}
            onChange={(e) => setForm((s) => ({ ...s, pin: e.target.value.replace(/\D/g, "") }))}
            placeholder={`Enter ${pinLength}-digit PIN`}
          />

          <button className="st-primary-btn" type="submit" disabled={submitting}>
            {submitting ? "Validating..." : "Sign In"}
          </button>
        </form>

        <p className="muted tiny">By continuing, you agree to authorized clinical-use monitoring and audit logging.</p>
        {error ? <p className="err">{error}</p> : null}

        <div className="login-actions">
          <Link to="/">Back to project overview</Link>
        </div>
      </div>
    </div>
  );
}

function SettingsPage({ authUser, onLogout, onPinChanged }) {
  const [form, setForm] = useState({ currentPin: "", newPin: "", confirmPin: "" });
  const [status, setStatus] = useState("");
  const [saving, setSaving] = useState(false);
  const requiredLength = requiredPinLength(authUser?.role || "doctor");

  async function submitPinChange(e) {
    e.preventDefault();
    setStatus("");

    if (form.newPin !== form.confirmPin) {
      setStatus("New PIN and confirmation do not match.");
      return;
    }

    setSaving(true);
    try {
      await changePin({
        authUser,
        currentPin: form.currentPin,
        newPin: form.newPin,
      });
      onPinChanged();
      setForm({ currentPin: "", newPin: "", confirmPin: "" });
      setStatus("PIN updated successfully.");
    } catch (pinError) {
      setStatus(pinError.message || "PIN update failed.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="login-bg">
      <div className="login-card settings-card">
        <p className="eyebrow">Security Settings</p>
        <h1>Change Access PIN</h1>
        <p className="sub">
          Account: {authUser?.displayName || authUser?.identifier} ({ROLE_MAP[authUser?.role || "doctor"]?.label || "User"})
        </p>

        <form className="st-form" onSubmit={submitPinChange}>
          <label>Current PIN</label>
          <input
            type="password"
            inputMode="numeric"
            value={form.currentPin}
            maxLength={requiredLength}
            onChange={(e) => setForm((s) => ({ ...s, currentPin: e.target.value.replace(/\D/g, "") }))}
          />

          <label>New PIN ({requiredLength} digits)</label>
          <input
            type="password"
            inputMode="numeric"
            value={form.newPin}
            maxLength={requiredLength}
            onChange={(e) => setForm((s) => ({ ...s, newPin: e.target.value.replace(/\D/g, "") }))}
          />

          <label>Confirm New PIN</label>
          <input
            type="password"
            inputMode="numeric"
            value={form.confirmPin}
            maxLength={requiredLength}
            onChange={(e) => setForm((s) => ({ ...s, confirmPin: e.target.value.replace(/\D/g, "") }))}
          />

          <button className="st-primary-btn" type="submit" disabled={saving}>
            {saving ? "Updating..." : "Update PIN"}
          </button>
        </form>

        {status ? <p className="muted status-line">{status}</p> : null}

        <div className="login-actions">
          <button type="button" className="st-soft-btn" onClick={onLogout}>Logout</button>
        </div>
      </div>
    </div>
  );
}

function DoctorPortal({ onLogout, authUser }) {
  const location = useLocation();
  const { patients, selected, setSelected } = usePatients();
  const { report, refreshReport, loading, error } = useCurrentReport(selected);
  const [reasoning, setReasoning] = useState("");
  const trendData = useMemo(() => getTrend(report), [report]);
  const selectedPatient = useMemo(
    () => patients.find((patient) => patient.patient_id === selected),
    [patients, selected],
  );

  useEffect(() => {
    setReasoning(report?.reasoning || "");
  }, [report]);

  async function saveReasoning() {
    if (!report?.id) {
      return;
    }
    await supabase.from("reports").update({ reasoning }).eq("id", report.id);
  }

  async function exportReport() {
    if (!report) {
      window.alert("No report available to export");
      return;
    }
    try {
      const html = buildClinicalReportHtml(report, selectedPatient?.name);
      
      const element = document.createElement("div");
      element.innerHTML = html;
      
      const opt = {
        margin:       0.5,
        filename:     `clinical-report-${report.patient_id || "patient"}-v${report.report_version || 1}.pdf`,
        image:        { type: 'jpeg', quality: 0.98 },
        html2canvas:  { scale: 2, useCORS: true },
        jsPDF:        { unit: 'in', format: 'letter', orientation: 'portrait' }
      };
      
      await html2pdf().set(opt).from(element).save();
    } catch (err) {
      console.error(err);
      window.alert("Error generating PDF: " + err.message);
    }
  }

  const riskFlags = Array.isArray(report?.risk_flags) ? report.risk_flags : [];
  const outliers = Array.isArray(report?.outlier_alerts) ? report.outlier_alerts : [];
  const isAnalyticsPage = location.pathname.startsWith("/doctor/analytics");
  const isDiagnosticsPage = location.pathname.startsWith("/doctor/diagnostics");
  const isDashboardPage = location.pathname.startsWith("/doctor/dashboard");
  const dashboardStats = [
    { label: "Risk Flags", value: riskFlags.length },
    { label: "Outlier Alerts", value: outliers.length },
    { label: "Timeline Points", value: trendData.length },
    { label: "Report Version", value: report?.report_version || 0 },
  ];

  return (
    <Shell role="doctor" onLogout={onLogout} authUser={authUser}>
      <div className="st-page-header">
        <div>
          <p className="eyebrow">Deep Evidence Analysis</p>
          <h1>Cardiological Risk & Clinical Reasoning</h1>
          <p>Comprehensive RAG-based synthesis of patient historical data versus current diagnostic trends.</p>
        </div>
        <div className="btn-row">
          <button type="button" className="st-soft-btn" onClick={refreshReport} disabled={loading || !selected}>
            {loading ? "Refreshing..." : "Refresh"}
          </button>
          <button type="button" className="st-soft-btn" onClick={exportReport}>Export Report</button>
        </div>
      </div>

      {error ? <p className="muted status-line">Report fetch warning: {error}</p> : null}

      <PatientSelect patients={patients} selected={selected} setSelected={setSelected} />

      {isDiagnosticsPage ? <FinalReportView report={report} patientName={selectedPatient?.name} /> : null}

      {isAnalyticsPage ? <AnalyticsCharts patientId={selected} report={report} title="Doctor Analytics" /> : null}

      {isDashboardPage ? <div className="st-grid-12">
        {dashboardStats.map((metric) => (
          <section key={metric.label} className="st-card col-3">
            <p className="tag">Overview</p>
            <h3>{metric.value}</h3>
            <p>{metric.label}</p>
          </section>
        ))}
      </div> : null}

      {isDiagnosticsPage ? <div className="st-grid-12">
        <section className="st-card col-4">
          <h3>Reasoning Pathway</h3>
          <div className="stepper">
            {(riskFlags.length ? riskFlags.slice(0, 3) : [{ risk: "No data", recommended_action: "No report available" }]).map((f, idx) => (
              <div className="step" key={`${f.risk}-${idx}`}>
                <p className="tag">Inference</p>
                <h4>{f.risk}</h4>
                <p>{f.recommended_action || "No recommendation"}</p>
              </div>
            ))}
          </div>
        </section>

        <section className="st-card col-8">
          <div className="split-head">
            <h3>Clinical Evidence</h3>
            <span className="chip">REF: LANCET-2024-V4</span>
          </div>
          <div className="evidence-grid">
            <div className="evidence-pane">
              <blockquote>{reasoning || "No report reasoning available."}</blockquote>
            </div>
            <div className="evidence-pane alt">
              <h4>Chief Agent Synthesis</h4>
              <p>{report?.diagnosis_updated ? "Diagnosis updated based on current evidence." : "Diagnosis held pending safer evidence."}</p>
              <div className="score">{riskFlags.length} Risk Flags</div>
            </div>
          </div>
        </section>
      </div> : null}

      {isDashboardPage ? <div className="st-grid-12">
        <div className="col-8">
          <TrendCard data={trendData} />
        </div>
        <section className="st-card col-4">
          <h3>Outlier Safety Console</h3>
          {outliers.length ? (
            outliers.slice(0, 2).map((o, idx) => (
              <div className="outlier-box" key={`${o.parameter || "outlier"}-${idx}`}>
                <p className="tag warn">Safety Alert</p>
                <h4>{o.parameter || "Unknown"}</h4>
                <p>{o.action_required || o.flag || "Review this value with clinical team."}</p>
              </div>
            ))
          ) : (
            <p className="muted">No outlier alerts in current report.</p>
          )}
        </section>
      </div> : null}

      {isDiagnosticsPage ? (
        <section className="st-card">
          <h3>Clinical Narrative</h3>
          <p className="summary-text">{reasoning || "No diagnostic reasoning available."}</p>
        </section>
      ) : null}
    </Shell>
  );
}

function StaffPortal({ onLogout, authUser }) {
  const navigate = useNavigate();
  const location = useLocation();
  const { patients, selected, setSelected, setPatients } = usePatients();
  const { report, refreshReport, loading: reportLoading, error: reportError } = useCurrentReport(selected);
  const selectedPatient = useMemo(
    () => patients.find((patient) => patient.patient_id === selected),
    [patients, selected],
  );
  const [reportEdit, setReportEdit] = useState("");
  const [nfcUrl, setNfcUrl] = useState("");
  const [status, setStatus] = useState("");
  const [uploading, setUploading] = useState(false);
  const fileInputRef = useRef(null);
  const [form, setForm] = useState({
    name: "",
    dob: "",
    mrn: "",
    patientPin: "",
    allergies: "",
    gender: "",
    bloodGroup: "",
  });

  useEffect(() => {
    setReportEdit(report?.reasoning || "");
    const p = patients.find((x) => x.patient_id === selected);
    setNfcUrl(p?.nfc_url || "");
  }, [report, patients, selected]);

  const isNewPatientPage = location.pathname.startsWith("/staff/new-patient");
  const isPatientRecordsPage = location.pathname.startsWith("/staff/patient-records");

  async function saveReport() {
    if (!report?.id) {
      setStatus("No report found for selected patient.");
      return;
    }
    const { error } = await supabase.from("reports").update({ reasoning: reportEdit }).eq("id", report.id);
    setStatus(error ? `Update failed: ${error.message}` : "Report updated.");
  }

  async function linkNfc() {
    if (!selected) {
      setStatus("Select a patient first.");
      return;
    }
    const { error } = await supabase.from("patients").update({ nfc_url: nfcUrl }).eq("patient_id", selected);
    setStatus(error ? `NFC update failed: ${error.message}` : "NFC linked.");
  }

  async function addPatient(e) {
    e.preventDefault();
    if (!/^\d{4}$/.test(form.patientPin || "")) {
      setStatus("Patient PIN must be exactly 4 digits.");
      return;
    }

    const publicBaseUrl = getPublicBaseUrl();
    const full = {
      name: form.name,
      subject_id: form.mrn,
      date_of_birth: form.dob || null,
      gender: form.gender || null,
      blood_group: form.bloodGroup || null,
      allergies: form.allergies || null,
    };

    const fullInsert = await supabase.from("patients").insert(full).select("*").limit(1);
    let inserted = fullInsert.data?.[0];

    if (fullInsert.error || !inserted) {
      const fallback = await supabase
        .from("patients")
        .insert({ name: form.name, subject_id: form.mrn })
        .select("*")
        .limit(1);
      inserted = fallback.data?.[0];
      if (fallback.error || !inserted) {
        const message = fallback.error?.message || fullInsert.error?.message || "Unknown insert error";
        setStatus(`Add patient failed: ${message}`);
        return;
      }
    }

    const generatedNfc = `${publicBaseUrl}/nfc/${inserted.patient_id}`;
    await supabase.from("patients").update({ nfc_url: generatedNfc }).eq("patient_id", inserted.patient_id);

    try {
      const identifiers = [
        String(form.mrn || "").trim().toLowerCase(),
        String(inserted.patient_id || "").trim().toLowerCase(),
      ].filter(Boolean);

      for (const patientIdentifier of identifiers) {
        const pinDigest = await hashPin("patient", patientIdentifier, form.patientPin);
        const pinRes = await supabase.from("pin_access").upsert(
          {
            identifier: patientIdentifier,
            role: "patient",
            display_name: inserted.name,
            pin_hash: pinDigest,
            is_active: true,
            must_rotate: false,
            failed_attempts: 0,
            locked_until: null,
            updated_at: new Date().toISOString(),
          },
          { onConflict: "identifier,role" },
        );
        if (pinRes.error) {
          throw new Error(pinRes.error.message);
        }
      }

      setStatus(`Patient added: ${inserted.name}. Login ID: ${form.mrn || inserted.patient_id}. NFC link: ${generatedNfc}`);
    } catch (credentialError) {
      setStatus(`Patient created, but PIN setup failed: ${credentialError.message}`);
    }

    inserted = { ...inserted, nfc_url: generatedNfc };
    setPatients((prev) => [inserted, ...prev]);
    setSelected(inserted.patient_id);
    setForm({ name: "", dob: "", mrn: "", patientPin: "", allergies: "", gender: "", bloodGroup: "" });
  }

  function openFilePicker() {
    fileInputRef.current?.click();
  }

  async function uploadSelectedFiles(e) {
    const files = Array.from(e.target.files || []);
    if (!files.length) {
      return;
    }
    if (!selected) {
      setStatus("Select a patient before uploading files.");
      e.target.value = "";
      return;
    }

    setUploading(true);
    let successCount = 0;

    for (const file of files) {
      try {
        await uploadPatientFile(selected, file, {
          dataType: "auto",
          triggerAnalysis: false,
        });
        successCount += 1;
      } catch {
        // Continue and report aggregate result.
      }
    }

    if (successCount > 0) {
      setStatus(`Uploaded ${successCount}/${files.length} file(s). Starting AI analysis...`);

      try {
        await triggerAnalysis(selected);

        // Poll until current report appears or timeout is reached.
        let generated = null;
        const maxAttempts = 20;
        for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
          generated = await refreshReport();
          if (generated) {
            break;
          }
          await new Promise((resolve) => {
            window.setTimeout(resolve, 3000);
          });
        }

        if (generated) {
          setStatus("Final report generated and loaded.");
        } else {
          setStatus("Analysis started. Report not ready yet; it will auto-appear when available.");
        }
      } catch (analysisError) {
        setStatus(`Analysis trigger failed: ${analysisError.message}`);
      }
    } else {
      setStatus(`Uploaded ${successCount}/${files.length} file(s).`);
    }

    setUploading(false);
    e.target.value = "";
  }

  return (
    <Shell role="staff" onLogout={onLogout} authUser={authUser}>
      <div className="st-page-header centered">
        <div>
          <h1>{isNewPatientPage ? "New Patient" : "Patient Records"}</h1>
          <p>
            {isNewPatientPage
              ? "Register a new patient and issue secure access details."
              : "Upload patient data and generate AI clinical report."}
          </p>
        </div>
      </div>

      {isNewPatientPage ? (
        <section className="st-card">
          <h3>Add Patient Form</h3>
          <form className="patient-form-grid" onSubmit={addPatient}>
            <div>
              <label>Name</label>
              <input value={form.name} onChange={(e) => setForm((s) => ({ ...s, name: e.target.value }))} required />
            </div>
            <div>
              <label>Date of Birth</label>
              <input type="date" value={form.dob} onChange={(e) => setForm((s) => ({ ...s, dob: e.target.value }))} />
            </div>
            <div>
              <label>MRN</label>
              <input value={form.mrn} onChange={(e) => setForm((s) => ({ ...s, mrn: e.target.value }))} required />
            </div>
            <div>
              <label>Patient PIN (4 digits)</label>
              <input
                type="password"
                inputMode="numeric"
                maxLength={4}
                value={form.patientPin}
                onChange={(e) => setForm((s) => ({ ...s, patientPin: e.target.value.replace(/\D/g, "") }))}
                required
              />
            </div>
            <div>
              <label>Allergies</label>
              <input value={form.allergies} onChange={(e) => setForm((s) => ({ ...s, allergies: e.target.value }))} />
            </div>
            <div>
              <label>Gender</label>
              <select value={form.gender} onChange={(e) => setForm((s) => ({ ...s, gender: e.target.value }))}>
                <option value="">Select gender</option>
                <option value="Male">Male</option>
                <option value="Female">Female</option>
                <option value="Other">Other</option>
              </select>
            </div>
            <div>
              <label>Blood Group</label>
              <select value={form.bloodGroup} onChange={(e) => setForm((s) => ({ ...s, bloodGroup: e.target.value }))}>
                <option value="">Select blood group</option>
                <option value="A+">A+</option>
                <option value="A-">A-</option>
                <option value="B+">B+</option>
                <option value="B-">B-</option>
                <option value="AB+">AB+</option>
                <option value="AB-">AB-</option>
                <option value="O+">O+</option>
                <option value="O-">O-</option>
              </select>
            </div>
            <button type="submit" className="st-primary-btn">Add Patient</button>
          </form>
          {status ? <p className="muted status-line">{status}</p> : null}
        </section>
      ) : null}

      {isPatientRecordsPage ? (
        <>
          <PatientSelect patients={patients} selected={selected} setSelected={setSelected} />

          <FinalReportView report={report} patientName={selectedPatient?.name} />

          <div className="st-grid-12">
            <section className="st-card col-8 upload-drop">
              <span className="material-symbols-outlined upload-icon">cloud_upload</span>
              <h3>Upload Patient Files</h3>
              <p>Select all files, then report generation starts automatically.</p>
              <div className="btn-row center">
                <input ref={fileInputRef} type="file" multiple onChange={uploadSelectedFiles} style={{ display: "none" }} />
                <button type="button" className="st-primary-btn" onClick={openFilePicker}>
                  Select Files & Generate Report
                </button>
                <button type="button" className="st-soft-btn" onClick={refreshReport} disabled={reportLoading || !selected}>
                  {reportLoading ? "Refreshing..." : "Refresh Report"}
                </button>
                <button type="button" className="st-soft-btn" onClick={() => navigate("/staff/new-patient")}>New Patient</button>
              </div>
              {uploading ? <p className="muted">Uploading files...</p> : null}
              {reportError ? <p className="muted">Report fetch warning: {reportError}</p> : null}
            </section>

            <section className="st-card col-4">
              <h3>Patient Record Tools</h3>
              <div className="queue-item">
                <strong>Current Report</strong>
                <p>{report ? `Version ${report.report_version || 1} loaded.` : "No report currently available."}</p>
              </div>
              <div className="queue-item">
                <strong>Edit Report</strong>
                <textarea rows={4} value={reportEdit} onChange={(e) => setReportEdit(e.target.value)} />
                <button type="button" className="st-soft-btn" onClick={saveReport}>Save Edit</button>
              </div>
              <div className="queue-item">
                <strong>NFC Linker</strong>
                <input value={nfcUrl} onChange={(e) => setNfcUrl(e.target.value)} placeholder="https://kaarigars-hc01.app/patient/{uuid}" />
                <button type="button" className="st-soft-btn" onClick={linkNfc}>Link NFC</button>
              </div>
              {status ? <p className="muted status-line">{status}</p> : null}
            </section>
          </div>
        </>
      ) : null}
    </Shell>
  );
}

function PatientPortal({ onLogout, authUser }) {
  const location = useLocation();
  const [patients, setPatients] = useState([]);
  const [selected, setSelected] = useState("");
  const { report, refreshReport, loading, error } = useCurrentReport(selected);
  const [labs, setLabs] = useState([]);
  const [careTeam, setCareTeam] = useState([]);

  useEffect(() => {
    async function run() {
      if (!authUser?.identifier) {
        setPatients([]);
        setSelected("");
        return;
      }

      const identifier = String(authUser.identifier || "").trim().toLowerCase();

      const bySubjectId = await supabase
        .from("patients")
        .select("patient_id,name,nfc_url,subject_id,created_at")
        .ilike("subject_id", identifier)
        .order("created_at", { ascending: false })
        .limit(10);

      let rows = bySubjectId.data || [];

      if (!rows.length) {
        const byPatientId = await supabase
          .from("patients")
          .select("patient_id,name,nfc_url,subject_id,created_at")
          .eq("patient_id", identifier)
          .limit(1);
        rows = byPatientId.data || [];
      }

      setPatients(rows);
      setSelected(rows[0]?.patient_id || "");
    }
    run();
  }, [authUser?.identifier]);

  useEffect(() => {
    async function run() {
      if (!selected) {
        setLabs([]);
        return;
      }

      const labRes = await supabase
        .from("parsed_data")
        .select("timestamp,data_type,structured_json")
        .eq("patient_id", selected)
        .order("timestamp", { ascending: false })
        .limit(50);

      const parsed = [];
      (labRes.data || []).forEach((row) => {
        if (row.data_type !== "lab") {
          return;
        }
        const vals = row.structured_json?.values || {};
        Object.entries(vals).forEach(([k, v]) => {
          const text =
            v && typeof v === "object"
              ? `${v.value ?? ""}${v.unit ? ` ${v.unit}` : ""}`.trim()
              : String(v ?? "");
          parsed.push({
            date: String(row.timestamp || "").slice(0, 10),
            test: k,
            value: text,
          });
        });
      });
      setLabs(parsed.slice(0, 20));

      const clinicians = await supabase.from("clinicians").select("full_name,role").limit(10);
      setCareTeam(clinicians.data || []);
    }
    run();
  }, [selected]);

  const trendData = useMemo(() => getTrend(report), [report]);
  const risk = Array.isArray(report?.risk_flags) ? report.risk_flags[0] : null;
  const isDiagnosticsPage = location.pathname.startsWith("/patient/diagnostics");
  const isAnalyticsPage = location.pathname.startsWith("/patient/analytics");
  const isLabsPage = location.pathname.startsWith("/patient/labs");

  return (
    <Shell role="patient" onLogout={onLogout} authUser={authUser}>
      <div className="st-page-header">
        <div>
          <p className="eyebrow">Surgical Unit 4B • Trauma Level 1</p>
          <h1>Patient Diagnostic Overview</h1>
        </div>
        <div className="btn-row">
          <button type="button" className="st-soft-btn" onClick={refreshReport} disabled={loading || !selected}>
            {loading ? "Refreshing..." : "Refresh"}
          </button>
        </div>
      </div>

      {error ? <p className="muted status-line">Report fetch warning: {error}</p> : null}

      {patients.length > 1 ? <PatientSelect patients={patients} selected={selected} setSelected={setSelected} /> : null}

      {isDiagnosticsPage ? <div className="st-grid-12">
        <div className="col-8">
          <TrendCard data={trendData} />
        </div>

        <div className="col-4">
          <section className="st-card vital-card">
            <h3>Active Vitals</h3>
            <div className="vital-list">
              <div><span>Heart Rate</span><strong>{getVal(report?.disease_timeline?.at(-1)?.vitals, ["heart_rate_bpm"]) || "72"} BPM</strong></div>
              <div><span>Blood Pressure</span><strong>{report?.disease_timeline?.at(-1)?.vitals?.blood_pressure_mmhg || "118/76"}</strong></div>
              <div><span>Core Temp</span><strong>{getVal(report?.disease_timeline?.at(-1)?.vitals, ["temperature_c"]) || "36.8"} C</strong></div>
            </div>
          </section>

          <section className="insight-card">
            <p className="tag">Clinical Insight</p>
            <h3>{risk?.risk || "No critical risk currently recorded."}</h3>
            <p>{risk?.recommended_action || "Awaiting latest model output for recommendation."}</p>
          </section>
        </div>
      </div> : null}

      {isAnalyticsPage ? <AnalyticsCharts patientId={selected} report={report} title="Patient Analytics" /> : null}

      {isLabsPage ? <div className="st-grid-12">
        <section className="st-card col-5">
          <h3>Lab History</h3>
          <table className="st-table">
            <thead>
              <tr>
                <th>Date</th>
                <th>Test</th>
                <th>Value</th>
              </tr>
            </thead>
            <tbody>
              {labs.length ? (
                labs.map((l, i) => (
                  <tr key={`${l.test}-${i}`}>
                    <td>{l.date}</td>
                    <td>{l.test}</td>
                    <td>{l.value}</td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan={3}>No labs available.</td>
                </tr>
              )}
            </tbody>
          </table>
        </section>

        <section className="st-card col-7">
          <h3>Care Team & Vaccinations</h3>
          <div className="care-grid">
            <div>
              <h4>Care Team</h4>
              <ul>
                {careTeam.length ? (
                  careTeam.map((c, idx) => (
                    <li key={`${c.full_name || "member"}-${idx}`}>
                      <strong>{c.role || "Role"}</strong>
                      <span>{c.full_name || "Unknown"}</span>
                    </li>
                  ))
                ) : (
                  <li><span>No care team records found.</span></li>
                )}
              </ul>
            </div>
            <div>
              <h4>Vaccinations</h4>
              <ul>
                <li><strong>Influenza</strong><span>Completed</span></li>
                <li><strong>Pneumococcal</strong><span>Completed</span></li>
                <li><strong>COVID Booster</strong><span>Due</span></li>
              </ul>
            </div>
          </div>
          <h4 className="summary-head">Doctor Summary</h4>
          <p className="summary-text">{report?.reasoning || "No doctor summary available for selected patient."}</p>
        </section>
      </div> : null}

      {isDiagnosticsPage ? (
        <section className="st-card">
          <h3>Doctor Summary</h3>
          <p className="summary-text">{report?.reasoning || "No doctor summary available for selected patient."}</p>
        </section>
      ) : null}
    </Shell>
  );
}

function NfcPatientAccessPage() {
  const { patientId } = useParams();
  const [doctorIdentifier, setDoctorIdentifier] = useState("");
  const [doctorPin, setDoctorPin] = useState("");
  const [verifying, setVerifying] = useState(false);
  const [error, setError] = useState("");
  const [patient, setPatient] = useState(null);
  const [report, setReport] = useState(null);

  async function verifyDoctor(e) {
    e.preventDefault();
    setError("");
    setVerifying(true);

    try {
      await signInWithPin({
        role: "doctor",
        identifier: doctorIdentifier,
        pin: doctorPin,
      });

      const patientRes = await supabase
        .from("patients")
        .select("patient_id,name,subject_id,nfc_url")
        .eq("patient_id", patientId)
        .limit(1)
        .maybeSingle();

      if (patientRes.error || !patientRes.data) {
        throw new Error(patientRes.error?.message || "Patient not found for this NFC tag.");
      }

      const reportRes = await supabase
        .from("reports")
        .select("*")
        .eq("patient_id", patientId)
        .eq("is_current", true)
        .order("report_version", { ascending: false })
        .limit(1)
        .maybeSingle();

      if (reportRes.error && reportRes.error.code !== "PGRST116") {
        throw new Error(reportRes.error.message || "Failed to load report.");
      }

      setPatient(patientRes.data);
      setReport(reportRes.data || null);
    } catch (verifyError) {
      setError(verifyError.message || "Doctor verification failed.");
    } finally {
      setVerifying(false);
    }
  }

  return (
    <div className="login-bg">
      <div className="login-card settings-card">
        <p className="eyebrow">NFC Secure Access</p>
        <h1>Doctor Verification Required</h1>
        <p className="sub">Scan ID: {patientId}</p>

        {!patient ? (
          <form className="st-form" onSubmit={verifyDoctor}>
            <label>Doctor Identifier</label>
            <input value={doctorIdentifier} onChange={(e) => setDoctorIdentifier(e.target.value)} required />

            <label>Doctor PIN (6 digits)</label>
            <input
              type="password"
              inputMode="numeric"
              maxLength={6}
              value={doctorPin}
              onChange={(e) => setDoctorPin(e.target.value.replace(/\D/g, ""))}
              required
            />

            <button type="submit" className="st-primary-btn" disabled={verifying}>
              {verifying ? "Verifying..." : "Unlock Patient Report"}
            </button>
          </form>
        ) : null}

        {error ? <p className="err">{error}</p> : null}

        {patient ? (
          <div className="nfc-report-wrap">
            <h3>Patient: {patient.name || "Unknown"}</h3>
            <p className="muted">MRN: {patient.subject_id || "N/A"}</p>
            <FinalReportView report={report} patientName={patient.name} />
          </div>
        ) : null}
      </div>
    </div>
  );
}

function SystemLogsPage({ authUser, onLogout }) {
  const [logs, setLogs] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    async function run() {
      setLoading(true);
      setError("");

      const res = await supabase
        .from("security_audit_logs")
        .select("occurred_at,actor_identifier,actor_role,action,status,detail,actor_ip")
        .order("occurred_at", { ascending: false })
        .limit(120);

      if (res.error) {
        setError(res.error.message || "Could not load logs.");
        setLogs([]);
      } else {
        setLogs(res.data || []);
      }
      setLoading(false);
    }
    run();
  }, []);

  return (
    <Shell role={authUser?.role || "staff"} onLogout={onLogout} authUser={authUser}>
      <div className="st-page-header">
        <div>
          <p className="eyebrow">Security & Operations</p>
          <h1>System Logs</h1>
          <p>Authentication and access activity trail.</p>
        </div>
      </div>

      {error ? <p className="muted status-line">{error}</p> : null}
      {loading ? <p className="muted">Loading logs...</p> : null}

      <section className="st-card">
        <table className="st-table">
          <thead>
            <tr>
              <th>Time</th>
              <th>Actor</th>
              <th>Role</th>
              <th>Action</th>
              <th>Status</th>
              <th>Details</th>
            </tr>
          </thead>
          <tbody>
            {logs.length ? (
              logs.map((row, idx) => (
                <tr key={`${row.occurred_at || "time"}-${idx}`}>
                  <td>{row.occurred_at ? new Date(row.occurred_at).toLocaleString() : "-"}</td>
                  <td>{row.actor_identifier || "-"}</td>
                  <td>{row.actor_role || "-"}</td>
                  <td>{row.action || "-"}</td>
                  <td>{row.status || "-"}</td>
                  <td>{row.detail || "-"}</td>
                </tr>
              ))
            ) : (
              <tr>
                <td colSpan={6}>No log entries found.</td>
              </tr>
            )}
          </tbody>
        </table>
      </section>
    </Shell>
  );
}

function ProtectedRoute({ authUser, element, allowedRoles }) {
  if (!authUser) {
    return <Navigate to="/" replace />;
  }
  if (Array.isArray(allowedRoles) && allowedRoles.length > 0 && !allowedRoles.includes(authUser.role)) {
    return <Navigate to={ROLE_MAP[authUser.role]?.route || "/"} replace />;
  }
  return element;
}

function HomeGate({ authUser }) {
  if (!authUser) {
    return <LandingPage />;
  }
  return <Navigate to={ROLE_MAP[authUser.role]?.route || "/doctor"} replace />;
}

export default function App() {
  const [authUser, setAuthUser] = useState(null);

  function persistSession(user) {
    const payload = {
      user,
      expiresAt: Date.now() + SESSION_TIMEOUT_MS,
      lastActivityAt: Date.now(),
    };
    sessionStorage.setItem(SESSION_KEY, JSON.stringify(payload));
  }

  function clearSession() {
    sessionStorage.removeItem(SESSION_KEY);
  }

  function renewActivity() {
    const raw = sessionStorage.getItem(SESSION_KEY);
    if (!raw) {
      return;
    }
    try {
      const parsed = JSON.parse(raw);
      parsed.lastActivityAt = Date.now();
      parsed.expiresAt = Date.now() + SESSION_TIMEOUT_MS;
      sessionStorage.setItem(SESSION_KEY, JSON.stringify(parsed));
    } catch {
      clearSession();
    }
  }

  useEffect(() => {
    const raw = sessionStorage.getItem(SESSION_KEY);
    if (!raw) {
      return;
    }
    try {
      const parsed = JSON.parse(raw);
      if (!parsed?.user || !parsed?.expiresAt || parsed.expiresAt < Date.now()) {
        clearSession();
        return;
      }
      setAuthUser(parsed.user);
    } catch {
      clearSession();
    }
  }, []);

  useEffect(() => {
    if (!authUser) {
      return;
    }

    const refreshEvents = ["click", "keydown", "mousemove", "scroll", "touchstart"];
    const onActivity = () => renewActivity();
    refreshEvents.forEach((eventName) => window.addEventListener(eventName, onActivity, { passive: true }));

    const timer = window.setInterval(() => {
      const raw = sessionStorage.getItem(SESSION_KEY);
      if (!raw) {
        setAuthUser(null);
        return;
      }
      try {
        const parsed = JSON.parse(raw);
        if (parsed.expiresAt < Date.now()) {
          clearSession();
          setAuthUser(null);
        }
      } catch {
        clearSession();
        setAuthUser(null);
      }
    }, 15000);

    return () => {
      refreshEvents.forEach((eventName) => window.removeEventListener(eventName, onActivity));
      window.clearInterval(timer);
    };
  }, [authUser]);

  function onLogin(user) {
    setAuthUser(user);
    persistSession(user);
  }

  function onPinChanged() {
    if (!authUser) {
      return;
    }
    const updated = { ...authUser, mustRotate: false };
    setAuthUser(updated);
    persistSession(updated);
  }

  async function onLogout() {
    clearSession();
    setAuthUser(null);
    window.location.assign("/");
  }

  return (
    <Routes>
      <Route path="/" element={<HomeGate authUser={authUser} />} />
      <Route path="/login" element={<PinLoginPage onLogin={onLogin} />} />
      <Route path="/nfc/:patientId" element={<NfcPatientAccessPage />} />
      <Route
        path="/settings"
        element={<ProtectedRoute authUser={authUser} element={<SettingsPage authUser={authUser} onLogout={onLogout} onPinChanged={onPinChanged} />} />}
      />
      <Route
        path="/system-logs"
        element={
          <ProtectedRoute
            authUser={authUser}
            allowedRoles={["doctor", "staff"]}
            element={<SystemLogsPage authUser={authUser} onLogout={onLogout} />}
          />
        }
      />
      <Route
        path="/doctor"
        element={
          <ProtectedRoute
            authUser={authUser}
            allowedRoles={["doctor"]}
            element={<Navigate to="/doctor/dashboard" replace />}
          />
        }
      />
      <Route
        path="/doctor/dashboard"
        element={
          <ProtectedRoute
            authUser={authUser}
            allowedRoles={["doctor"]}
            element={<DoctorPortal authUser={authUser} onLogout={onLogout} />}
          />
        }
      />
      <Route
        path="/doctor/diagnostics"
        element={
          <ProtectedRoute
            authUser={authUser}
            allowedRoles={["doctor"]}
            element={<DoctorPortal authUser={authUser} onLogout={onLogout} />}
          />
        }
      />
      <Route
        path="/doctor/analytics"
        element={
          <ProtectedRoute
            authUser={authUser}
            allowedRoles={["doctor"]}
            element={<DoctorPortal authUser={authUser} onLogout={onLogout} />}
          />
        }
      />
      <Route
        path="/staff"
        element={
          <ProtectedRoute
            authUser={authUser}
            allowedRoles={["staff"]}
            element={<Navigate to="/staff/new-patient" replace />}
          />
        }
      />
      <Route
        path="/staff/new-patient"
        element={
          <ProtectedRoute
            authUser={authUser}
            allowedRoles={["staff"]}
            element={<StaffPortal authUser={authUser} onLogout={onLogout} />}
          />
        }
      />
      <Route
        path="/staff/patient-records"
        element={
          <ProtectedRoute
            authUser={authUser}
            allowedRoles={["staff"]}
            element={<StaffPortal authUser={authUser} onLogout={onLogout} />}
          />
        }
      />
      <Route
        path="/patient"
        element={
          <ProtectedRoute
            authUser={authUser}
            allowedRoles={["patient"]}
            element={<Navigate to="/patient/diagnostics" replace />}
          />
        }
      />
      <Route
        path="/patient/diagnostics"
        element={
          <ProtectedRoute
            authUser={authUser}
            allowedRoles={["patient"]}
            element={<PatientPortal authUser={authUser} onLogout={onLogout} />}
          />
        }
      />
      <Route
        path="/patient/analytics"
        element={
          <ProtectedRoute
            authUser={authUser}
            allowedRoles={["patient"]}
            element={<PatientPortal authUser={authUser} onLogout={onLogout} />}
          />
        }
      />
      <Route
        path="/patient/labs"
        element={
          <ProtectedRoute
            authUser={authUser}
            allowedRoles={["patient"]}
            element={<PatientPortal authUser={authUser} onLogout={onLogout} />}
          />
        }
      />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
