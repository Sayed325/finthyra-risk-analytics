# ADR-003: ML Model Choice for Anomaly Detection — XGBoost with Pseudo-Labelling
Date: 2026-04-15

## Decision
Use **XGBoost** (gradient-boosted decision trees) as the anomaly detection model, trained on **pseudo-labelled** historical data with a **walk-forward train/validation/test split** (70/15/15 by time). The model scores per-asset anomaly probability daily; results are aggregated to portfolio level.

## Context
Finthyra detects unusual behaviour in its 17-asset portfolio — volatility spikes, extreme return z-scores, accelerating drawdowns, and volume surges — without any labelled ground truth. There are no human-annotated "anomaly" events in the historical data. The model must run inside the daily GitHub Actions pipeline (< 60s total budget for the ML step), produce interpretable per-asset scores, and write results to the existing `risk_metrics` row. Class imbalance is severe: genuine anomalies are rare relative to normal trading days.

## Reasons

**XGBoost over alternative classifiers**
- **Tabular data dominance:** The feature set — rolling volatility, return z-scores, drawdown magnitude, drawdown acceleration, volume z-scores, and macro context (VIX, Fed Funds, Treasury Yield) — is entirely tabular. XGBoost consistently outperforms deep learning on tabular financial features at this data scale.
- **Handles class imbalance natively:** `scale_pos_weight` adjusts the loss function to weight anomaly-class samples proportionally. No oversampling (SMOTE) or threshold tuning required at training time.
- **Walk-forward compatibility:** XGBoost trains and scores in seconds on the dataset sizes involved (≤17 assets × 252 days = ~4,000 rows). The walk-forward loop (train on 70%, validate on 15%, test on 15% by chronological order) completes within the pipeline time budget.
- **Deterministic scoring:** Given the same feature matrix, XGBoost produces the same probability scores. This is important for reproducibility in a daily automated pipeline — the same market conditions on a re-run produce the same anomaly flag.
- **scikit-learn compatibility:** `XGBClassifier` implements the scikit-learn estimator interface, making `classification_report` and `predict_proba` drop-in available without custom wrappers.

**Pseudo-labelling rationale**
Ground-truth anomaly labels do not exist for this portfolio's historical data. Pseudo-labels are generated from statistical thresholds applied to the same features the model trains on:
- `volatility_anomaly`: rolling 20-day volatility > 95th percentile across the asset's history
- `return_anomaly`: |return z-score| > 2.5 standard deviations
- `drawdown_anomaly`: drawdown < -10% AND drawdown acceleration > -2% (worsening)
- `volume_anomaly`: volume z-score > 3.0

The composite label is the OR of all four conditions. This approach encodes domain knowledge (these thresholds map to well-established financial risk rules) without requiring manual annotation. The model then learns non-linear combinations of these features that generalise beyond the threshold rules.

**Walk-forward split rationale**
Random train/test splits on time-series data produce optimistic evaluation: the model sees future information during training. The 70/15/15 chronological split ensures validation and test sets are always temporally after the training set — a necessary condition for honest backtesting in financial ML.

**Alternatives considered:**
- **Isolation Forest:** Unsupervised, no labels needed. However, it produces anomaly scores without any domain-knowledge anchoring, and its decision boundary is opaque compared to XGBoost's feature importances. Pseudo-labelling with XGBoost gives us the interpretability of rule-based thresholds combined with the generalisation of a learned classifier.
- **LSTM / Temporal CNN:** Architecturally suited to sequential data, but requires significantly more data than 17 assets × 252 days to avoid overfitting, demands GPU or long CPU training time, and offers no feature importance output for debugging. Overkill for the scale of this problem.
- **One-Class SVM:** Trains only on normal data; sensitive to kernel and `nu` hyperparameter choice. Performance degrades on high-dimensional feature spaces. XGBoost is more robust without hyperparameter search.
- **Prophet (Facebook):** Designed for trend/seasonality forecasting, not anomaly classification. The existing `prophet_model.py` stub was left in scope for potential future price trend forecasting, not for anomaly detection.
- **Statistical threshold-only approach (no ML):** The pseudo-label thresholds alone could serve as the anomaly detector. XGBoost is added because it learns non-linear feature interactions (e.g., high volatility during a VIX spike is less anomalous than high volatility during calm macro conditions) that simple thresholds cannot capture.

## Tradeoffs
- **Pseudo-labels introduce circular dependency:** The model trains on labels derived from the same features it uses for inference. This means it cannot discover anomaly patterns that violate the labelling heuristics. Acceptable at this stage; ground-truth labels (e.g., from backtested drawdown events) would remove the circularity in a future iteration.
- **No persistence of trained model:** The model is retrained from scratch on each pipeline run. This ensures the model always reflects the most recent 252-day window and avoids model staleness. The cost is 2–5 seconds of training time per run — within budget.
- **Portfolio-level aggregation is simplistic:** Per-asset anomaly flags are aggregated as `any_flag = any([flags])`, `max_score = max([scores])`, and `anomaly_types = unique([types])`. This does not weight by portfolio allocation. A NVDA anomaly with 6% portfolio weight is treated identically to a BAS.DE anomaly with 6% weight. A weighted aggregation would be more precise but adds complexity without changing the dashboard display.
- **Class imbalance risk:** Even with `scale_pos_weight`, if fewer than ~5% of days are pseudo-labelled anomalies, the model may under-predict. This is monitored via `classification_report` logged to stdout on each run.

## Status
Accepted
