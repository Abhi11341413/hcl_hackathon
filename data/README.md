# Hybrid seed dataset: Nimbus Group AI portfolio (demo)

Real public data is used wherever it exists. Synthetic values only fill the fields no public source has, which are **usage** (weekly active users, licensed users), **benefits** (realised and planned) and **people** (sponsor and owner names).

## Rebuild

```bash
python -m venv .venv && .venv/Scripts/pip install -r requirements-data.txt
.venv/Scripts/python scripts/download_sources.py      # ~95 MB into data/raw + data/external
.venv/Scripts/python scripts/build_hybrid_dataset.py  # deterministic (SEED = 20261113)
```

## Folder map (matches the architecture's ingestion layer)

| Folder | Feeds | Ingest in the app? |
|---|---|---|
| `seed/portfolio_register.xlsx`, `seed/usage_weekly.csv`, `seed/financials.xlsx`, `seed/agency_kpis.csv` | Excel / CSV Files → Data Loaders → Cleaning | **Yes** (deliberately messy) |
| `seed/charters/*.pdf` (5) and `*.docx` (5) | PDF / DOCX Charters → Text Extraction → Chunking → ChromaDB | **Yes** |
| `truth/` | Evaluation answer key: clean inputs, expected scorecard, data-quality log, 37 test questions | **No.** Never index this folder |
| `eval/` | External evaluation sets: TAT-QA router sample (300) and prompt-injection set (662) | No (evaluation only) |
| `raw/`, `external/` | Downloaded sources | No (git-ignored) |

## Portfolio (10 initiatives)

| ID | Initiative | Real backbone | Synthetic | Expected status |
|---|---|---|---|---|
| NIM-01 | FSIS Public Health Information System (PHIS) | IT Dashboard: identity, 14 projects + costs, KPIs, CIO reviews, OA | usage, benefits, people | Green |
| NIM-02 | USDA Intelligent Automation CoE | same | same | Green (adoption exactly 60%) |
| NIM-03 | FDA Regulatory Business Information Services | same | same | Amber |
| NIM-04 | CMS Enterprise Portal Services (chatbot) | same, **incl. a real ×1000 cost duplicate** | same + injection line | Red |
| NIM-05 | State Dept Data Analytics CoE | same | same | Red (ROI < 0) |
| NIM-06 | Education DCC / Aidan virtual assistant | same | same | Amber (ROI exactly 0) |
| NIM-07 | CBP Automated Targeting System | same | same | Green |
| NIM-08 | StateChat (GenAI) | AI Use Case Inventory: identity, purpose, outputs, go-live, governance answers | costs, usage, benefits, people | Amber |
| NIM-09 | DHS commercial GenAI chatbot | same | same + injection quote | Red |
| NIM-10 | BLS SOII Autocoder (NLP classifier) | same | same | Green |

## Field provenance

| Field | Source |
|---|---|
| Initiative name, agency, bureau, description | **Real**: IT Dashboard `it_portfolio` / AI Inventory |
| Go-live date | **Real**: earliest completed-project end date (IT Dashboard) or *Date Implemented* (Inventory) |
| Total cost to date | **Real** for NIM-01 to 07 (sum of project `actualCost`, $M); **synthetic** for NIM-08 to 10 |
| Charter sections 1–3, 6–7 (overview, project goals, KPIs, CIO risk reviews, operational analysis) | **Real** |
| Agency KPIs (`agency_kpis.csv`) | **Real** |
| Licensed users, 3 weeks of WAU, realised and planned benefit | **Synthetic**, set so the portfolio has a Green/Amber/Red mix |
| Benefits case, adoption plan, sponsor/owner names (fictional) | **Synthetic** |
| Injection strings | One hand-written; one from deepset/prompt-injections |

Every charter ends with a **Source notes** section that labels each section as real or synthetic.

## Data-quality issues (answer key: `truth/planted_issues.md`)
29 issues: **3 found in the real data** (×1000 cost duplicate, `Percent/percentage/%/Percetnage` unit spellings, mixed KPI reporting periods) and **26 planted**. The planted ones are renamed metrics, IDs with stripped leading zeros, % instead of counts, $K / $M / INR / text-formatted money, a monthly average instead of a cumulative total, a monthly plan, stale and exact duplicates, a negative WAU, an out-of-window week, a year typo, mixed date formats, trailing spaces, 2 charter injections, a charter-vs-spreadsheet conflict and a personal-data trap.

An independent cleaning pass, using only the documented fixes, reproduces `truth/expected_clean_inputs.csv` exactly.

## Assumptions to document (FR-01)
- Months live = whole calendar months from go-live to the reporting date 2026-11-13.
- FX: 1 USD = 84.0 INR, supplied in `financials.xlsx › FX_and_Units`.
- A negative WAU is treated as a sign error.
- Ratios are rounded to 10 dp before threshold tests, so ROI = 0 stays Amber.
- Suggested client clarification question: three CMS EPS projects report costs of only $0.003–0.014M, which may be another unit error ($K entered as $M). Should they be corrected?

## Licences and attribution
- US Federal IT Dashboard data via itspending.us: US public domain.
- OMB 2024 Federal AI Use Case Inventory: US government work. The repo has no LICENSE file; it is presumed public domain.
- TAT-QA: CC BY 4.0 (NExT++).
- deepset/prompt-injections: Apache-2.0 per its dataset card.
