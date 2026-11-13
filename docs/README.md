---
title: VigilanSee documentation
status: current
last_reviewed: 2026-10-13
---

# VigilanSee documentation

Organised with the [Diátaxis](https://diataxis.fr) framework. Each page has one job; pick the section by what you need.

| I want to...                         | Go to                              |
|--------------------------------------|------------------------------------|
| look up a fact (rules, config, CI)   | [`reference/`](reference/)         |
| fix or do one specific thing         | [`how-to/`](how-to/)               |
| understand why things are the way they are | [`explanation/`](explanation/) |

Tutorials (guided first run of the stack) will be added once the application stabilises. Writing them now would mean rewriting them every week.

## Reference
- [CI workflows](reference/ci-workflows.md)
- [Repository rules](reference/repo-rules.md)
- [Workspace crates](reference/crates.md)
- [Environment variables](reference/environment-variables.md)
- [Devlog format](reference/devlog-format.md)

## How-to
- [Fix a failing CI check](how-to/fix-a-failing-ci-check.md)

## Explanation
- [Contributing workflow](explanation/contributing-workflow.md)
- [Architecture overview](explanation/architecture.md)
- [Architecture decision records](explanation/decisions/README.md)

## Keeping these docs honest
- Every page has `last_reviewed` in its front matter. If a page looks old, treat it with suspicion and fix it.
- Link to the source of truth (`.github/workflows/`, the ruleset) rather than copying it.
- If your change touches a workflow, a rule or a config value, update the matching page in the same PR.
