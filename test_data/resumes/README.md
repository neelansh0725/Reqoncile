# Resumes

**Empty on purpose.** The resume used to build and measure this project is a
real one — it carries a phone number and an email address — so it is
gitignored rather than published. The job descriptions in
`../sample_jds/` are public postings and remain tracked.

## To run the pipeline

Drop a resume here as a PDF and point the CLI at it:

```sh
./.venv/bin/python scripts/run_pipeline.py \
    test_data/sample_jds/mathco_ai_analyst.txt \
    test_data/resumes/<your-resume>.pdf
```

Or upload it through the UI, which extracts the text and shows it to you
before anything is analysed.

## To reproduce the measurements

Two things reference a resume by path and will need yours:

- `test_data/eval_set.json` — the 20-pair labelled classifier eval (T035).
  Its `resume` field points at the original file. **The labels are specific to
  that resume**, so the accuracy figure in `docs/classifier_eval.md` is not
  reproducible against a different one; you would need to re-label.
- `scripts/draft_resume_text.py` — regenerates the ground-truth text fixture
  from a PDF:

  ```sh
  ./.venv/bin/python scripts/draft_resume_text.py test_data/resumes/<your>.pdf
  ```

  It writes `<your>.expected.txt` plus a `.review.md` listing every
  substitution it made, so you can check the extraction before trusting it.
  That fixture is what the T016 extraction test compares against.

Everything that does **not** depend on a specific resume — the free-tier quota
measurements, the retrieval design findings, the fabrication boundary test's
method — is recorded in `docs/`.
