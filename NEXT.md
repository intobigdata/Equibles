# NEXT.md — Equibles continuation

*Written August 11, 2026. Replaces prior contents each session. Fork-local ops notes live in `CLAUDE.md`; this file is the active work queue.*

---

## TL;DR — state after this session

1. **Pulled 31 upstream commits** (clean rebase, 18 local commits replayed, now 0 behind). ⚠️ **Fork backup still PENDING** — see *Do this first*.
2. **Problem 1 mitigated locally, not fixed.** `BatchSize` 32 → 512 in `InsiderFilingReprocessManager`. Measured **4.6× faster per accession**; backlog ETA **~28 h → ~6.4 h**. The O(n²) shape is untouched — this only runs the bad query less often.
3. **Problem 2 (577 GB of blobs) untouched** — deliberately deferred this session. Still 100% `StorageProvider='Database'`, DB still 908 GB.

---

## Do this first

✅ Fork pushed 2026-08-12 (`9253704f` → `28be6ee9`, forced update after the rebase).
✅ Upstream issue filed: **[#4374](https://github.com/daniel3303/Equibles/issues/4374)**.

Still uncommitted: `CLAUDE.md`, `InsiderFilingReprocessManager.cs` (the BatchSize deviation), and this file.

---

## Problem 1 — `InsiderFilingReprocessManager` O(n²) reprocess query

### Status: mitigated locally; upstream issue [#4374](https://github.com/daniel3303/Equibles/issues/4374) filed 2026-08-12

`BatchSize` 32 → 512 (`InsiderFilingReprocessManager.cs:55`), marked in-code as
`FORK-LOCAL DEVIATION — do NOT include in an upstream PR`.

### Measured, not predicted (544 s paired window, post-deploy)

| | Before | After |
|---|---:|---:|
| Selection query mean | 4.006 s/call | **13.84 s/call** |
| Accessions per call | 32 | **512.0** (17,920 ÷ 35 — exact) |
| **Cost per accession** | **125.2 ms** | **27.0 ms** |

⚠️ **No DB-CPU claim.** Post-deploy the DB container was observed at both 75% and 126% within
20 minutes, and the fact-reimport / fund-rescore re-enrollments below add concurrent load, so
there is no clean before/after. The defensible metrics are cost-per-accession and 512.0/call.

**Gain is 4.6×, NOT the 16× first estimated.** Correction: the estimate assumed the
selection query costs the same regardless of batch size. It does not — `DISTINCT … LIMIT n`
stops early once *n* distinct values are collected, so a bigger batch scans further into the
table before it can stop. Most of the nominal 16× is eaten by the longer scan.

⚠️ **Expect the per-call cost to keep rising as it drains.** As v5 rows get sparser the scan
must go further to find 512 distinct accessions. ~6.4 h is a floor, not a promise.

Backlog at time of writing: **759,983** distinct accessions pending (from 802,319).

⚠️ **Do not run `SELECT … GROUP BY "ParserVersion"` casually to check progress** — that
verification query itself costs ~15.6 s and ~500 k block reads. Prefer:
`SELECT count(DISTINCT "AccessionNumber") FROM "InsiderTransaction" WHERE "ParserVersion" < 6;`

### Upstream issue — REFRAMED, do not use the old draft

The prior draft said to *lead with the `ChunkDocumentBatch` persisted-cursor precedent*.
**That framing is now wrong.** Upstream's `#4360` (`54675d90`, landed **2026-08-11 — the same
day as this session**, in this pull) rewrote 260 lines of the sibling
`NportFilingReprocessManager` and **deliberately kept the no-cursor design** — the
`// No DB cursor:` comment survived the rewrite, only reworded. Arguing for a persisted cursor
now argues against a choice the maintainer re-affirmed *today*.

**What upstream actually did in #4360 is the template:** it paged the selection query by id,
*"32 per query instead of one ordered query per filing"* — i.e. it attacked the same problem by
**running the expensive selection fewer times**. That is the identical lever to BatchSize, in
the maintainer's own idiom.

Points to make:
1. Evidence: 63,910 s total, 26.7–27.1 B of ~29 B DB-wide `blks_read` (≈89%), 4.0 s mean × ~15.8 k calls.
2. Repro condition is **row count, not config**: 9.08 M `InsiderTransaction` rows, 2.32 M at
   `ParserVersion < 6` (26% ⇒ planner correctly seq-scans 8.65 GB), 759,983 distinct pending.
3. **Acknowledge the deliberate design** — quote the collation comment, do not propose a naive
   keyset. Option A (work-queue table) needs no ordering at all and sidesteps the objection.
4. **Lead with #4360's own paging remedy**, then note that paging alone is sublinear (measured
   4.6× for a 16× batch increase), so it mitigates rather than fixes.
5. Note the sibling `NportFilingReprocessManager` now has the honest attempt ledger but still
   carries the same shape.

---

## Problem 2 — 577 GB of write-only blobs inside Postgres (UNTOUCHED)

Deferred by choice this session. All findings below still verified as of today.

`File`: **8,254,505 rows / 577 GB / 100% `StorageProvider='Database'`**. DB = **908 GB**;
volume 939 GB used of 2.0 TB (**975 GB free inside the VM**, so headroom is not a constraint).

Composition: `image/jpeg` 357 GB (62%), `text/plain` 138 GB (24%), `application/gzip` 65 GB,
`image/gif` 16 GB. Images are 8-K exhibit page renderings, ~7.4/filing, **read by nothing** —
write-side code only, no controller/MCP/view serves image bytes, not in the BM25 index.

