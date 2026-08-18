/**
 * Report views (T063-T066).
 *
 * The honesty constraints the pipeline enforces have to survive into the UI,
 * or the report quietly starts over-claiming at the last step:
 *
 *  - Gaps are shown plainly, with no rewrite offered (FR12).
 *  - Eligibility is a separate checklist, never labelled Matched/Weak/Gap and
 *    never scored (T015a) -- the system did not assess these.
 *  - Errored requirements are shown as unassessed, not folded into gaps.
 *  - Every rewrite shows the original line beside it (FR11), and a flagged
 *    rewrite is visibly flagged rather than silently offered.
 */
import { useState } from "react";
import { fetchTrace } from "./api";

const LABELS = {
  matched: { title: "Matched", tone: "ok", blurb: "Your resume clearly evidences these." },
  weak: { title: "Under-communicated", tone: "warn", blurb: "The experience is there, but a reader scanning for these could miss it." },
  gap: { title: "Gaps", tone: "bad", blurb: "Your resume does not evidence these. Stated plainly — no rewrite is offered, because there is nothing to surface." },
};

export function ScoreHeader({ report }) {
  const meaningful = report.score_is_meaningful;
  return (
    <header className="score">
      <div className={`score-dial ${meaningful ? "" : "muted"}`}>
        <span className="score-value">{meaningful ? `${Math.round(report.score)}%` : "—"}</span>
        <span className="score-label">match</span>
      </div>
      <div className="score-detail">
        <p className="score-explanation">{report.score_explanation}</p>
        {report.summary && <p className="summary">{report.summary}</p>}
        {report.warnings?.length > 0 && (
          <ul className="warnings">
            {report.warnings.map((w, i) => <li key={i}>{w}</li>)}
          </ul>
        )}
      </div>
    </header>
  );
}

function RequirementGroup({ label, items, runId }) {
  const meta = LABELS[label];
  return (
    <section className={`group tone-${meta.tone}`}>
      <h3>{meta.title} <span className="count">{items.length}</span></h3>
      {items.length === 0 ? (
        <p className="empty">None.</p>
      ) : (
        <>
          <p className="blurb">{meta.blurb}</p>
          <ul className="requirements">
            {items.map((c, i) => (
              <RequirementRow key={`${c.requirement.name}-${i}`} c={c} runId={runId} />
            ))}
          </ul>
        </>
      )}
    </section>
  );
}

