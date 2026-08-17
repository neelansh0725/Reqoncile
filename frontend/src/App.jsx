/** Reqoncile UI (T061-T062, FR15). */
import { useEffect, useRef, useState } from "react";
import { analyze, health, uploadResume } from "./api";
import {
  EligibilityChecklist, ErroredList, RequirementSections, Rewrites, ScoreHeader,
} from "./components";

export default function App() {
  const [jdText, setJdText] = useState("");
  const [resumeText, setResumeText] = useState("");
  const [status, setStatus] = useState("idle");   // idle | uploading | running | done | error
  const [error, setError] = useState(null);
  const [result, setResult] = useState(null);
  const [service, setService] = useState(null);
  const [elapsed, setElapsed] = useState(0);
  const fileInput = useRef(null);

  useEffect(() => {
    health().then(setService).catch(() => setService({ status: "unreachable" }));
  }, []);

  // A run can take 20-90s (docs/latency.md). A spinner with no elapsed time
  // reads as "hung" long before the request is actually slow.
  useEffect(() => {
    if (status !== "running") return;
    setElapsed(0);
    const started = Date.now();
    const id = setInterval(() => setElapsed(Math.round((Date.now() - started) / 1000)), 1000);
    return () => clearInterval(id);
  }, [status]);

  async function onUpload(event) {
    const file = event.target.files?.[0];
    if (!file) return;
    setStatus("uploading");
    setError(null);
    try {
      const { text, characters, lines } = await uploadResume(file);
      setResumeText(text);
      setStatus("idle");
      setService((s) => ({ ...s, lastUpload: `${file.name} — ${characters} chars, ${lines} lines` }));
    } catch (e) {
      setError(e.message);
      setStatus("error");
    } finally {
      if (fileInput.current) fileInput.current.value = "";
    }
  }

  async function onAnalyze(event) {
    event.preventDefault();
    setStatus("running");
    setError(null);
    setResult(null);
    try {
      setResult(await analyze({ jdText, resumeText }));
      setStatus("done");
    } catch (e) {
      setError(e.message);
      setStatus("error");
    }
  }

  const canRun = jdText.trim() && resumeText.trim() && status !== "running" && status !== "uploading";
  const report = result?.report;

  return (
    <div className="page">
      <header className="masthead">
        <h1>Reqoncile</h1>
        <p className="tagline">
          Where your resume already matches a job description, where it under-sells you,
          and where the gaps genuinely are.
        </p>
        {service && (
          <p className={`service ${service.status !== "ok" ? "service-bad" : ""}`}>
            API: {service.status}
            {service.reasoning_tier && ` · reasoning ${service.reasoning_tier} · generation ${service.generation_tier}`}
          </p>
        )}
      </header>

      <form className="inputs" onSubmit={onAnalyze}>
        <div className="field">
          <label htmlFor="jd">Job description</label>
          <textarea
            id="jd" value={jdText} onChange={(e) => setJdText(e.target.value)}
            placeholder="Paste the full job description…" rows={14} spellCheck={false}
          />
          <span className="hint">{jdText.length.toLocaleString()} characters</span>
        </div>

        <div className="field">
          <label htmlFor="resume">Your resume</label>
          <textarea
            id="resume" value={resumeText} onChange={(e) => setResumeText(e.target.value)}
            placeholder="Paste your resume, or upload a PDF below…" rows={14} spellCheck={false}
          />
          <div className="hint row">
            <span>{resumeText.length.toLocaleString()} characters</span>
            <label className="upload">
              <input ref={fileInput} type="file" accept=".pdf,.txt,.md" onChange={onUpload} />
              {status === "uploading" ? "Extracting…" : "Upload PDF"}
            </label>
          </div>
          {service?.lastUpload && <span className="hint muted">Extracted from {service.lastUpload} — check it before analysing.</span>}
        </div>

        <div className="actions">
          <button type="submit" disabled={!canRun}>
            {status === "running" ? `Analysing… ${elapsed}s` : "Analyse"}
          </button>
          {status === "running" && (
            <span className="hint muted">
              One model call per requirement, paced to the free-tier quota — a longer job
              description takes proportionally longer.
            </span>
          )}
        </div>
      </form>

      {status === "error" && (
        <div className="error" role="alert">
          <strong>That didn’t work.</strong>
          <p>{error}</p>
        </div>
      )}

      {report && (
        <main className="report">
          <ScoreHeader report={report} />
          <p className="timings muted">
            Completed in {result.total_seconds}s ·{" "}
            {Object.entries(result.timings).map(([k, v]) => `${k} ${v}s`).join(" · ")}
          </p>
          <RequirementSections report={report} />
          <Rewrites rewrites={report.rewrites} />
          <EligibilityChecklist items={report.eligibility} />
          <ErroredList items={report.errored} />
          <details className="raw">
            <summary>Full report as Markdown</summary>
            <pre>{result.markdown}</pre>
          </details>
        </main>
      )}
    </div>
  );
}
