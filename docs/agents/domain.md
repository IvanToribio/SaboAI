# Domain Docs

## Before exploring

Read `GLOSSARY.md` at the repo root and ADRs in `docs/adr/` relevant to the area being explored.

If these files do not exist, proceed silently. Create them lazily through domain modeling when terms or decisions are resolved.

## Layout

This project uses a single-context layout:

- `GLOSSARY.md`: domain vocabulary.
- `docs/adr/`: architecture decision records.

## Vocabulary and decisions

Use domain terms as defined in `GLOSSARY.md`, including in tickets, proposals and tests. When a concept is missing, reconsider the term or record the gap for domain modeling.

Explicitly flag any proposal that contradicts an existing ADR, identifying the ADR and explaining why the decision should be revisited.
