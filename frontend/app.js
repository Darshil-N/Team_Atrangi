function byId(id) {
  return document.getElementById(id);
}

function showResult(elementId, data) {
  const el = byId(elementId);
  if (typeof data === "string") {
    el.textContent = data;
    return;
  }
  el.textContent = JSON.stringify(data, null, 2);
}

function apiBase() {
  return byId("baseUrl").value.trim().replace(/\/$/, "");
}

function isUuid(value) {
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value);
}

function currentPatientId() {
  return byId("patientId").value.trim();
}

async function triggerFinalReport(patientId) {
  const res = await fetch(`${apiBase()}/reports/analyse`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ patient_id: patientId }),
  });
  const payload = await res.json();
  return { ok: res.ok, payload };
}

async function fetchCurrentReport(patientId) {
  const res = await fetch(`${apiBase()}/reports/${patientId}/current`, {
    method: "GET",
  });
  const payload = await res.json();
  return { ok: res.ok, payload };
}

byId("patientForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  showResult("patientResult", "Creating patient...");

  const body = {
    name: byId("patientName").value.trim(),
  };
  const subjectId = byId("subjectId").value.trim();
  if (subjectId) {
    body.subject_id = subjectId;
  }

  try {
    const res = await fetch(`${apiBase()}/patients/`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });

    const payload = await res.json();
    if (!res.ok) {
      showResult("patientResult", payload);
      return;
    }

    showResult("patientResult", payload);
    if (payload.patient_id) {
      byId("patientId").value = payload.patient_id;
    }
  } catch (err) {
    showResult("patientResult", `Request failed: ${err}`);
  }
});

byId("uploadForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  showResult("uploadResult", "Uploading files...");

  const patientId = currentPatientId();
  const dataType = byId("dataType").value;
  const files = Array.from(byId("fileInput").files || []);
  const deferAnalysis = byId("deferAnalysis").checked;

  if (!isUuid(patientId)) {
    showResult(
      "uploadResult",
      "Invalid patient ID. Create a patient first or paste a valid UUID (example: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx)."
    );
    return;
  }

  if (files.length === 0) {
    showResult("uploadResult", "Select one or more files first.");
    return;
  }

  try {
    const uploadResults = [];

    for (let i = 0; i < files.length; i += 1) {
      const form = new FormData();
      form.append("file", files[i]);
      form.append("data_type", dataType);
      form.append("trigger_analysis", deferAnalysis ? "false" : "true");

      showResult("uploadResult", `Uploading ${i + 1}/${files.length}: ${files[i].name}`);
      const res = await fetch(`${apiBase()}/upload/${patientId}`, {
        method: "POST",
        body: form,
      });
      const payload = await res.json();
      uploadResults.push({ file: files[i].name, ok: res.ok, response: payload });
    }

    if (deferAnalysis) {
      showResult("uploadResult", {
        uploaded_files: files.length,
        mode: "deferred_analysis",
        next_step: "Click 'Generate Final Report' or wait and fetch current report after trigger.",
        uploads: uploadResults,
      });
    } else {
      showResult("uploadResult", {
        uploaded_files: files.length,
        mode: "per_upload_analysis",
        uploads: uploadResults,
      });
    }
  } catch (err) {
    showResult("uploadResult", `Request failed: ${err}`);
  }
});

byId("triggerReportBtn").addEventListener("click", async () => {
  const patientId = currentPatientId();
  if (!isUuid(patientId)) {
    showResult("reportResult", "Invalid patient ID. Create a patient first or paste a valid UUID.");
    return;
  }

  showResult("reportResult", "Triggering final report generation...");
  try {
    const result = await triggerFinalReport(patientId);
    showResult("reportResult", result.payload);
  } catch (err) {
    showResult("reportResult", `Request failed: ${err}`);
  }
});

byId("fetchReportBtn").addEventListener("click", async () => {
  const patientId = currentPatientId();
  if (!isUuid(patientId)) {
    showResult("reportResult", "Invalid patient ID. Create a patient first or paste a valid UUID.");
    return;
  }

  showResult("reportResult", "Fetching current report...");
  try {
    const result = await fetchCurrentReport(patientId);
    showResult("reportResult", result.payload);
  } catch (err) {
    showResult("reportResult", `Request failed: ${err}`);
  }
});
