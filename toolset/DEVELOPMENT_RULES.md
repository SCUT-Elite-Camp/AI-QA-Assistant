# Toolset Development Rules

## Scope

These rules apply to the Toolset team's work on the `toolset-dev` branch.

They are intended for code, tests, documentation, and commit messages related to the tool layer / toolset module.

## English Comments and Commit Messages

All code comments, docstrings, inline explanations, commit messages, and PR titles should be written in English.

This rule applies to:

- Python comments
- Python docstrings
- TODO notes
- Inline implementation explanations
- Commit messages
- Pull request titles
- Pull request summaries

User-facing text may still use Chinese when the product requirement requires Chinese output or Chinese UI copy.

## Commit Message Format

Use short English commit messages with a conventional prefix:

```text
feat: add unified search tool
fix: handle empty retrieval results
docs: update tool layer interface spec
test: add hybrid retrieval tests
chore: update local settings
```

Recommended prefixes:

| Prefix | Usage |
| --- | --- |
| `feat:` | New feature |
| `fix:` | Bug fix |
| `docs:` | Documentation update |
| `test:` | Test changes |
| `refactor:` | Code restructuring without behavior change |
| `chore:` | Configuration or maintenance changes |

## Examples

Good:

```text
feat: implement RRF hybrid retrieval
fix: normalize BM25 scores before filtering
docs: add CP2 interface notes
```

Avoid:

```text
feat: 添加混合检索
fix: 修复分数过滤
docs: 更新接口说明
```

## Local Git Template

Developers can optionally configure the provided commit template:

```powershell
git config commit.template .gitmessage.txt
```

This only affects the local repository and helps keep commit messages consistent.
