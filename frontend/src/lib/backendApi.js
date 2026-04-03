const API_BASE = (import.meta.env.VITE_BACKEND_URL || "http://localhost:8080").replace(/\/$/, "");

async function readResponse(response) {
  const contentType = response.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    return response.json();
  }
  return response.text();
}

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, options);
  const payload = await readResponse(response);

  if (!response.ok) {
    const detail =
      typeof payload === "object" && payload !== null
        ? payload.detail || JSON.stringify(payload)
        : payload || `Request failed with status ${response.status}`;
    throw new Error(String(detail));
  }

  return payload;
}

export async function uploadPatientFile(patientId, file, opts = {}) {
  const body = new FormData();
  body.append("file", file);
  body.append("data_type", opts.dataType || "auto");
  body.append("trigger_analysis", String(Boolean(opts.triggerAnalysis)));

  return request(`/upload/${patientId}`, {
    method: "POST",
    body,
  });
}

export async function triggerAnalysis(patientId) {
  return request("/reports/analyse", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ patient_id: patientId }),
  });
}

export async function fetchCurrentReport(patientId) {
  return request(`/reports/${patientId}/current`);
}

export { API_BASE };
