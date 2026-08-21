/**
 * API client (T060).
 *
 * Base URL is relative in dev so Vite's proxy handles it (one origin, no
 * preflight on every analyse call); override with VITE_API_BASE to point at a
 * server elsewhere.
 */
const BASE = import.meta.env.VITE_API_BASE ?? "/api";

/**
 * FastAPI returns errors as {detail: ...}, where detail is a string for our
 * own HTTPExceptions and an array of validation objects for 422s. Flatten
 * both into one readable line so callers never render "[object Object]".
 */
async function readError(response) {
  let detail;
  try {
    const body = await response.json();
    detail = body?.detail ?? body;
  } catch {
    detail = await response.text().catch(() => "");
  }
  if (Array.isArray(detail)) {
    return detail
      .map((d) => `${(d.loc ?? []).slice(1).join(".") || "request"}: ${d.msg}`)
      .join("; ");
  }
  if (typeof detail === "object" && detail !== null) return JSON.stringify(detail);
  return detail || `${response.status} ${response.statusText}`;
}

async function request(path, options = {}) {
  let response;
  try {
    response = await fetch(`${BASE}${path}`, options);
  } catch (cause) {
    // fetch only rejects on network failure, so this is "server unreachable"
    // rather than "server said no" -- worth distinguishing for the user.
    throw new Error(
      "Could not reach the Reqoncile API. Is it running? (./scripts/serve.sh)",
      { cause },
    );
  }
  if (!response.ok) throw new Error(await readError(response));
  return response.json();
}

export const health = () => request("/health");

export const analyze = ({ jdText, resumeText, includeRewrites = true, includeSummary = true }) =>
  request("/analyze", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      jd_text: jdText,
      resume_text: resumeText,
      include_rewrites: includeRewrites,
      include_summary: includeSummary,
    }),
  });

/** Rank 2-3 JDs against one resume (FR17-FR20). */
export const compare = ({ jds, resumeText, includeRewrites = false }) =>
  request("/compare", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      jds: jds.map(({ label, text }) => ({ label, jd_text: text })),
      resume_text: resumeText,
      include_rewrites: includeRewrites,
    }),
  });

/** Interview questions for a completed run's gaps (FR21-FR23). */
export const interviewPrep = (runId, limit = 5) =>
  request(`/interview-prep/${encodeURIComponent(runId)}?limit=${limit}`, {
    method: "POST",
  });

/** Diff two resume versions against one JD (FR24-FR27). */
export const diffVersions = ({ jdText, resumeBefore, resumeAfter }) =>
  request("/diff", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      jd_text: jdText,
      resume_before: resumeBefore,
      resume_after: resumeAfter,
    }),
  });

/**
 * PDF/text -> extracted text. One endpoint for both document types.
 *
 * `kind` only changes the wording of an error ("job description" vs
 * "resume"); extraction itself is identical, so there is no second code path
 * to keep in step with this one.
 */
export const uploadDocument = (file, kind = "resume") => {
  const form = new FormData();
  form.append("file", file);
  form.append("kind", kind);
  return request("/upload-resume", { method: "POST", body: form });
};

export const uploadResume = (file) => uploadDocument(file, "resume");

export const fetchTrace = (runId) => request(`/trace/${encodeURIComponent(runId)}`);
