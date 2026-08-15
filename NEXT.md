# NEXT.md — Equibles continuation

*Written August 15, 2026. Replaces prior contents each session. Fork-local ops notes live in `CLAUDE.md`; this file is the active work queue.*

---

## TL;DR — state after this session

1. **Problem 1 is FIXED UPSTREAM and deployed locally.** Issue [#4374](https://github.com/daniel3303/Equibles/issues/4374) → `4ac6e726` (PR #4386), ~22 h turnaround. Verified on this box: the selection went from **8.47 M rows / 8.05 M buffers / 7,819 ms** to **64 rows / 26 buffers / 0.095 ms**. The fork-local `BatchSize` deviation is **reverted**; that file is byte-identical to upstream again.
2. **Pulled 24 upstream commits** (clean rebase, 20 local commits replayed, 0 behind), fork pushed, stack rebuilt, 4 migrations applied.
3. **Problem 2 (577 GB of blobs) still untouched** — the only large open item. Still 100% `StorageProvider='Database'`.

---

## Do this first

Nothing blocking. Problem 2 below is the next substantive piece of work.

---

## Problem 1 — reprocess selection — ✅ RESOLVED, no action needed

**Fixed upstream by `4ac6e726` (PR #4386), deployed here 2026-08-15.** Kept as the reference
case for how this fork's report → fix loop worked, and because the *shape* recurs.

### What the problem was

**Symptom:** `equibles-db-1` pinned at ~100–116% CPU (one full core) continuously for weeks,
with ~54 TB read / ~24.8 TB written of cumulative container block I/O. Nothing was visibly
broken — no errors, no crash, no data loss — the box was just permanently busy, and the insider
reprocess backlog barely moved. Worker logs showed nothing because the container emits **WRN and
above only**, and the reprocess progress lines are `LogInformation`.

**How it was found:** `pg_stat_statements`, not logs. One query accounted for **~89% of all
block reads database-wide** (26.7 B of 29.1 B), 16.9 h of cumulative execution, 4.0 s mean ×
~15.8 k calls — roughly 12× the next-most-expensive query.

**The query** (`InsiderFilingReprocessManager.Run`) selected work with a cursorless
`DISTINCT … LIMIT`:

```csharp
.Where(t => t.ParserVersion < InsiderTransaction.CurrentParserVersion)   // range predicate
.Select(t => t.AccessionNumber).Distinct().Take(BatchSize)
```

**Mechanism:** to satisfy `DISTINCT … LIMIT` with early termination the planner walked
`IX_InsiderTransaction_AccessionNumber_TransactionOrder` (which supplies the ordering), then
applied `ParserVersion` as a **post-index `Filter`** because that column is absent from the
index. Every already-processed row was read and discarded before the scan reached pending work
— **8,473,803 rows discarded (~93% of the table) to produce one 512-accession batch.** With no
cursor this restarted from scratch every batch, so total work scaled with corpus size, not
batch size.

**Scale:** 9.08 M `InsiderTransaction` rows / 8,798 MB; 802,319 distinct accessions pending at
peak; upstream `BatchSize = 32` ⇒ ~25,000 such re-reads queued (~28 h of DB time).

⚠️ **Two of my own early calls here were wrong, both corrected by measurement — worth
remembering as failure modes:**
1. The original diagnosis said the planner *seq-scanned* because the predicate matched ~26% of
   rows. `EXPLAIN` showed an **index scan with a post-filter** instead. The distinction mattered:
   the real fix is about which column is in the ordering index, not about scan type.
2. I predicted raising `BatchSize` 32→512 would give ~16× (batch ratio). **Measured 4.6×**, decaying
   toward ~1.6× — a larger `DISTINCT … LIMIT n` walks further before it can stop, so the
   selection cost rises with batch size and eats most of the nominal gain. That mitigation was
   later reverted once upstream fixed the query.

### The fix

The fix is a composite `(ParserVersion, AccessionNumber)` index **plus** the code change that
makes it usable: the loop takes `MinAsync` of pending versions then filters
`ParserVersion == oldest` — an **equality**, not a range — so the leading column is a single
seek and `Unique` + `Limit` stream in `AccessionNumber` order without a sort.

⚠️ **The index alone would NOT have fixed it.** `ParserVersion < 6` spans several values, so a
composite index orders `AccessionNumber` only *within* each version. The original issue draft
proposed the index without the equality rewrite; a `/codex` review caught the gap before
filing, and the issue shipped with that limitation stated rather than glossed. Upstream then
closed it properly. **Lesson: when proposing an index for a `DISTINCT … LIMIT`, check whether
the predicate is an equality on the leading column — if it is a range, the ordering does not
survive.**

Verified after deploy:

| | Before | After |
|---|---:|---:|
| Access path | Index Scan + post-`Filter` | **Index Only Scan**, `Index Cond` |
| Rows examined | 8,473,867 | **64** |
| Buffers | 8,046,802 | **26** |
| Execution time | 7,819.825 ms | **0.095 ms** |

Index `IX_InsiderTransaction_ParserVersion_AccessionNumber`, 190 MB, built `CONCURRENTLY`,
`indisvalid = t`. Backlog fully drained beforehand (0 rows below current parser version;
9,083,252 rows all at v6, total *up* 689 from ingest — no data was ever lost).

⚠️ **Cheap backlog check** (do NOT use a `GROUP BY ParserVersion` — that costs ~15 s and
~500 k block reads):
`SELECT count(*) FROM "InsiderTransaction" WHERE "ParserVersion" < 6;`

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

## In flight — watch, don't panic

**From the 2026-08-15 pull** (4 migrations, all applied cleanly; web healthy in 19 s):
`OptimizeInsiderReprocessSelection` (the #4374 index, built `CONCURRENTLY`, valid),
`AddStockQuarterlyListingActivity` (new table), `BackfillHistoricalTickerAliases`
(hardcoded 21-row insert, not a sweep), `AddYahooEnrichmentCheckpoint` (one `CommonStock`
column). None heavy. No new `.env` gate in this pull — the short-data estimate feature
(`452d234d`) is an unregistered interface (`IShortInterestEstimateSource`), not a config knob.

**Carried over from the 2026-08-11 pull** — two version bumps re-enrolled the corpus:

- Financial-facts re-import — ✅ **COMPLETE** (8,220/8,220 at `ImporterVersion = 2`).
- Fund rescore — 🔄 **still draining**: 7,460 at `CalculationVersion = 2`, **2,803 still at 0**
  (was 6,288 pending on 2026-08-12). ⚠️ Driven by `FundScoringWorker`, the ~9.9 GB spike worker
  (~1.7 GB margin). No OOM observed across four days, but it is the standing memory risk.

**`RepairChunkReportingDates` was a false alarm — do not re-investigate.** The planner's
`rows=40583581` is its default selectivity guess for `IS DISTINCT FROM`. **Measured 0 actual
mismatches** (20,937-row scattered sample + 50,000 newest chunks, no NULLs either side). This
deployment's chunks were regenerated after the 2026-07-27 drain and already carry the correct
cast. It scanned and updated nothing.

---

## New, unexplained — low priority

**FINRA short-volume `403 Forbidden`** on `FinraClient.DownloadDailyShortVolumeFile` for
historical days (first seen 2026-08-11 on 01/09/2025 and 12/05/2018). **Persistent but low-rate:
~2 occurrences per 10–15 min, unchanged on 2026-08-15 across four days and two full redeploys.**
Not growing, so still low priority — but it is *not* transient, so "wait and see" has now been
tried and answered. ⚠️ This is **not** the credential-expiry mode `CLAUDE.md` documents (that is a
`400` from `GetAccessToken()`, and the credential is valid to 2027-06-02). Next step if it ever
matters: capture which dates fail and whether FINRA simply has no file for them (a 403 on a
non-existent archive object would explain a permanent, harmless low rate).

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
