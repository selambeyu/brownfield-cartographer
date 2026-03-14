## Cartographer Web Console

This app provides a browser-first UI for the Cartographer system so users can run analysis and queries without using CLI commands directly.

## Features

- Run analysis (`analyze run`) with repo, output, incremental, and LLM flags
- Run structured queries (`trace-lineage`, `blast-radius`, `explain-module`)
- Run natural-language query mode (`ask`)
- Visualize Surveyor and Hydrologist graphs

## Run Locally

From the project root:

```bash
uv sync
cd web
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000).

## Notes

- API routes invoke `uv run python -m src.cli ...` from the project root.
- The output directory should remain inside this repository (default `.cartography`).
- This UI is intended for local/dev usage where Python and `uv` are installed.
