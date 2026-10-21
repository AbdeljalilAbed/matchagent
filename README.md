# matchagent

LLM agent (PydanticAI) answering natural-language questions about football
matches, grounded in real event data, with sourced answers and a numeric evaluation.

## Setup

```bash
uv sync
uv run python scripts/phase0_explore.py coverage
uv run pytest
```

## Data and attribution

Data: [StatsBomb Open Data](https://github.com/statsbomb/open-data).
StatsBomb's user agreement asks to credit StatsBomb as the data source (and use
their logo) when publishing research, analysis or insights based on this data.
Read the LICENSE in their repository for the exact terms.
