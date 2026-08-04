# Citation Check

## Purpose

`CitationChecker` validates structural consistency between the final answer,
public Citations, and accepted Evidence.

## Rules

- Answer markers use `[n]`.
- Citation IDs are unique and contiguous from 1.
- Every answer marker resolves to a Citation.
- Every Citation is referenced in the answer.
- Every Citation maps to accepted Evidence by `doc_id + chunk_id`.
- Reusing the same marker more than once is allowed.
- An answer without markers is valid only when no Citations are supplied.

This CP2 component performs deterministic structural validation. It does not
use an LLM to judge whether every sentence is semantically entailed by the
Evidence.
