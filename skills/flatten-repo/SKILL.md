---
name: flatten-repo
description: Umbrella skill for flatten-repo when tasks span architecture, tests, and quality gates together.
---

# Flatten Repo

## Overview

Use this skill for cross-cutting requests. For focused tasks, prefer dedicated skills:

- `flatten-repo-architecture` for module/package design.
- `flatten-repo-testing` for pytest layout and marker behavior.
- `flatten-repo-quality` for pre-commit, Ruff, ty, and secret scanning.

## Workflow

1. Split the request by concern (architecture, tests, quality).
2. Apply only the minimal needed dedicated skills.
3. Verify each concern independently, then run a final end-to-end check.
