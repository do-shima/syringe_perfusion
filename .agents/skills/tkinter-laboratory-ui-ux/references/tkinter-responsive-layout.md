# Tkinter responsive layout

## Layout strategy

- Let the primary content row/column carry nonzero weight.
- Define a deterministic breakpoint from the content viewport, not the monitor size.
- Use proportional grid weights or a resizable `ttk.PanedWindow` in wide mode.
- Stack or switch workspaces in narrow mode rather than preserving unusable columns.
- Treat minimum pane widths as logical constraints and test them under scaling.
- Debounce wraplength updates from `<Configure>` events; avoid resize busy loops.

## Scrollable regions

- Synchronize the canvas window width to the viewport.
- Update `scrollregion` whenever inner content changes size.
- Route mouse-wheel input to the registered scrollable area under the pointer.
- Do not call `bind_all`/`unbind_all` per scrollable frame.
- Preserve Combobox dropdown and editable Text scrolling.
- Support Windows `MouseWheel` deltas and Linux Button-4/Button-5.
- Support Page Up/Down and Home/End when focus is not editing text.
- Unregister handlers on destruction and test multiple independent regions.
- Show vertical/horizontal scrollbars whenever content is otherwise unreachable.

## Geometry verification

For each supported size/scaling, assert:

- the bottom-most required control is reachable;
- fixed actions and global STOP remain mapped and inside the viewport;
- scrollregion exceeds viewport only when expected;
- inner content follows viewport width;
- no unsupported horizontal overflow;
- wide and narrow modes select predictably;
- long Japanese strings remain reachable and wrap without overlap.

Prefer deterministic `update_idletasks()` geometry assertions over screenshot-only tests. Use screenshots as complementary visual evidence.
