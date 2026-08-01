# Localization guidelines

## Architecture

- Use stable semantic message keys and UTF-8 catalogs.
- Keep English as a safe fallback and report missing development keys visibly without crashing frozen startup.
- Build dynamic messages from one key and named parameters; never translate concatenated fragments.
- Keep internal enums, JSON keys, profile/syringe IDs, plan/run IDs, commands, filenames, hashes, COM names, and paths canonical.
- Define reversible internal-value ↔ localized-label mappings for editable enum controls.
- Persist language in local application settings, never scientific Active Config.

## Japanese laboratory language

- Prefer short, operational wording over literal translation.
- Retain IN and OUT; clarify as 送液側 and 回収側 when useful.
- Retain DRY-RUN and LIVE with an explanatory phrase.
- Show localized state plus canonical code when troubleshooting benefits.
- Do not translate UART bytes or alter unit calculations.
- Avoid ambiguous labels such as 実行 for actions that must distinguish validation, DRY-RUN, LIVE, or movement.

## Runtime switching

- Update titles, navigation, buttons, fields, statuses, dialogs, empty states, tooltips, and dynamic messages.
- Preserve canonical selected values and runtime/coordinator state.
- Trigger layout/scrollregion recalculation after text changes.
- Confirm language changes do not write UART, change config fingerprints, invalidate ARMED, or stale commissioning evidence.

## Audit categories

- A: canonical technical identifier that remains unchanged.
- B: operator-facing content that must be localized.
- C: localized label plus canonical code.
- D: historical raw message available only in technical details.
