# Repository-local Codex Skills

## Purpose

This repository stores repeatable project workflows as small Agent Skills so task prompts can state the objective and scope without copying the full safety, GUI, verification, HIL, and closeout contracts each time.

## Canonical location and format

Skills live only under:

```text
.agents/skills/<skill-name>/SKILL.md
```

Codex 0.146.0 and the current official Codex Skills guidance scan `.agents/skills` from the current working directory through the Git repository root. The root location therefore makes these Skills available throughout this repository. Do not duplicate them under `.codex/skills` or install them into a contributor's global home directory.

Each `SKILL.md` uses the current Agent Skills format: YAML frontmatter with a unique lowercase kebab-case `name` and trigger-oriented `description`, followed by imperative workflow instructions. Detailed checklists are under `references/`; reusable report forms are under `templates/`. Optional `agents/openai.yaml` supplies display metadata without changing the workflow.

## Discovery and invocation

Start a new Codex session from this repository after cloning or changing Skills. Codex detects Skill changes automatically in supported surfaces; restart if the list appears stale.

In Codex CLI or the IDE extension, inspect available Skills through the Skills interface (`/skills`) where supported, or ask Codex to list repository Skills and their paths. Invoke one explicitly by mentioning it with `$`, for example:

```text
Use $tkinter-laboratory-ui-ux to audit the Recipe workspace at 900×600.
```

Implicit selection uses the `description` in each Skill's frontmatter. Descriptions are intentionally distinct: repository workflow, hardware safety, Tkinter UX, release verification, physical HIL commissioning, and read-only closeout.

## Composition

Multiple Skills should be selected when a task crosses boundaries. `AGENTS.md` contains the concise index and global rules; the Skill files contain detailed procedures.

The suite contains:

- `syringe-perfusion-project-workflow` — scoped repository development and Git closeout.
- `syringe-perfusion-hardware-safety` — serial, pump, state, scheduler, Recipe, NIS, START, cancellation, and STOP safety.
- `tkinter-laboratory-ui-ux` — responsive Tkinter GUI, localization, accessibility, and visual review.
- `syringe-perfusion-verification-release` — tests, Windows builds, CI, versions, packaging, manifests, and checksums.
- `syringe-perfusion-hil-commissioning` — fixed-build physical direction, STOP, flow, balance, NIS, and workstation validation.
- `syringe-perfusion-review-closeout` — read-only audits, evidence grading, and milestone completion classification.

Examples:

- GUI presentation change: project-workflow + tkinter-laboratory-ui-ux + verification-release + review-closeout.
- START/STOP GUI change: add hardware-safety.
- Fixed-build pump validation: HIL-commissioning + hardware-safety + review-closeout; do not modify source during the session.

Use [codex/TASK_PROMPTS.md](codex/TASK_PROMPTS.md) for concise prompt templates.

## Adding or modifying a Skill

1. Choose one bounded responsibility and distinct trigger description.
2. Invoke the installed `$skill-creator` or run its `init_skill.py` into `.agents/skills`.
3. Keep `SKILL.md` concise; put detailed policies in directly linked references and report structures in templates.
4. Use only `name` and `description` in `SKILL.md` frontmatter.
5. If `agents/openai.yaml` is present, keep its display name, 25–64 character short description, and `$skill-name` default prompt aligned.
6. Add the Skill to root `AGENTS.md` and any relevant short prompt.
7. Validate and forward-test representative prompts.

## Validation

Run the installed creator validator for every directory:

```powershell
$validator = "$env:USERPROFILE\.codex\skills\.system\skill-creator\scripts\quick_validate.py"
Get-ChildItem .agents\skills -Directory | ForEach-Object {
    python $validator $_.FullName
}
```

Also verify unique names, matching frontmatter/folder names, valid relative links, UTF-8 Markdown, no personal paths or local numeric COM assignments, correct `AGENTS.md` paths, task-template names, and `git diff --check`. Run the full application pytest suite because Skills and project instructions must not affect runtime behavior.

For discoverability, start a fresh Codex session in the repository and inspect the Skills list. If a live fresh-session test is unavailable, report that limitation and distinguish structural validation from automatic discovery.

## Project-local versus user-global

Repository Skills are versioned with this project and apply only within its tree. User-global Skills live outside the repository and apply across projects; this suite intentionally writes nothing there.

## Troubleshooting

- Confirm the working directory is inside the intended Git repository.
- Confirm each directory contains `SKILL.md` and valid frontmatter.
- Confirm the directory is `.agents/skills`, not a similarly named duplicate tree.
- Restart Codex after changes if discovery appears stale.
- Check for duplicate Skill names in project, user, admin, or system scopes.
- Confirm root `AGENTS.md` paths and instructions are loaded from the expected repository root.
