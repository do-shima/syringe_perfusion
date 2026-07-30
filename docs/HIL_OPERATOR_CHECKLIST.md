# HIL Commissioning Operator Checklist

Use this short checklist beside the GUI. Record details in the commissioning record and `HIL_VALIDATION_SESSION.md`.

- [ ] Verify release version, commit, clean status, control compatibility, and ZIP SHA-256.
- [ ] Confirm the Active Config and preserve its runtime/validation folders.
- [ ] Scan ports without assuming roles from COM numbers.
- [ ] Physically confirm IN and OUT adapter identities.
- [ ] Confirm conservative bounded setpoints and global STOP availability.
- [ ] Observe IN forward direction.
- [ ] Observe OUT reverse direction.
- [ ] Validate STOP for IN, OUT, and both pumps.
- [ ] Rehearse delayed cancellation in DRY-RUN.
- [ ] Record at least the selected flow-calibration replicates.
- [ ] Review but do not automatically apply candidate syringe calibration.
- [ ] Record paired IN/OUT balance evidence.
- [ ] Validate immediate, delayed, cancel, and STOP NIS wrappers.
- [ ] Review 100%, 125%, 150%, and constrained display layouts.
- [ ] Export commissioning and sanitized diagnostic reports.
- [ ] Record deviations and final disposition.

UART completion alone is not physical PASS. **PROGRAMMED — NOT READ BACK** remains authoritative.
