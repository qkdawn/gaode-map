# 2026-05-14 Tourism Cross Analysis Validator

## Symptom

The commercial summary panel could generate the regular summary sections, but the tourism cross analysis card did not appear.

## Root Cause

`_validate_tourism_cross_analysis_payload()` required an exact fifth-section heading:

`五、人口×POI×夜光交叉诊断`

LLM outputs that were semantically valid but used natural variants like `五、人口、POI与夜光交叉诊断` were rejected. The rejected payload was not attached to `summary_pack.tourism_cross_analysis`, so the frontend had no content to display.

## Fix

Relaxed the validator while keeping the report structure guardrails:

- Still requires `一、综合判断`
- Still requires `九、策划结论`
- Requires the fifth section to include population, POI, nightlight/night lighting, cross-analysis wording, and diagnosis/analysis wording
- Allows separator variants such as `×`, `x`, `、`, and `与`

## Verification

- `.\.venv\Scripts\python.exe -m pytest tests/domain/test_agent_summary_service.py -k "tourism_cross_analysis"`
- `.\.venv\Scripts\python.exe -m pytest tests/domain/test_agent_summary_service.py`
- `npm.cmd test -- --test-name-pattern "tourism|summary stream completion fills tourism|summary session history persists tourism"`
