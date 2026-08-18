/** Reqoncile UI (T061-T062, FR15). */
import { useEffect, useRef, useState } from "react";
import { analyze, compare, diffVersions, health, interviewPrep, uploadResume } from "./api";
import {
  ComparisonView, EligibilityChecklist, ErroredList, InterviewPrepPanel,
  RequirementSections, Rewrites, ScoreHeader, VersionDiffView,
} from "./components";

export default function App() {
  const [mode, setMode] = useState("analyse");    // analyse | compare
  const [jdText, setJdText] = useState("");
  // Compare mode holds its own JD slots so switching modes does not discard
  // what was already typed into the other one.
  const [jds, setJds] = useState([
    { label: "Job 1", text: "" },
    { label: "Job 2", text: "" },
  ]);
  const [resumeText, setResumeText] = useState("");
  const [status, setStatus] = useState("idle");   // idle | uploading | running | done | error
  const [error, setError] = useState(null);
  const [result, setResult] = useState(null);
  const [service, setService] = useState(null);
  const [elapsed, setElapsed] = useState(0);
  // Diff mode keeps its own second resume so switching modes preserves input.
  const [resumeAfter, setResumeAfter] = useState("");
  const [prep, setPrep] = useState(null);
  const [prepStatus, setPrepStatus] = useState("idle");
  const [prepError, setPrepError] = useState(null);
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
    setPrep(null);
    setPrepStatus("idle");
    setPrepError(null);
    try {
      setResult(await analyze({ jdText, resumeText }));
      setStatus("done");
    } catch (e) {
      setError(e.message);
      setStatus("error");
    }
  }

  async function onDiff(event) {
    event.preventDefault();
    setStatus("running");
    setError(null);
    setResult(null);
    try {
      setResult(await diffVersions({
        jdText, resumeBefore: resumeText, resumeAfter,
      }));
      setStatus("done");
    } catch (e) {
      setError(e.message);
      setStatus("error");
    }
  }

  async function onPrepare() {
    setPrepStatus("preparing");
    setPrepError(null);
    try {
      setPrep(await interviewPrep(result.report.run_id));
      setPrepStatus("done");
    } catch (e) {
      setPrepError(e.message);
      setPrepStatus("error");
    }
  }

  async function onCompare(event) {
    event.preventDefault();
    setStatus("running");
    setError(null);
    setResult(null);
    try {
      setResult(await compare({ jds: filledJds, resumeText }));
      setStatus("done");
    } catch (e) {
      setError(e.message);
      setStatus("error");
    }
  }

  function updateJd(index, patch) {
    setJds((current) => current.map((jd, i) => (i === index ? { ...jd, ...patch } : jd)));
  }

  const busy = status === "running" || status === "uploading";
  const canDiff = jdText.trim() && resumeText.trim() && resumeAfter.trim()
    && resumeText.trim() !== resumeAfter.trim() && !busy;
  const filledJds = jds.filter((jd) => jd.text.trim() && jd.label.trim());
  const canCompare = filledJds.length >= 2 && resumeText.trim() && !busy;
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

      <nav className="modes" role="tablist" aria-label="Mode">
        <button
          type="button" role="tab" aria-selected={mode === "analyse"}
          className={mode === "analyse" ? "mode on" : "mode"}
          onClick={() => { setMode("analyse"); setResult(null); setStatus("idle"); }}
        >
          Analyse one job
        </button>
        <button
          type="button" role="tab" aria-selected={mode === "compare"}
          className={mode === "compare" ? "mode on" : "mode"}
          onClick={() => { setMode("compare"); setResult(null); setStatus("idle"); }}
        >
          Compare up to 3
        </button>
        <button
          type="button" role="tab" aria-selected={mode === "diff"}
          className={mode === "diff" ? "mode on" : "mode"}
          onClick={() => { setMode("diff"); setResult(null); setStatus("idle"); }}
        >
          Compare two resume drafts
        </button>
      </nav>

      <form className="inputs" onSubmit={mode === "compare" ? onCompare : mode === "diff" ? onDiff : onAnalyze}>
        {mode === "analyse" ? (
          <div className="field">
            <label htmlFor="jd">Job description</label>
            <textarea
              id="jd" value={jdText} onChange={(e) => setJdText(e.target.value)}
              placeholder="Paste the full job description…" rows={14} spellCheck={false}
            />
            <span className="hint">{jdText.length.toLocaleString()} characters</span>
          </div>
        ) : (
          <div className="field jd-slots">
            <label>Job descriptions</label>
            {jds.map((jd, i) => (
              <div className="jd-slot" key={i}>
                <div className="row">
                  <input
                    className="jd-label" value={jd.label} maxLength={120}
                    aria-label={`Name for job ${i + 1}`}
                    onChange={(e) => updateJd(i, { label: e.target.value })}
                  />
                  {jds.length > 2 && (
                    <button
                      type="button" className="link"
                      onClick={() => setJds((c) => c.filter((_, j) => j !== i))}
                    >
                      Remove
                    </button>
                  )}
                </div>
                <textarea
                  value={jd.text} rows={8} spellCheck={false}
                  placeholder={`Paste job description ${i + 1}…`}
                  onChange={(e) => updateJd(i, { text: e.target.value })}
                />
              </div>
            ))}
            {jds.length < 3 && (
              <button
                type="button" className="link"
                onClick={() => setJds((c) => [...c, { label: `Job ${c.length + 1}`, text: "" }])}
              >
                + Add another job description
              </button>
            )}
            <span className="hint muted">
              Each job costs one model call per requirement, so comparing three takes
              roughly three times as long as analysing one. Rewrites are skipped here —
              run a single analysis on whichever job you pick.
            </span>
          </div>
        )}

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

        {mode === "diff" && (
          <div className="field">
            <label htmlFor="resume-after">Your revised resume</label>
            <textarea
              id="resume-after" value={resumeAfter} rows={14} spellCheck={false}
              placeholder="Paste the newer version…"
              onChange={(e) => setResumeAfter(e.target.value)}
            />
            <span className="hint muted">
              The job description is parsed once and the same requirements are used for both
              versions — otherwise extraction noise would look like progress.
            </span>
          </div>
        )}

        <div className="actions">
          <button
            type="submit"
            disabled={mode === "compare" ? !canCompare : mode === "diff" ? !canDiff : !canRun}
          >
            {status === "running"
              ? `${{ compare: "Comparing", diff: "Diffing" }[mode] ?? "Analysing"}… ${elapsed}s`
              : mode === "compare" ? `Compare ${filledJds.length || ""} jobs`.trim()
              : mode === "diff" ? "Compare drafts" : "Analyse"}
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

      {mode === "compare" && result?.result && (
        <>
          <ComparisonView result={result.result} labels={result.labels} />
          <details className="raw">
            <summary>Full comparison as Markdown</summary>
            <pre>{result.markdown}</pre>
          </details>
        </>
      )}

      {mode === "diff" && result?.diff && (
        <>
          <VersionDiffView diff={result.diff} />
          <details className="raw">
            <summary>Full diff as Markdown</summary>
            <pre>{result.markdown}</pre>
          </details>
        </>
      )}

      {mode === "analyse" && report && (
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
          <InterviewPrepPanel
            report={report} onPrepare={onPrepare} prep={prep}
            status={prepStatus} error={prepError}
          />
          <details className="raw">
            <summary>Full report as Markdown</summary>
            <pre>{result.markdown}</pre>
          </details>
        </main>
      )}
    </div>
  );
}
