---
name: git-workflow
description: >
  Guide best practices for Git workflows including branching, commits, rebasing,
  conflict resolution, and pull requests. Activate when the user mentions Git,
  branches, commits, merging, rebasing, or pull requests.
tools_required: [run_shell, read_file]
version: "1.0"
trigger_keywords: [git, branch, commit, merge, rebase, pull request, pr, cherry-pick, stash]
---

# Git Workflow Skill

## When to Activate
Activate when the user mentions: 'git', 'branch', 'commit', 'merge', 'rebase',
'pull request', 'PR', 'cherry-pick', 'stash', 'conflict', 'bisect'.

## Core Principles

1. **Check current state first**: Always run `git status` and `git log --oneline -10` before making changes.
2. **Small, atomic commits**: Each commit should do one logical thing.
3. **Descriptive commit messages**: Follow Conventional Commits format: `type(scope): description`.
4. **Never force-push to main/master** without explicit user confirmation.

## Common Procedures

### Starting a Feature Branch
```bash
git checkout main && git pull origin main
git checkout -b feat/your-feature-name
```

### Cleaning Up Before PR
```bash
git add -A
git commit -m "feat(scope): what this does"
git push origin feat/your-feature-name
```

### Resolving Merge Conflicts
1. Run `git status` to find conflicted files.
2. Open each file and resolve `<<<<<<<` / `=======` / `>>>>>>>` markers.
3. Run `git add <resolved-file>` for each.
4. Run `git commit` to complete the merge.

### Interactive Rebase (squash commits)
```bash
git rebase -i HEAD~N  # Replace N with number of commits to squash
```
In the editor, change `pick` to `squash` (or `s`) for commits to merge into the previous one.

## Safety Rules
- NEVER run `git reset --hard` without confirming with the user.
- NEVER run `git push --force` without user approval.
- Prefer `git restore` over `git checkout` for file restoration (modern Git).
