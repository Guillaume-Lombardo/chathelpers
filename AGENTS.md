# AGENTS

## Skills

This repository uses local skills stored under `skills/*/SKILL.md`.

### Available skills by usage

#### Package architecture
- `flatten-repo-architecture`
  - File: `skills/flatten-repo-architecture/SKILL.md`
  - Use for: `src/` layout, module boundaries, CLI wiring, settings/logging design.

#### Testing strategy
- `flatten-repo-testing`
  - File: `skills/flatten-repo-testing/SKILL.md`
  - Use for: pytest markers, test placement (`unit/integration/end2end`), fixtures, defaults.

#### Quality and tooling
- `flatten-repo-quality`
  - File: `skills/flatten-repo-quality/SKILL.md`
  - Use for: pre-commit, Ruff, detect-secrets, `ty`, coverage gates.

#### Legacy umbrella skill
- `flatten-repo`
  - File: `skills/flatten-repo/SKILL.md`
  - Use for: broad tasks touching several usage areas at once.

## Skill selection rules

- If the request clearly targets one usage area, use the dedicated skill above.
- If the request spans multiple areas, combine the minimum required dedicated skills.
- Use the umbrella `flatten-repo` skill only for cross-cutting tasks or repository onboarding.
