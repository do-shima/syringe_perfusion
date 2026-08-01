# Syringe perfusion UI contract

## Structure

- Preserve top-level areas: Experiment, Setup, Advanced.
- Keep commissioning within Setup and profile/calculator/recipe/history within established navigation.
- Do not create another hardware-control application or another START/STOP state machine.

## Experiment primary view

Keep visible at supported geometry:

- current state and DRY-RUN/LIVE mode;
- preflight BLOCK/WARN summary;
- commissioning current/stale/incomplete status;
- PROGRAM/ARM action appropriate to enabled pumps;
- START ARMED;
- STOP ALL;
- important scheduled/start/end timing.

Place the global footer STOP outside scrollable secondary content, keep it enabled through all operation states, and preserve Esc binding.

## Supported presentation

- 900×600 and approximately 1170×790.
- Windows 100%, 125%, and 150% scaling.
- Japanese, English, and Auto locale detection with an explicit persisted preference.
- Japanese-capable installed font fallback: Yu Gothic UI, Meiryo UI, Meiryo, Segoe UI, then Tk default.

## Safety presentation

- Show `PROGRAMMED — NOT READ BACK` where applicable.
- Show `COMPLETED_ESTIMATED` as a time estimate only.
- Mark OUT disabled and avoid presenting OUT values as executable.
- Distinguish port-open testing, bounded movement, manual motion, jog, DRY-RUN, and LIVE.
- Keep raw UART commands in technical details and never translate their bytes.
