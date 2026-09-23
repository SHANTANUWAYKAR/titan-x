# Maintaining this project

For the maintainer. How a contributor's work reaches `main`, and how it reaches
your private working copy.

---

## The two repositories

```
TIS/
├── project_titan_x/      PRIVATE  — your working copy
│                         1.8 GB data · full history · .env · never published
│
└── titan-x-public/       PUBLIC   — the mirror people contribute to
                          938 files · 12 MB · clean history
                          → github.com/<you>/titan-x
```

They are deliberately separate. The private copy carries data that is
regenerable, not yours to redistribute, and in four cases larger than GitHub's
100 MB hard limit. A branch inside the private repo would keep all of it one
mistyped `git push --all` away from being public. A separate directory with its
own fresh history **cannot leak what it has never contained.**

---

## Publishing your own work

```bash
cd TIS/project_titan_x
python scripts/sync_public.py --dry-run     # always look first
python scripts/sync_public.py

cd ../titan-x-public
git status                                  # review what moved
git add -A && git commit -m "..."
git push
```

`sync_public.py` is **deny-by-default**: nothing is copied unless it matches an
allow rule, and an allowed path is still dropped if it matches a deny rule.
Adding a new engine publishes automatically. Adding a new data directory does
not.

---

## Receiving a contribution

This is the flow you asked for — someone improves the project, and it becomes
part of your main.

```
 1. contributor forks github.com/<you>/titan-x
 2. they branch, change, and open a pull request against main
 3. CI runs: tests · secret scan · file-size guard
 4. you review (see the bar below)
 5. you merge  →  it is now in main
 6. you pull it into your working copy
```

**Step 6, the part that closes the loop:**

```bash
cd TIS/titan-x-public
git pull                                    # their work is now local

# copy the changed files back into your private working copy
cp -r engines/ setups/ scripts/ ../project_titan_x/
cd ../project_titan_x
pytest tests/ -q                            # verify against YOUR data
git add -A && git commit -m "merge: <what they contributed>"
```

Your data, models and `.env` are untouched by this — the public repo has none
of them, so nothing can overwrite them.

### Reviewing: the bar

A pull request that touches a strategy, signal or statistic must state:

| Required | Why |
|---|---|
| Trade count | Below ~100 trades a result is arithmetic |
| Net expectancy **after costs** | `cost_R = cost / stop_frac` decides outcomes |
| A null comparison | 150 of 150 noise paths once "passed" here |
| Year-by-year results | The cut that killed five leads |
| Unresolved-trade fraction | One lead looked profitable until 65% of its trades turned out to have vanished |

`setups/concept_lab.py` and `setups/trade_journal.py` compute all of these. Ask
for those, not for a different evaluator — comparability is the whole point.

**The most valuable PR is one that kills something.** If someone shows a
strategy here does not work, that is a contribution. This project has already
retracted several of its own findings and keeps them in the reports.

---

## Versioning

Every merged PR adds a line to `CHANGELOG.md` under `[Unreleased]`. When you cut
a release:

```bash
echo "1.1.0" > VERSION
# move [Unreleased] entries under a new [1.1.0] - YYYY-MM-DD heading
git commit -am "release: 1.1.0"
git tag -a v1.1.0 -m "..." && git push && git push --tags
```

| Bump | When |
|---|---|
| MAJOR | a public API changes, **or a measurement's meaning changes** |
| MINOR | new engine, setup, script, report |
| PATCH | bug fix, docs, test |

A bug fix that **changes previously published numbers is MAJOR**, not PATCH.
Anyone who acted on the old figure needs to notice. This project has already
shipped three such fixes; each one moved numbers that had been reported.

---

## Identity

The public repo has a **repo-local** git identity so a stray global edit cannot
change it:

```bash
git config --local user.name  "Shantanu Waykar"
git config --local user.email "waykarshantanu2007@gmail.com"
```

A repo-local identity matters here: a mistyped global `user.email` silently
attributes commits to an address you do not control, and GitHub cannot link
them to your profile. Setting it locally means the public repo is unaffected
by whatever the global config happens to be.

**To hide your email from public history** (GitHub still links commits to your
profile, and they still count toward your contribution graph):

```bash
# Settings → Emails → "Keep my email address private", then:
git config --local user.email "<ID>+<username>@users.noreply.github.com"
```

---

## Never publish

Withheld by `sync_public.py` and by `.gitignore`. If you add something in one of
these categories, check it is covered:

| Path | Reason |
|---|---|
| `data/**` | 1.8 GB, regenerable, four files over GitHub's limit |
| `reports/TITAN_X_DELIVERABLES/**` | 419 files extracted from copyrighted books/video |
| `reports/knowledge_base_notes/**` | 116 files, same |
| `.env`, `*.key`, `*.pem` | credentials |
| `CLAUDE.md`, `MASTER_PROMPT.md`, `.claude/` | local agent config |

Your **measurements** of copyrighted material are yours to publish. The
extracted source text is not.

CI enforces the last line of defence: a secret scan and a 50 MB file-size guard
run on every push and pull request.
