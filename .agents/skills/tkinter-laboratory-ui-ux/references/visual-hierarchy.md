# Visual hierarchy

## Order information by operational importance

1. Safety action and mode: STOP, LIVE/DRY-RUN.
2. Current state and blocking findings.
3. Principal operation: PROGRAM/ARM, START, Validate, Apply.
4. Editable scientific inputs and calculated preview.
5. Secondary navigation and file actions.
6. Technical identifiers, raw commands, and logs.

Keep levels 1–3 visible without scrolling in the primary experiment view. Move long explanations and raw UART data into expandable details.

## Color roles

| Role | Use | Avoid |
| --- | --- | --- |
| Primary blue | validation, DRY-RUN, main non-destructive action | STOP or LIVE |
| Success green | Save, Apply, PROGRAM/ARM | passive status-only decoration |
| Warning amber | LIVE, commissioning incomplete, operator attention | routine secondary actions |
| Danger red | STOP, destructive delete/cancel | ordinary validation |
| Neutral filled gray | New, Open, Refresh, Copy, move/navigation | white-on-white buttons |
| White | cards, entries, document surfaces | ordinary enabled buttons |

Show text labels for every safety state; color is supplemental. Give disabled controls a visible boundary and muted text. Configure hover, pressed, selected, and keyboard focus explicitly.

## Content rules

- Use concise summaries first and wrapped detail second.
- Shorten path display only when the full value remains copyable and available in details or a tooltip.
- Keep exact identifiers, commands, hashes, and paths unmodified.
- Distinguish connection/open tests from bounded physical movement.
- Distinguish DRY-RUN from LIVE in action labels, confirmations, and status.
