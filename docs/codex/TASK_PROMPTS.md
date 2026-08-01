# Short Codex task prompts

Use `Goal:` as plain prompt text. Add concrete scope and prohibitions; let the repository Skills provide the repeated workflow.

## Feature task

```text
Goal:

<one clear objective>

Use the relevant repository Skills.

Scope:
- <items>

Do not change:
- <items>

Verification:
- run relevant tests
- run full suite
- build when applicable

Commit the completed change.
Do not push.
```

## GUI task

```text
Goal:

Improve <screen or workflow>.

Use:
- syringe-perfusion-project-workflow
- tkinter-laboratory-ui-ux
- syringe-perfusion-verification-release
- syringe-perfusion-review-closeout

Preserve hardware-control semantics.

Commit when verified.
Do not push.
```

## Hardware-control task

```text
Goal:

<control objective>

Use:
- syringe-perfusion-project-workflow
- syringe-perfusion-hardware-safety
- syringe-perfusion-verification-release
- syringe-perfusion-review-closeout

Do not perform real serial communication in automated tests.
Commit when verified.
Do not push.
```

## Read-only audit

```text
Goal:

Audit <milestone>.

Use:
- syringe-perfusion-review-closeout
- syringe-perfusion-hardware-safety when relevant

Start read-only.
Repair only incomplete prior-scope defects.
Commit only if repairs are made.
Do not push.
```

## HIL session

```text
Goal:

Conduct controlled validation of <artifact>.

Use:
- syringe-perfusion-hil-commissioning
- syringe-perfusion-hardware-safety
- syringe-perfusion-review-closeout

Do not modify source during the fixed-build session.
```
