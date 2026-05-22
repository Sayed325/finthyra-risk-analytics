# ADR-004: AI Commentary Layer Design — Gemini with Round-Robin Key Rotation
Date: 2026-05-21

## Decision
Use **Google Gemini 2.5 Flash** (with **Gemini 2.5 Flash Lite** as fallback) for daily portfolio briefing generation, accessed via the `google-genai` SDK with **round-robin rotation across up to 5 API keys × 2 models** for resilience. The AI layer reads only computed metrics — never raw price data — and writes a single `ai_briefing` column in the `risk_metrics` table via `UPDATE` (never `INSERT`).

## Context
The pipeline already computes quantitative risk metrics (VaR, Sharpe, drawdown, beta) and anomaly flags daily. The final mile — translating numbers into plain-English portfolio commentary — requires a language model. The commentary must: (1) be generated free of charge at the scale of one call/day, (2) degrade gracefully if an API key is exhausted or the model is unavailable, (3) never expose credentials or raw data to the dashboard, and (4) run in < 30s as the last step in the daily pipeline.

## Reasons

**Gemini over other LLMs**
- **Free tier sufficient:** Gemini 2.5 Flash is available on Google AI Studio's free tier with a rate limit of 15 requests/minute. One call per day is several orders of magnitude below the limit. No payment method required for this use case.
- **Context window:** Gemini 2.5 Flash supports a 1M-token context window. The prompt (risk metrics + macro context + holdings) is < 500 tokens — well within limits regardless of portfolio size growth.
- **Output quality for structured financial text:** In internal testing during development, Gemini 2.5 Flash produced coherent 3-sentence summaries that correctly referenced numeric values from the prompt. Hallucination of numbers was not observed when values were explicitly included in the prompt.
- **`google-genai` SDK:** The current Google-recommended SDK (`google-genai>=1.0.0`), replacing the deprecated `google-generativeai`. Migration was completed in session 3 after FutureWarnings appeared in pipeline logs.

**Round-robin key × model rotation**
- **Why multiple keys:** A single free-tier key has a per-minute token quota. On retry after a rate-limit error, rotating to a different key immediately resumes the request without a sleep. Five keys provide a comfortable buffer.
- **Why two models:** Gemini 2.5 Flash Lite is a smaller, faster model used as secondary fallback if all Flash primary attempts are exhausted. Flash Lite produces slightly shorter output but remains adequate for a 3-sentence briefing.
- **Rotation order:** `itertools.cycle` over all (key, model) combinations — first all keys on Flash, then all keys on Flash Lite. This exhausts Flash capacity before downgrading, preserving output quality.
- **Failure semantics:** If all (key, model) combinations raise an API error, `generate_commentary()` returns `{"status": "failure"}` without raising. The pipeline logs the failure and continues. The `ai_briefing` column retains its previous day's value — a stale briefing is better than a pipeline abort.

**Prompt design**
The prompt includes: today's VaR 95/99, Sharpe ratio, max drawdown, beta, anomaly flag/type/score, all 5 macro indicator values, portfolio holdings with asset names, and the worst-performing asset's daily return. It instructs the model to output exactly 3 sentences with no preamble, headers, or markdown. This constraint makes the output suitable for direct display in `st.info()` without post-processing.

**`UPDATE`-only write pattern**
The `risk_metrics` row is written first by `compute_risk_metrics()`, then updated by `run_anomaly_detection()` (anomaly columns), then updated again by `generate_commentary()` (`ai_briefing` column). Commentary never inserts its own row — it uses a SELECT-then-UPDATE pattern to locate the day's existing row by `portfolio_id` and `date`. This prevents orphaned rows if the risk metrics step failed and maintains referential integrity with the pipeline's execution order.

**Alternatives considered:**
- **OpenAI GPT-4o / GPT-4o-mini:** Higher output quality than Gemini Flash for complex reasoning, but no permanently free tier for API access. GPT-4o costs ~$0.005/call — negligible individually, but introduces a payment dependency that violates the project's zero-cost constraint. GPT-4o-mini is cheaper but still not free.
- **Anthropic Claude API (claude-haiku-4-5):** Strong instruction-following, competitive with Gemini Flash on structured output tasks. Available on a free tier with limits, but lower request quota than Google's offering. A viable alternative if Gemini free tier policies change.
- **Locally hosted LLM (Ollama + Llama 3):** Zero API cost, no rate limits, full privacy. Incompatible with GitHub Actions runner (no GPU, insufficient RAM for 7B+ parameter models within the pipeline's runtime budget). Would require self-hosted infrastructure, violating the zero-ops constraint.
- **Rule-based template (no LLM):** A deterministic template filling `"VaR is {var_95:.1%}, Sharpe is {sharpe:.2f}..."` is reliable and free. Rejected because it produces identical sentence structure every day, reducing the utility of the briefing as a daily communication tool. The LLM provides variety and contextualisation (e.g., relating VIX level to the anomaly flag) that a template cannot.
- **Single API key with retry sleep:** Simpler than round-robin rotation, but introduces 60s+ sleep delays on rate-limit errors, violating the pipeline's time budget.

## Tradeoffs
- **LLM hallucination risk:** Even with explicit numeric values in the prompt, the model could misrepresent a relationship (e.g., calling a Sharpe of 0.3 "strong"). Mitigation: the prompt instructs the model to use the provided numbers directly and to avoid qualitative assessments not grounded in the data. The dashboard displays the briefing in an `st.info()` callout, not as a primary data panel — the metric cards are the authoritative source of truth.
- **Prompt sensitivity:** Small changes to the prompt phrasing can materially change output style. The prompt is not versioned separately from the code. If the output quality regresses after a Gemini model update, the prompt may need adjustment.
- **No briefing history:** Only the current day's `ai_briefing` is stored (one row per `portfolio_id, date` in `risk_metrics`). Past briefings are accessible by querying by date but are not surfaced in the dashboard. A future "Briefing Archive" panel would expose this history.
- **Key management overhead:** Five GEMINI_KEY_n environment variables must be kept valid. Expired keys silently reduce rotation pool size — the pipeline does not alert when the effective pool shrinks below a threshold.

## Status
Accepted
