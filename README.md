# City IT Contact + Staff Directory Finder

This repo:
1) Attempts to discover a city's staff directory page from its website
2) Scrapes the directory page(s) to find IT-related contacts (IT Manager, Information Technology, CIO, etc.)
3) Outputs CSVs + an optional ClickUp-friendly CSV.

## Setup

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt
python city_it_contact_finder.py --input data/cities.csv
