# PTA Telecom Market & QoS Dashboard

Pakistan cellular market share and quarterly network QoS dashboard, built from official [PTA](https://www.pta.gov.pk) data.

**Live page:** published via GitHub Pages from `index.html`.

## What's in here

- `index.html` — the dashboard itself (subscriber/market-share trends + Q1 2026 QoS survey results), single self-contained file (Chart.js inlined, no external dependencies).
- `scripts/update_pta_dashboard.py` — fetches PTA's monthly subscriber/market-share data, validates it against PTA's own reported totals, and updates `index.html`. Also checks PTA's QoS survey page for new quarterly reports (flagged in `scripts/qos_update_needed.txt` if found — those need a human/AI to read the PDF and update the QoS section, since that data is chart images, not parseable text).
- `.github/workflows/update.yml` — runs the script automatically on the 1st of every month and commits the result.

## Data sources

- PTA Telecom Indicators (subscribers / market share): https://www.pta.gov.pk/category/telecom-indicators/164 and /166
- PTA Independent QoS Survey of Cities (quarterly PDF reports): https://www.pta.gov.pk/category/qos-survey-959959384-2023-05-30

## Manual run

```
python3 scripts/update_pta_dashboard.py
```
