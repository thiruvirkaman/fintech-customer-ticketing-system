# Public knowledge staging area

No public NBFC content is bundled yet.

Before adding a public document:

1. Confirm the URL is an approved, customer-facing source.
2. Save an authorized Markdown, PDF, or text representation in this directory.
3. Add it to `data/knowledge/manifest.json` with `source_type` set to `PUBLIC_NBFC`.
4. Preserve the canonical public URL in `source_url`.
5. Record when and how the content was obtained.
6. Run `python -m app.ingestion` to validate and chunk the corpus.

Do not add scraped private pages, authenticated content, real customer data, or invented lender policy.
