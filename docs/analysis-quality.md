# Evidence-bound analyst instructions

Prompt contract version `1.0` is recorded in synthesis trace metadata. Shared rules,
sport/domain guidance and reviewer requirements live in `analysis_instructions.py`;
presentation guidance and agent construction remain in `agents.py`.

Every coordinator/specialist receives the same analytical contract. The coordinator
also receives reviewer checks, including direct follow-ups without specialists.
`inspect_analysis_context` supplies selected subject/windows, current timestamp,
registered metric definitions and the acquisition dates/coverage of evidence sources.
Unknown definitions or completeness remain unknown. Context is not itself a citation.
Comparison evidence includes both sample counts where the analytics provide them;
play-row counts must not be mistaken for a metric's non-null denominator.

`MODEL` performs evidence synthesis. `CHAT_MODEL`, when configured, edits only the
validated draft's wording and must preserve numbers, denominators, qualifications,
sport terminology and measured-versus-interpretive status.

## Verification and model evaluation

The retained high-level tests exercise actual tool and prompt construction for NFL
receiving, NBA defense and soccer scoring, with unequal samples, incomplete coverage,
missing values, counter-signals and unsupported tactical questions. Calls are mocked:
these are wiring/contract regressions, not proof of model factual accuracy.

For live model evaluation, replay these cases with captured evidence and the configured
analysis model, reviewing initial and follow-up outputs separately. Model calls incur
provider usage and are not part of the default test suite. Use these acceptance criteria:

| Scenario                                     | Required behavior                                                                               |
|----------------------------------------------|-------------------------------------------------------------------------------------------------|
| NFL receiving improvement with fewer targets | Separate workload and efficiency; do not infer separation from yards/target.                    |
| NBA lineup improvement                       | State unit/sample context; do not credit an individual or infer assignments from lineup rating. |
| Soccer goals rise while xG falls             | Preserve contradictory signals; compare covered matches and avoid finishing-skill forecasts.    |
| Missing metric                               | Explicitly unavailable, never zero or estimated.                                                |
| Unequal samples or partial coverage          | Identify the relevant restriction without declaring causal/statistical certainty.               |
| Endpoint-only range                          | Do not invent intermediate-season results or a continuous trend.                                |
| Conversational rewrite                       | Preserve conclusions and material restrictions; add no new facts or mechanisms.                 |

Score each response for numerical fidelity, citation entailment, scope/coverage fidelity,
sport terminology, causal restraint and directness. Any invented number, unsupported
tactical assertion, or source/window mismatch fails the case. Record prompt version,
model/version, source snapshot and reviewer rationale when comparing runs in LangSmith.

Citation schema validation checks that references exist; it does not establish semantic
entailment. Reviewer prompts and structured output do not replace independent evaluation.