/** One requirement, with its reasoning trace on demand (FR16). */
function RequirementRow({ c, runId }) {
  const [trace, setTrace] = useState(null);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  async function toggle() {
    if (open) return setOpen(false);
    setOpen(true);
    if (trace || busy) return;
    setBusy(true);
    setError(null);
    try {
      const data = await fetchTrace(runId);
      const step = data.steps.find((s) => s.requirement === c.requirement.name);
      setTrace(step ?? { retrieved: [], justification: c.justification });
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <li className="requirement">
      <div className="requirement-head">
        <strong>{c.requirement.name}</strong>
        <span className="tags">
          <span className={`tag ${c.requirement.necessity}`}>{c.requirement.necessity}</span>
          <span className="tag">{c.requirement.category}</span>
        </span>
        <button className="link" onClick={toggle} aria-expanded={open}>
          {open ? "hide reasoning" : "why?"}
        </button>
      </div>
      <p className="justification">{c.justification}</p>

      {open && (
        <div className="trace">
          {busy && <p className="muted">Loading reasoning…</p>}
          {error && <p className="error-inline">Could not load the trace: {error}</p>}
          {trace && (
            <>
              <p className="trace-head">
                Retrieved {trace.retrieved?.length ?? 0} resume excerpt(s), then judged:
              </p>
              <ol className="excerpts">
                {(trace.retrieved ?? []).map((r) => (
                  <li key={r.chunk_id} className={c.evidence_chunk_ids?.includes(r.chunk_id) ? "cited" : ""}>
                    <code>{r.chunk_id}</code>
                    <span className="muted">
                      {" "}{r.section} · line {r.source_line_no} ·{" "}
                      {r.similarity > 0 ? `similarity ${r.similarity.toFixed(3)}` : "keyword match"}
                    </span>
                    <p>{r.text}</p>
                  </li>
                ))}
              </ol>
              {trace.rejected_evidence?.length > 0 && (
                <p className="error-inline">
                  Rejected {trace.rejected_evidence.length} citation(s) the model invented:{" "}
                  {trace.rejected_evidence.join(", ")}
                </p>
              )}
              {trace.repaired && <p className="error-inline">{trace.repaired}</p>}
            </>
          )}
        </div>
      )}
    </li>
  );
}

export function RequirementSections({ report }) {
  const byLabel = (l) => report.classifications.filter((c) => c.label === l);
  return (
    <>
      {["matched", "weak", "gap"].map((l) => (
        <RequirementGroup key={l} label={l} items={byLabel(l)} runId={report.run_id} />
      ))}
    </>
  );
}

/** FR11: the original line is always shown beside the suggestion. */
export function Rewrites({ rewrites }) {
  if (!rewrites?.length) return null;
  return (
    <section className="group tone-warn">
      <h3>Suggested rewrites <span className="count">{rewrites.length}</span></h3>
      <p className="blurb">
        Each suggestion uses only what the original line already says, and shows the
        line it came from.
      </p>
      {rewrites.map((r, i) => (
        <article key={i} className={`rewrite ${r.grounding_flags?.length ? "flagged" : ""}`}>
          <h4>{r.requirement.name}</h4>
          <div className="rewrite-pair">
            <div>
              <span className="rewrite-label">Current <code>{r.source_chunk_id}</code></span>
              <blockquote className="original">{r.original_text}</blockquote>
            </div>
            <div>
              <span className="rewrite-label">Suggested</span>
              <blockquote className="suggested">{r.suggested_text}</blockquote>
            </div>
          </div>
          <p className="rationale">{r.rationale}</p>
          {r.grounding_flags?.length > 0 && (
            <div className="flags">
              <strong>Review before using —</strong> this suggestion may add something the
              original does not support:
              <ul>{r.grounding_flags.map((f, j) => <li key={j}>{f}</li>)}</ul>
            </div>
          )}
        </article>
      ))}
    </section>
  );
}

/** T015a: never scored, never labelled — for the candidate to confirm. */
export function EligibilityChecklist({ items }) {
  if (!items?.length) return null;
  return (
    <section className="group tone-neutral">
      <h3>Eligibility checklist <span className="count">{items.length}</span></h3>
      <p className="blurb">
        These were <strong>not assessed</strong>. A resume cannot reliably evidence work
        authorisation, location or graduation year, so they are listed for you to confirm
        rather than guessed at — and they do not affect the score.
      </p>
      <ul className="checklist">
        {items.map((r, i) => (
          <li key={i}>
            <label><input type="checkbox" /> <strong>{r.name}</strong></label>
            <span className="muted"> — {r.source_text}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

export function ErroredList({ items }) {
  if (!items?.length) return null;
  return (
    <section className="group tone-neutral">
      <h3>Could not assess <span className="count">{items.length}</span></h3>
      <p className="blurb">
        These failed during analysis. They are listed rather than counted as gaps — the
        system did not assess them, so it makes no claim either way.
      </p>
      <ul className="requirements">
        {items.map((c, i) => (
          <li key={i} className="requirement">
            <strong>{c.requirement.name}</strong>
            <p className="justification muted">{c.error}</p>
          </li>
        ))}
      </ul>
    </section>
  );
}


/**
 * Multi-JD comparison result (T076, FR19).
 *
 * Ties are rendered as ties. The system measured that it separates strong
 * fits from weak ones but does not resolve fine-grained rank between similar
 * JDs, so a shared rank is shown as a shared rank rather than broken into an
 * arbitrary order the numbers do not support.
 */
export function ComparisonView({ result, labels }) {
  const { ranking = [], reports = [], overall_note: note, warnings = [] } = result;
  const byLabel = Object.fromEntries(reports.map((r) => [labels[r.run_id], r]));
  const rankedLabels = new Set(ranking.map((r) => r.label));
  const unranked = reports
    .map((r) => labels[r.run_id])
    .filter((label) => !rankedLabels.has(label));

  return (
    <main className="report comparison">
      <h2>Which of these fits best</h2>
      {note && <p className="lede">{note}</p>}

      {ranking.length === 0 && <p className="muted">No ranking was produced.</p>}

      <ol className="ranking">
        {ranking.map((entry) => {
          const report = byLabel[entry.label];
          const scored = report?.score_is_meaningful;
          return (
            <li key={entry.label} className={entry.tied_with?.length ? "ranked tied" : "ranked"}>
              <div className="rank-head">
                <span className="rank-badge">{entry.rank}</span>
                <h3>{entry.label}</h3>
                <span className="rank-score">{scored ? `${Math.round(report.score)}%` : "no score"}</span>
              </div>
              <p className="rank-reason">{entry.reason}</p>
              {report && (
                <p className="rank-counts muted">
                  {report.matched.length} matched · {report.weak.length} under-communicated ·{" "}
                  {report.gaps.length} gaps
                </p>
              )}
              {entry.tied_with?.length > 0 && (
                <p className="rank-tie">
                  Too close to separate from {entry.tied_with.join(", ")} — the order between
                  them is not resolvable, not a judgement that they are identical.
                </p>
              )}
            </li>
          );
        })}
      </ol>

      {unranked.length > 0 && (
        <section className="unranked">
          <h3>Not ranked</h3>
          <p className="muted">
            These produced no classifiable requirements, so they have no score and were
            excluded rather than guessed at.
          </p>
          <ul>{unranked.map((label) => <li key={label}>{label}</li>)}</ul>
        </section>
      )}

      {warnings.length > 0 && (
        <section className="warnings">
          <h3>Notes</h3>
          <ul>{warnings.map((w, i) => <li key={i}>{w}</li>)}</ul>
        </section>
      )}

      <p className="caveat muted">
        Scores are comparable within this run only — requirement counts vary between
        extractions, so each score has its own denominator.
      </p>
    </main>
  );
}


/**
 * Interview prep for gaps (T082, FR21-FR23).
 *
 * Renders notes as *notes* -- what an honest answer must cover -- and says so
 * on the page. The schema already refuses to produce a sample answer; the UI
 * should not imply one is on offer either.
 */
export function InterviewPrepPanel({ report, onPrepare, prep, status, error }) {
  const gapCount = report.gaps.length;
  if (gapCount === 0) return null;

  return (
    <section className="prep">
      <h2>Prepare for the gaps</h2>
      <p className="muted">
        Questions an interviewer could ask about each gap, and what an honest answer would
        need to cover. These are notes to think with — deliberately not answers to memorise.
      </p>

      {!prep && (
        <button type="button" onClick={onPrepare} disabled={status === "preparing"}>
          {status === "preparing"
            ? "Generating…"
            : `Prepare for ${Math.min(gapCount, 5)} gap${gapCount === 1 ? "" : "s"}`}
        </button>
      )}
      {status === "preparing" && (
        <p className="hint muted">
          Runs on the local model — roughly 20 seconds per gap, and the first call also
          waits for the model to load.
        </p>
      )}
      {error && <p className="error-inline">{error}</p>}

      {prep?.prep?.prepared?.map((record) => (
        <article className="prep-gap" key={record.requirement}>
          <h3>{record.requirement}</h3>
          {record.error ? (
            <p className="prep-declined">
              No questions generated for this gap. The draft was rejected rather than
              shown — usually because it drifted into writing an answer for you.
            </p>
          ) : (
            <ol className="prep-questions">
              {record.questions.map((q, i) => (
                <li key={i}>
                  <p className="prep-q">{q.question}</p>
                  <p className="prep-a">
                    <strong>An honest answer covers:</strong> {q.answer_should_cover}
                  </p>
                </li>
              ))}
            </ol>
          )}
        </article>
      ))}

      {prep?.gaps_found > (prep?.prep?.prepared?.length ?? 0) && (
        <p className="hint muted">
          Showing {prep.prep.prepared.length} of {prep.gaps_found} gaps.
        </p>
      )}
    </section>
  );
}


const DIRECTION_META = {
  improved: { label: "Stronger", tone: "up", blurb: "These moved up between versions." },
  regressed: { label: "Weaker", tone: "down",
    blurb: "These moved down. Worth checking whether an edit removed something the earlier version was evidencing." },
  indeterminate: { label: "Not comparable", tone: "unknown",
    blurb: "One version failed to classify these, so no movement can be claimed either way." },
  unchanged: { label: "Unchanged", tone: "same", blurb: "Same verdict in both versions." },
};

/**
 * Version diff (T087, FR26-FR27).
 *
 * The net-improvement line leads, because that is the one thing FR27 asks be
 * readable at a glance. Indeterminate changes get their own group rather than
 * being folded into "unchanged" — no movement observed is not the same fact
 * as no movement.
 */
export function VersionDiffView({ diff }) {
  const groups = ["improved", "regressed", "indeterminate", "unchanged"];
  const byDirection = Object.fromEntries(
    groups.map((g) => [g, diff.changes.filter((c) => c.direction === g)]),
  );

  return (
    <main className="report diffview">
      <h2>What changed between versions</h2>
      <p className="diff-summary">{diff.summary}</p>

      {diff.warnings?.length > 0 && (
        <div className="warnings">
          <ul>{diff.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul>
        </div>
      )}

      {groups.map((g) => {
        const items = byDirection[g];
        if (!items.length) return null;
        const meta = DIRECTION_META[g];
        return (
          <section key={g} className={`diff-group ${meta.tone}`}>
            <h3>{meta.label} ({items.length})</h3>
            <p className="muted">{meta.blurb}</p>
            <ul className="diff-list">
              {items.map((c) => (
                <li key={c.requirement}>
                  <span className="diff-req">{c.requirement}</span>
                  <span className="diff-move">
                    <span className={`chip ${c.before}`}>{c.before}</span>
                    <span aria-hidden="true"> → </span>
                    <span className={`chip ${c.after}`}>{c.after}</span>
                  </span>
                </li>
              ))}
            </ul>
          </section>
        );
      })}
    </main>
  );
}
