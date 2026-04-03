import { supabase } from "./supabase";

const CREDENTIAL_TABLE = "pin_access";
const AUDIT_TABLE = "security_audit_logs";
const MAX_ATTEMPTS = 5;
const LOCK_MINUTES = 15;

export const ROLE_MAP = {
  patient: { label: "Patient", pinLength: 4, route: "/patient" },
  doctor: { label: "Doctor", pinLength: 6, route: "/doctor" },
  staff: { label: "Entry Staff", pinLength: 6, route: "/staff" },
};

function nowIso() {
  return new Date().toISOString();
}

function lockUntilIso() {
  return new Date(Date.now() + LOCK_MINUTES * 60 * 1000).toISOString();
}

function toHex(buffer) {
  const bytes = new Uint8Array(buffer);
  return Array.from(bytes)
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

export function requiredPinLength(role) {
  return ROLE_MAP[role]?.pinLength || 6;
}

export function normalizeIdentifier(identifier) {
  return String(identifier || "").trim().toLowerCase();
}

export async function hashPin(role, identifier, pin) {
  const payload = `${role}:${normalizeIdentifier(identifier)}:${String(pin || "")}`;
  const data = new TextEncoder().encode(payload);
  const digest = await crypto.subtle.digest("SHA-256", data);
  return toHex(digest);
}

async function writeAudit(entry) {
  try {
    await supabase.from(AUDIT_TABLE).insert(entry);
  } catch {
    // Do not block auth flow on audit logging failures.
  }
}

export async function signInWithPin({ role, identifier, pin, actorIp = null }) {
  const normalizedRole = role;
  const normalizedIdentifier = normalizeIdentifier(identifier);
  const pinLength = requiredPinLength(normalizedRole);

  if (!ROLE_MAP[normalizedRole]) {
    throw new Error("Invalid role selected.");
  }
  if (!/^\d+$/.test(String(pin || "")) || String(pin).length !== pinLength) {
    throw new Error(`${ROLE_MAP[normalizedRole].label} PIN must be exactly ${pinLength} digits.`);
  }

  const fetchCredential = async (idValue) =>
    supabase
      .from(CREDENTIAL_TABLE)
      .select("id,identifier,role,pin_hash,display_name,must_rotate,failed_attempts,locked_until,last_login_at")
      .eq("role", normalizedRole)
      .eq("identifier", idValue)
      .eq("is_active", true)
      .limit(1)
      .maybeSingle();

  let lookup = await fetchCredential(normalizedIdentifier);

  // Patient convenience fallback: if user typed MRN but credential was stored by UUID,
  // or typed UUID but credential exists by MRN, resolve through patients table.
  if ((!lookup.data || lookup.error) && normalizedRole === "patient") {
    const bySubject = await supabase
      .from("patients")
      .select("patient_id,subject_id")
      .ilike("subject_id", normalizedIdentifier)
      .limit(1)
      .maybeSingle();

    if (!bySubject.error && bySubject.data?.patient_id) {
      const fallbackByPatientId = await fetchCredential(normalizeIdentifier(bySubject.data.patient_id));
      if (!fallbackByPatientId.error && fallbackByPatientId.data) {
        lookup = fallbackByPatientId;
      }
    }

    if ((!lookup.data || lookup.error) && /^[0-9a-f-]{32,36}$/i.test(normalizedIdentifier)) {
      const byPatientId = await supabase
        .from("patients")
        .select("patient_id,subject_id")
        .eq("patient_id", normalizedIdentifier)
        .limit(1)
        .maybeSingle();

      if (!byPatientId.error && byPatientId.data?.subject_id) {
        const fallbackBySubject = await fetchCredential(normalizeIdentifier(byPatientId.data.subject_id));
        if (!fallbackBySubject.error && fallbackBySubject.data) {
          lookup = fallbackBySubject;
        }
      }
    }
  }

  if (lookup.error) {
    throw new Error(`Authentication system error: ${lookup.error.message}`);
  }
  if (!lookup.data) {
    await writeAudit({
      actor_identifier: normalizedIdentifier,
      actor_role: normalizedRole,
      action: "LOGIN_FAILED",
      status: "FAIL",
      detail: "Credential not found",
      actor_ip: actorIp,
      occurred_at: nowIso(),
    });
    throw new Error("Credential not found. Contact administrator to provision access.");
  }

  const record = lookup.data;
  if (record.locked_until && new Date(record.locked_until).getTime() > Date.now()) {
    await writeAudit({
      actor_identifier: normalizedIdentifier,
      actor_role: normalizedRole,
      action: "LOGIN_LOCKED",
      status: "DENY",
      detail: `Locked until ${record.locked_until}`,
      actor_ip: actorIp,
      occurred_at: nowIso(),
    });
    throw new Error(`Account is temporarily locked until ${new Date(record.locked_until).toLocaleTimeString()}.`);
  }

  const attemptedHash = await hashPin(normalizedRole, normalizedIdentifier, pin);
  if (attemptedHash !== record.pin_hash) {
    const failedAttempts = Number(record.failed_attempts || 0) + 1;
    const shouldLock = failedAttempts >= MAX_ATTEMPTS;

    await supabase
      .from(CREDENTIAL_TABLE)
      .update({
        failed_attempts: failedAttempts,
        locked_until: shouldLock ? lockUntilIso() : null,
        updated_at: nowIso(),
      })
      .eq("id", record.id);

    await writeAudit({
      actor_identifier: normalizedIdentifier,
      actor_role: normalizedRole,
      action: "LOGIN_FAILED",
      status: "FAIL",
      detail: shouldLock ? "Max attempts reached; account locked" : "PIN mismatch",
      actor_ip: actorIp,
      occurred_at: nowIso(),
    });

    throw new Error(shouldLock ? "Too many failed attempts. Account locked for 15 minutes." : "Invalid PIN.");
  }

  await supabase
    .from(CREDENTIAL_TABLE)
    .update({
      failed_attempts: 0,
      locked_until: null,
      last_login_at: nowIso(),
      updated_at: nowIso(),
    })
    .eq("id", record.id);

  await writeAudit({
    actor_identifier: normalizedIdentifier,
    actor_role: normalizedRole,
    action: "LOGIN_SUCCESS",
    status: "OK",
    detail: "PIN login successful",
    actor_ip: actorIp,
    occurred_at: nowIso(),
  });

  return {
    id: record.id,
    role: normalizedRole,
    identifier: normalizedIdentifier,
    displayName: record.display_name || normalizedIdentifier,
    mustRotate: Boolean(record.must_rotate),
    route: ROLE_MAP[normalizedRole].route,
  };
}

export async function changePin({ authUser, currentPin, newPin, actorIp = null }) {
  if (!authUser?.id || !authUser?.role || !authUser?.identifier) {
    throw new Error("Not authenticated.");
  }

  const pinLength = requiredPinLength(authUser.role);
  if (!/^\d+$/.test(String(newPin || "")) || String(newPin).length !== pinLength) {
    throw new Error(`New PIN must be exactly ${pinLength} digits.`);
  }

  const recordRes = await supabase
    .from(CREDENTIAL_TABLE)
    .select("id,pin_hash")
    .eq("id", authUser.id)
    .limit(1)
    .maybeSingle();

  if (recordRes.error || !recordRes.data) {
    throw new Error("Credential record not found.");
  }

  const currentHash = await hashPin(authUser.role, authUser.identifier, currentPin);
  if (currentHash !== recordRes.data.pin_hash) {
    await writeAudit({
      actor_identifier: authUser.identifier,
      actor_role: authUser.role,
      action: "PIN_CHANGE",
      status: "FAIL",
      detail: "Current PIN mismatch",
      actor_ip: actorIp,
      occurred_at: nowIso(),
    });
    throw new Error("Current PIN is incorrect.");
  }

  const newHash = await hashPin(authUser.role, authUser.identifier, newPin);
  if (newHash === currentHash) {
    throw new Error("New PIN must be different from current PIN.");
  }

  const update = await supabase
    .from(CREDENTIAL_TABLE)
    .update({
      pin_hash: newHash,
      must_rotate: false,
      failed_attempts: 0,
      locked_until: null,
      pin_changed_at: nowIso(),
      updated_at: nowIso(),
    })
    .eq("id", authUser.id);

  if (update.error) {
    throw new Error(`PIN update failed: ${update.error.message}`);
  }

  await writeAudit({
    actor_identifier: authUser.identifier,
    actor_role: authUser.role,
    action: "PIN_CHANGE",
    status: "OK",
    detail: "PIN changed successfully",
    actor_ip: actorIp,
    occurred_at: nowIso(),
  });
}
