# CivicPlusPlus

Finds city websites using the Civic Plus management platform, identifies staff directories, then extracts IT manager info.

**Author:** [SkyzFallin](https://github.com/SkyzFallin)

## What It Does

1. Discovers a city's staff directory page by crawling its website
2. Scrapes the directory page(s) to find IT-related contacts (IT Manager, CIO, etc.)
3. Outputs CSVs + an optional ClickUp-friendly CSV

## Setup

```bash
git clone https://github.com/SkyzFallin/CivicPlusPlus.git
cd CivicPlusPlus

python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt
```

## Usage

```bash
python city_it_contact_finder.py --input data/cities.csv
```

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--input` | (required) | Input CSV path with city/state/site_url columns |
| `--outdir` | `output/` | Output directory for results |
| `--max_candidates` | `5` | Directory candidates to keep per city |
| `--max_pages` | `18` | Max pages to crawl per city |
| `--max_depth` | `2` | Crawl depth per city |

## Output Files

- `staff_directory_candidates.csv` — ranked directory page URLs per city
- `it_contacts.csv` — extracted IT contact info (emails, phones, context)
- `clickup_import.csv` — ClickUp-ready task import format

## Input CSV Format

Your `data/cities.csv` should have these columns:

| Column | Required | Description |
|--------|----------|-------------|
| `city` | Yes | City name |
| `state` | Yes | State abbreviation |
| `site_url` | Yes | City website URL |
| `county` | No | County name |
| `known_directory_url` | No | Skip discovery and use this URL directly |

## License

GPL-3.0
