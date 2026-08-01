# Physical Syringe Calibration Library

The syringe library is stored in the shared Active Config as `syringes.json`. GUI, CLI, profiles, commissioning, and armed perfusion therefore read the same records. Existing schema-v1 records remain readable; schema-v2 adds physical identity, provenance, capacity, and optional stroke metadata without discarding unknown keys.

## Evidence and calculation

- `calibrated_ul_per_mm` is the authoritative conversion when present.
- `nominal_ul_per_mm`, or a value derived from `nominal_inner_diameter_mm`, is a clearly labeled nominal estimate only.
- `nominal_volume_ml` is physical metadata. It must be greater than zero and no greater than 150 mL, and is never substituted for a calibration.
- A measured calibration is never silently replaced by a nominal estimate.
- `maximum_usable_stroke_mm`, when known, limits requested travel. Large-syringe capacity alone does not establish mechanical fit, clamp compatibility, force, or usable stroke.

The normal Experiment form shows a concise physical name/label and a Calibrated, Nominal only, Calibration stale, or Missing calibration badge. Full provenance remains in Management / Advanced → Syringe library.

## Preview-first import

JSON and CSV import follows: select file → parse and validate → review create/update/skip conflicts → explicit apply. File selection alone never writes Active Config. Apply creates a timestamped backup, writes UTF-8 JSON atomically, records import provenance, and preserves unknown keys. A selected armed syringe change invalidates the plan; an unrelated record does not.

Stable keys and physical labels are separate. Conflicts match by `key`, never display name alone. “Create as new” allocates a distinct key, “Update existing” merges the selected record, and “Skip” leaves it unchanged. JSON retains full nested provenance; CSV intentionally does not encode nested audit history.

## CSV format

CSV is UTF-8 with one header row. Supported columns are:

```text
key,display_name,manufacturer,model,physical_label,nominal_volume_ml,nominal_inner_diameter_mm,nominal_ul_per_mm,calibrated_ul_per_mm,calibration_date,calibration_method,calibration_validation_id,replicate_count,coefficient_of_variation_percent,mean_error_percent,maximum_usable_stroke_mm,notes,active
```

The minimum interoperable fields are `key`, `display_name`, `nominal_volume_ml`, and a nominal diameter/conversion. An empty `calibrated_ul_per_mm` means uncalibrated; it must not be interpreted as zero. Use JSON when full import provenance or future extension fields must round-trip.

Read-only inspection never opens a serial port:

```powershell
a4ctl.exe --config-dir "<CFG>" syringe-list --json
a4ctl.exe --config-dir "<CFG>" syringe-show <KEY> --json
a4ctl.exe --config-dir "<CFG>" syringe-library-status --json
```
