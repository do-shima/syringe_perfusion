---
name: tkinter-laboratory-ui-ux
description: Design, implement, localize, and review safe responsive Tkinter/ttk laboratory interfaces. Use for GUI redesign, Recipe Builder work, layout, scrolling, visual hierarchy, accessibility, keyboard operation, Japanese/English localization, screenshot review, and operator-workflow defects in syringe_perfusion or similar scientific desktop apps. Do not use for headless-only or hardware-control-only changes.
---

# Tkinter Laboratory UI/UX

Optimize for reliable operation during experiments, not only configuration. Read [references/syringe-perfusion-ui-contract.md](references/syringe-perfusion-ui-contract.md) for project work; omit it when applying this skill to another scientific Tkinter application.

## Required inputs

- Target screen/workflow, supported window sizes and scaling, languages, safety actions, and canonical model values.
- Current screenshots when available, relevant GUI construction/update code, shared theme/scroll components, and deterministic GUI tests.

## Workflow

1. Inspect screenshot and code together.
2. Map primary action, current state, warnings, editable data, secondary detail, and technical detail.
3. Identify clipping, reachability, ambiguous labels, mixed-language strings, invisible controls, focus gaps, and resize behavior.
4. Implement responsive wide/narrow modes rather than relying on one fixed pixel layout.
5. Put overflowing content in tested scrollable workspaces. Never use competing `bind_all`/`unbind_all` handlers; route wheel input to the region under the pointer.
6. Keep inner width synchronized to its viewport, refresh scroll regions after dynamic content/language changes, and preserve Text/Combobox behavior.
7. Keep canonical internal values stable. Localize through explicit display mappings and named message parameters.
8. Keep serial operations off the Tk thread; workers receive immutable snapshots and return UI work through the safe dispatcher.
9. Preserve state during language changes. Never invalidate scientific configuration, ARMED state, or commissioning evidence because display language changed.
10. Add deterministic geometry, mapping, focus, and behavior tests. Build and visually inspect the packaged GUI when required.

## Non-negotiable visual and accessibility guardrails

- Keep safety-critical controls visible and convey state with text, not color alone.
- Use blue for principal non-destructive actions, green for Save/Apply/PROGRAM, amber for LIVE/operator attention, red for STOP/destructive actions, filled gray for secondary actions, and white chiefly for cards/inputs.
- Give enabled, disabled, hover, pressed, selected, warning, danger, and keyboard-focus states distinct appearances.
- Preserve logical Tab order, Enter/Space activation, Treeview navigation, and global Esc STOP.
- Do not make tooltips the sole carrier of essential safety information.
- Use Japanese appropriate for concise laboratory operation; retain canonical identifiers when troubleshooting benefits.
- Package no external fonts; select installed Japanese-capable fonts with fallbacks.

## Required references

- Read [references/visual-hierarchy.md](references/visual-hierarchy.md) for style or hierarchy work.
- Read [references/tkinter-responsive-layout.md](references/tkinter-responsive-layout.md) for layout, scrolling, DPI, or resize work.
- Read [references/accessibility-checklist.md](references/accessibility-checklist.md) for interaction or keyboard work.
- Read [references/localization-guidelines.md](references/localization-guidelines.md) for localization work.
- Use [templates/ui-audit-report.md](templates/ui-audit-report.md) for a read-only visual audit.

## Verification

- Exercise 900×600, normal approximately 1170×790, and 100/125/150% scaling through deterministic geometry tests.
- Check both Japanese and English and state precisely which OS-level visual checks were actually performed.
- Confirm global STOP visibility and operation-state preservation.
- Confirm no test or visual smoke opens a real serial port.

## Output contract

Report hierarchy/layout decisions, responsive breakpoints, scrolling/focus/localization behavior, deterministic tests, packaged smoke results, manual viewports and OS scaling actually inspected, and any remaining workstation checks.
