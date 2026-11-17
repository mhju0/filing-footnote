# Neutrality Guards on Generated Text

Status: Accepted · 2026-11-17 (D63)

Generated summaries pass checks before they can ship: they contain no digits, because figures are rendered from structured data; they contain none of a banned list of evaluative words; they make no prediction and give no advice; and each statement is attributed to the company that made it. A summary that fails any check is withheld and the app shows the figures alone. An LLM reviewer may flag further problems, but it is advisory and never approves a summary. Only summaries the owner has approved ship in the bundled file. The guards do not prove that a sentence is supported by the filing, that a neutral-looking sentence is not misleading, or that the banned list is complete; owner review covers those. This was chosen over trusting the model's instructions because instructions alone cannot be tested, and over automatic approval because a reviewer model shares the failure modes of the writer.
