"""Download the public source data used to build the hybrid seed dataset.

Run once:  python scripts/download_sources.py
Everything lands in data/raw/ and data/external/ (both are untracked; re-download any time).
"""
import io
import os
import urllib.request
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SOURCES = {
    # US Federal IT Dashboard mirror (public domain) - costs, projects, CIO reviews, KPIs, narratives
    "data/raw/itspending/itspending-all.zip": "https://itspending.us/downloads/itspending-all.zip",
    # OMB 2024 Federal AI Use Case Inventory - real AI use-case narratives and go-live dates
    "data/raw/federal_ai_inventory/2024_consolidated_ai_inventory_raw_v2.csv":
        "https://raw.githubusercontent.com/ombegov/2024-Federal-AI-Use-Case-Inventory/main/data/2024_consolidated_ai_inventory_raw_v2.csv",
    # TAT-QA dev split (CC BY 4.0) - labelled table / text / table-text questions for router evaluation
    "data/external/tatqa_dataset_dev.json":
        "https://huggingface.co/datasets/next-tat/TAT-QA/resolve/main/tatqa_dataset_dev.json",
    # deepset/prompt-injections (Apache-2.0 per card) - labelled injection strings for guardrail evaluation
    "data/external/deepset_prompt_injections_train.parquet":
        "https://huggingface.co/datasets/deepset/prompt-injections/resolve/main/data/train-00000-of-00001-9564e8b05b4757ab.parquet",
    "data/external/deepset_prompt_injections_test.parquet":
        "https://huggingface.co/datasets/deepset/prompt-injections/resolve/main/data/test-00000-of-00001-701d16158af87368.parquet",
}


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (hackathon-data-fetch)"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return r.read()


def main() -> None:
    for rel, url in SOURCES.items():
        dest = os.path.join(ROOT, rel)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        print(f"GET {url}")
        data = fetch(url)
        if rel.endswith(".zip"):
            # extract only flat CSV / txt members, never paths
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                for name in z.namelist():
                    base = os.path.basename(name)
                    if base and base.lower().endswith((".csv", ".txt")):
                        with open(os.path.join(os.path.dirname(dest), base), "wb") as f:
                            f.write(z.read(name))
        else:
            with open(dest, "wb") as f:
                f.write(data)
    print("done")


if __name__ == "__main__":
    main()
