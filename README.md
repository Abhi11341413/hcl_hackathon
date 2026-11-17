# Enterprise RAG Value Intelligence Assistant: HCLTech Hackathon, Use Case 2b

A governed AI-portfolio scorecard plus a grounded assistant and weekly report.
**Code computes the numbers, retrieval finds the text, the LLM only explains.**

## Setup (Windows PowerShell)
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .streamlit\secrets.toml.example .streamlit\secrets.toml   # then add your keys
streamlit run app.py
pytest -q
```
On the home page, click **Build / refresh data**. It cleans `data/seed/`, writes the SQLite scorecard and builds the ChromaDB charter index.

## Team workflow
- Each member works on their own branch and edits only the files they own.
- Shared files (`app.py`, `src/contracts.py`, `src/config.py`, `requirements.txt`, ...) change only on `main`. Request changes in `docs/requests/<Mx>.md`.
- Modules talk only through public functions and the Pydantic models in `src/contracts.py`. `tests/<module>/test_contract_*.py` fails if a signature drifts.

## Data
`data/seed/` holds the hybrid dataset the app ingests: real US federal IT/AI records plus synthetic usage and benefits, with deliberate data-quality issues. `data/truth/` is the answer key used for tests and evaluation; never index it. Provenance and licences are in [data/README.md](data/README.md).

To regenerate the dataset (optional; the outputs are committed):
```powershell
pip install -r requirements-data.txt
python scripts/download_sources.py
python scripts/build_hybrid_dataset.py
```

## Architecture (build time → question time)
Spreadsheets → clean and standardise → scorecard engine → SQLite · Charters → indexer → ChromaDB
Question → router → scorecard lookup and/or charter retriever → LLM answer (evidence only) → guardrail validator → answer with sources, or "I do not have that in the data provided."