**Compression is NOT a lever — measured, do not retry.** pglz 1.10×, lz4 1.19×; ~77% of bytes
are already-compressed formats. Dedup potential only 0.9%. ⚠️ `pg_column_size()` is misleading
here (reports detoasted size) — compare `pg_total_relation_size` on rebuilt tables.

**The fix exists and is disabled:** `src/Equibles.Media.HostedService/FileBackfillWorker.cs`.
Blob-before-row with an fsync barrier; `FileStorageRouter.ReadProvider()` dispatches per row so
migrated and unmigrated blobs stay readable — safe to run live, stop/resume at will. Exclusion
filter is `!(f is Image)` and all rows are `Discriminator='File'`, so all 577 GB is eligible.

```
FileStorage__Enabled=true   FileStorage__RootPath=/data/media   (needs a volume mounted here)
FileBackfill__Enabled=true  FileBackfill__BatchSize=1000  FileBackfill__Concurrency=8
```

⚠️ **Back up first — it deletes `FileContent` rows.** Read, never test-run on this machine.
⚠️ Space is not returned automatically: needs `VACUUM FULL`/`pg_repack` then a Docker disk trim.

Optional follow-on: OCR the ~1.22 M text-poor exhibit images (170 GB) into **its own table**
(`DocumentImageText`) with its own BM25 index — appending to `Chunk` would collide with
`IX_Chunk_DocumentId_Index` (UNIQUE) and corrupt `StartPosition`/`EndPosition` semantics.
**Do not delete the images** (`FK_DocumentImage_File_FileId` is `ON DELETE RESTRICT`; OCR is lossy).

---

## In flight from this pull — watch, don't panic

Two migrations added version columns defaulting to `0` while the code constants are `2`, which
**re-enrolls the corpus for recompute**:

- `AddFinancialFactsImporterVersion` → `FinancialFactsImportService.CurrentImporterVersion = 2`;
  **8,220** `FinancialFactsSyncStatus` rows re-import. This is the *intent* of the fact-quality
  fixes in this pull (`568b517d`, `b9868e56`, `1af22e8f`).
- `VersionFundScorePriceReturnBasis` → `FundScore.CurrentCalculationVersion = 2`; **12,636**
  fund scores rescore. ⚠️ Driven by `FundScoringWorker`, the ~9.9 GB spike worker (~1.7 GB
  margin). Worker was 2.79 GiB and healthy 20 min post-deploy, but this is the OOM risk to watch.

All 6 migrations applied cleanly; web healthy in 29 s.

**`RepairChunkReportingDates` was a false alarm — do not re-investigate.** The planner's
`rows=40583581` is its default selectivity guess for `IS DISTINCT FROM`. **Measured 0 actual
mismatches** (20,937-row scattered sample + 50,000 newest chunks, no NULLs either side). This
deployment's chunks were regenerated after the 2026-07-27 drain and already carry the correct
cast. It scanned and updated nothing.

---

## New, unexplained — low priority

**FINRA short-volume `403 Forbidden`** on `FinraClient.DownloadDailyShortVolumeFile` for
historical days (observed 01/09/2025 and 12/05/2018). **Only 2 occurrences in 10 min** —
sporadic, not systematic. ⚠️ This is **not** the credential-expiry mode `CLAUDE.md` documents
(that is a `400` from `GetAccessToken()`, and the credential is valid to 2027-06-02). Unexplained;
re-check whether it grows before investigating.

---

## Non-problems — do not chase these

- **Memory is not the bottleneck.** Docker VM = 16 GB, deliberately (see `CLAUDE.md`). Raising
  it further is optional, not a fix.
- **The 68.4% cache hit ratio was a bad inference and is retracted.** `track_io_timing` is
  **off**, so there is currently no I/O-time evidence either way. Turn it on before any I/O claim.
- **`shared_buffers` = 128 MB on a 908 GB DB is genuinely undersized** and worth raising to
  ~8 GB — but second-order. Re-measure after the reprocess backlog drains.
- **No hardware needed.** Revisit only for isolation/always-on reasons; do the blob drain first
  so any migration is ~400 GB, not 975 GB.

---

## Verification commands

```bash
# Problem 1 — cheap backlog check (do NOT use the GROUP BY version)
docker exec equibles-db-1 psql -U postgres -d equibles -c \
 "SELECT count(DISTINCT \"AccessionNumber\") FROM \"InsiderTransaction\" WHERE \"ParserVersion\" < 6;"

# Problem 1 — is the reprocess query still dominant?
docker exec equibles-db-1 psql -U postgres -d equibles -c \
 "SELECT round(total_exec_time/1000) total_s, calls, round(mean_exec_time) mean_ms,
         left(regexp_replace(query,'\s+',' ','g'),60) q
  FROM pg_stat_statements ORDER BY total_exec_time DESC LIMIT 5;"

# Problem 2 — drain progress / DB size
docker exec equibles-db-1 psql -U postgres -d equibles -c \
 "SELECT \"StorageProvider\", count(*), pg_size_pretty(sum(\"Size\")) FROM \"File\" GROUP BY 1;"
docker exec equibles-db-1 psql -U postgres -d equibles -c \
 "SELECT pg_size_pretty(pg_database_size('equibles'));"

# Facts, not logs (worker logs WRN+ only — see CLAUDE.md)
docker stats --no-stream
```
