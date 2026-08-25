/** Reqoncile UI (T061-T062, FR15). */
import { useEffect, useRef, useState } from "react";
import { analyze, compare, diffVersions, health, interviewPrep, uploadDocument } from "./api";
import {
  ComparisonView, EligibilityChecklist, ErroredList, InterviewPrepPanel,
  ReportSkeleton, RequirementSections, Rewrites, ScoreHeader, VersionDiffView,
} from "./components";

const MODES = [
  { id: "analyse", label: "Analyse one job" },
  { id: "compare", label: "Compare up to 3" },
  { id: "diff", label: "Compare two resume drafts" },
];

const MODE_LABEL = {
  analyse: "Analysed",
  compare: "Compared",
  diff: "Compared drafts:",
};

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
  // Once results exist the form collapses to a summary: after a wait of a
  // minute or more, scrolling past your own input to reach the answer is the
  // wrong order. Reopening restores it untouched.
  const [inputsOpen, setInputsOpen] = useState(true);
  const [prep, setPrep] = useState(null);
  const [prepStatus, setPrepStatus] = useState("idle");
  const [prepError, setPrepError] = useState(null);
  const fileInput = useRef(null);
  const jdFileInput = useRef(null);
  const resumeAfterFileInput = useRef(null);
  const tabRefs = useRef({});

  function selectMode(id) {
    setMode(id);
    setResult(null);
    setStatus("idle");
    setInputsOpen(true);
  }

  /** Arrow-key navigation, per the WAI-ARIA tabs pattern. */
  function onTabKeyDown(event) {
    const order = MODES.map((m) => m.id);
    const current = order.indexOf(mode);
    const next = {
      ArrowRight: (current + 1) % order.length,
      ArrowLeft: (current - 1 + order.length) % order.length,
      Home: 0,
      End: order.length - 1,
    }[event.key];
    if (next === undefined) return;
    event.preventDefault();
    const id = order[next];
    selectMode(id);
    tabRefs.current[id]?.focus();
  }

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

  /**
   * Extract text from an uploaded PDF into either box.
   *
   * One handler for both, because the backend has one extraction path. The
   * only difference is which box receives the text and which note reports it.
   */
  async function onUpload(event, target = "resume") {
    const file = event.target.files?.[0];
    if (!file) return;
    const kind = target === "jd" ? "jd" : "resume";
    const input = {
      jd: jdFileInput, resume: fileInput, resumeAfter: resumeAfterFileInput,
    }[target];
    setStatus("uploading");
    setError(null);
    try {
      const { text, characters, lines } = await uploadDocument(file, kind);
      const note = `${file.name} (${characters} chars, ${lines} lines)`;
      if (target === "jd") {
        setJdText(text);
        setService((s) => ({ ...s, lastJdUpload: note }));
      } else if (target === "resumeAfter") {
        setResumeAfter(text);
        setService((s) => ({ ...s, lastAfterUpload: note }));
      } else {
        setResumeText(text);
        setService((s) => ({ ...s, lastUpload: note }));
      }
      setStatus("idle");
    } catch (e) {
      setError(e.message);
      setStatus("error");
    } finally {
      if (input.current) input.current.value = "";
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
      setInputsOpen(false);
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
      setInputsOpen(false);
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
      setInputsOpen(false);
    } catch (e) {
      setError(e.message);
      setStatus("error");
    }
  }

  function updateJd(index, patch) {
    setJds((current) => current.map((jd, i) => (i === index ? { ...jd, ...patch } : jd)));
  }

  /** One line describing what was submitted, for the collapsed bar. */
  function summariseInputs() {
    const chars = (s) => `${s.trim().length.toLocaleString()} characters`;
    if (mode === "compare") {
      return `${filledJds.map((jd) => jd.label).join(", ")} against a resume of ${chars(resumeText)}`;
    }
    if (mode === "diff") {
      return `two resume drafts (${chars(resumeText)} and ${chars(resumeAfter)})`;
    }
    return `job description of ${chars(jdText)}, resume of ${chars(resumeText)}`;
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
        {/* Model ids and tier names are operator detail, not user-facing
            product copy. Only a degraded service is worth saying out loud,
            because it changes what the user should expect. */}
        {service && service.status !== "ok" && (
          <p className="service service-bad">
            The analysis service is unavailable, so a run will fail. Status:{" "}
            {service.status}.
          </p>
        )}
      </header>

      <div className="modes" role="tablist" aria-label="Analysis mode">
        {MODES.map(({ id, label }) => (
          <button
            key={id}
            type="button"
            role="tab"
            id={`tab-${id}`}
            aria-selected={mode === id}
            aria-controls="mode-panel"
            // Roving tabindex: the tablist is one stop, arrows move within it.
            tabIndex={mode === id ? 0 : -1}
            ref={(el) => { tabRefs.current[id] = el; }}
            className={mode === id ? "mode on" : "mode"}
            onKeyDown={onTabKeyDown}
            onClick={() => selectMode(id)}
          >
            {label}
          </button>
        ))}
      </div>

      <div id="mode-panel" role="tabpanel" aria-labelledby={`tab-${mode}`}>
      {!inputsOpen && (
        <div className="inputs-collapsed">
          <p>
            <strong>{MODE_LABEL[mode]}</strong>{" "}
            <span className="muted">{summariseInputs()}</span>
          </p>
          <button type="button" className="secondary" onClick={() => setInputsOpen(true)}>
            Edit inputs
          </button>
        </div>
      )}

      <form
        className="inputs"
        hidden={!inputsOpen}
        onSubmit={mode === "compare" ? onCompare : mode === "diff" ? onDiff : onAnalyze}
      >
        {/* Diff compares TWO RESUMES against ONE job description, so it needs
            the single JD field, not the multi-JD slots. Only compare mode
            takes several jobs. Getting this wrong left diff mode with no
            visible JD field at all: the slots write to `jds[]` while onDiff
            submits `jdText`, so the button stayed disabled forever unless
            `jdText` happened to survive from an earlier analyse run. */}
        {mode !== "compare" ? (
          <div className="field">
            <label htmlFor="jd">Job description</label>
            <textarea
              id="jd" value={jdText} onChange={(e) => setJdText(e.target.value)}
              placeholder="Paste the full job description…" rows={14} spellCheck={false}
            />
            <div className="hint row">
              <span>{jdText.length.toLocaleString()} characters</span>
              <label className="upload">
                <input
                  ref={jdFileInput} type="file" accept=".pdf,.txt,.md"
                  onChange={(e) => onUpload(e, "jd")}
                />
                {status === "uploading" ? "Extracting…" : "Upload PDF"}
              </label>
            </div>
            {service?.lastJdUpload && (
              <span className="hint muted">
                Extracted from {service.lastJdUpload}. Check it before analysing.
              </span>
            )}
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
                  // The adjacent input names the job; this labels the body.
                  // A placeholder is not a label: it disappears on first
                  // keystroke and is not announced as one.
                  aria-label={`Text of ${jd.label || `job ${i + 1}`}`}
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
              roughly three times as long as analysing one. Rewrites are skipped here;
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
              <input
                ref={fileInput} type="file" accept=".pdf,.txt,.md"
                onChange={(e) => onUpload(e, "resume")}
              />
              {status === "uploading" ? "Extracting…" : "Upload PDF"}
            </label>
          </div>
          {service?.lastUpload && <span className="hint muted">Extracted from {service.lastUpload}. Check it before analysing.</span>}
        </div>

        {mode === "diff" && (
          <div className="field">
            <label htmlFor="resume-after">Your revised resume</label>
            <textarea
              id="resume-after" value={resumeAfter} rows={14} spellCheck={false}
              placeholder="Paste the newer version…"
              onChange={(e) => setResumeAfter(e.target.value)}
            />
            <div className="hint row">
              <span>{resumeAfter.length.toLocaleString()} characters</span>
              <label className="upload">
                <input
                  ref={resumeAfterFileInput} type="file" accept=".pdf,.txt,.md"
                  onChange={(e) => onUpload(e, "resumeAfter")}
                />
                {status === "uploading" ? "Extracting…" : "Upload PDF"}
              </label>
            </div>
            {service?.lastAfterUpload && (
              <span className="hint muted">
                Extracted from {service.lastAfterUpload}. Check it before analysing.
              </span>
            )}
            <span className="hint muted">
              The job description is parsed once and the same requirements are used for both
              versions, otherwise extraction noise would look like progress.
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
              One model call per requirement, paced to the free-tier quota, so a longer
              job description takes proportionally longer.
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

      </div>

      {/* #12: a run takes minutes. Without this a screen-reader user gets no
          notification that the report they waited for has arrived. */}
      <p className="sr-only" role="status" aria-live="polite">
        {status === "running" ? "Analysis in progress." : ""}
        {status === "done" && result ? "Analysis complete. Results follow." : ""}
      </p>

      {status === "running" && <ReportSkeleton mode={mode} />}

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
          <p className="timings muted">Completed in {Math.round(result.total_seconds)}s.</p>
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
