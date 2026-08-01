# Accessibility and keyboard checklist

- Preserve a logical Tab order from navigation to primary action, inputs, secondary action, and details.
- Leave ordinary buttons focusable; use `takefocus=False` only with a documented reason.
- Configure a visible focus state with adequate contrast.
- Confirm Space and Enter activate focused buttons appropriately.
- Confirm Treeview arrow keys change selection and selected rows remain visible.
- Add documented shortcuts only when they do not conflict with text editing.
- Keep Esc bound to the authoritative global STOP in syringe_perfusion.
- Provide confirmation before destructive deletion or discarding unsaved work.
- Do not steal initial focus into selectable diagnostic text.
- Keep essential warnings visible without hover; tooltips may add detail only.
- Pair color with text/icons and distinguish enabled from disabled without color alone.
- Give Japanese labels adequate vertical padding and installed-font fallbacks.
- Check screen-reader-friendly labels and unambiguous action names where practical.
- Verify language switching does not move focus unpredictably or change model values.
