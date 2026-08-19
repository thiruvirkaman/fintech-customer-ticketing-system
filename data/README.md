# Demo data

This directory contains only synthetic, demo-only records. It contains no real customer data and no verified NBFC internal policy.

## Layout

```text
data/
|-- knowledge/
|   |-- manifest.json       Allowlisted source metadata
|   |-- public/             Staging rules for approved public material
|   `-- synthetic/          Demo LOS guidance and playbooks
|-- seeds/
|   |-- customers.json      20 synthetic customer records
|   `-- applications.json   20 linked LOS application records
`-- derived/                Reproducible generated output; ignored by Git
```

## Knowledge contract

Every ingested document must be explicitly listed in `knowledge/manifest.json`. A manifest record contains:

- a unique `document_id`;
- `source_type`, either `SYNTHETIC_INTERNAL` or `PUBLIC_NBFC`;
- a human-readable `source_title`;
- a path contained within this data directory;
- `source_url` for every public document.

The ingestion command validates those fields, rejects paths that escape this directory, reads the Markdown, and emits chunks with retained provenance. Public pages are not downloaded automatically.

```powershell
python -m app.ingestion
python -m app.ingestion --output data/derived/knowledge_chunks.json
```

## Seed contract

The customer and application files are validated together. The contract requires at least 20 of each, unique IDs and customer identifiers, valid application-to-customer links, synthetic classification, parseable timestamps, `example.com` emails, `DEMO_` failure codes, and coverage across all declared LOS states.

```powershell
python -m app.seed_data
```

This command validates and reports the fixtures. It does not write them to PostgreSQL. Database insertion belongs with the future schema and migration implementation, where idempotency and transaction behavior can be defined safely.

## Adding data safely

- Never add real names, contact details, PAN values, account numbers, credentials, or private lender material.
- Use reserved example identities and clearly synthetic identifiers.
- Add public knowledge only after approval, retain its canonical URL, and confirm redistribution rights.
- Keep generated chunks out of source control; regenerate them from the manifest.
- Run the complete test suite after changing any source or seed file.
