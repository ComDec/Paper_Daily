# Daily Preprint Digest

Automated daily pipeline that fetches new preprints (arXiv, bioRxiv, ChemRxiv), filters and scores them with an LLM (OpenRouter), renders a daily HTML report, and publishes it via GitHub Pages.

## What it does

- Fetches papers from multiple sources for a target date
- Applies a cheap keyword prefilter and an LLM relevance filter
- Rates papers (TLDR + 1-10 scores) and sorts by overall priority
- Writes `daily_json/YYYY-MM-DD.json` and `daily_html/YYYY_MM_DD.html`
- Generates `reports.json`, `index.html`, and `list.html`

All behavior is driven by `config.yaml`.

## Local usage

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

export OPENROUTER_API_KEY='...'

python -m paper_digest --config config.yaml
# Optional:
# python -m paper_digest --config config.yaml --date YYYY-MM-DD --days-back 0 --force
```

## GitHub Actions

Workflow: `.github/workflows/daily_arxiv.yml`

- Runs on a daily schedule and on manual dispatch
- Uses `OPENROUTER_API_KEY` from repository secrets
- Commits updated outputs and deploys to GitHub Pages

## Layout

```
.
├── paper_digest/                  # Pipeline package
├── config.yaml                    # Single-run configuration
├── templates/                     # Jinja templates
├── daily_json/                    # Daily JSON outputs
├── daily_html/                    # Daily HTML outputs
├── reports.json                   # Report index (metadata)
├── index.html                     # Latest report
├── list.html                      # Report archive
└── .github/workflows/daily_arxiv.yml
```
