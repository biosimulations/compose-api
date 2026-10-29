# Entry updates: a trusted repository's commit moves by API, not by pull request

**Status (2026-10-29): the active plan; step 1 in review.** Asked for by Jim on 2026-10-29 while updating viva-pde-particle (its #69). One PR
per step, each merged with a merge commit; deploying is a release, as usual.

| Step | What | State |
|---|---|---|
| 0 | This document | merged (#480) |
| 1 | The manifest flag, and a version made at a newer commit of a flagged entry (API, CLI) | in review |
| 2 | Compliance gates a moved commit: refused until its cases pass, and never the default before then | — |
| 3 | The web page: "new commits" on an environment's page, and making a version from one | — |
| 4 | (Later, if wanted) candidates made by the service when a flagged repository moves | — |

## Context

- **Moving a composed entry to new code takes a release today.**
  - A manifest entry (`compose_api/registry/manifest.yaml`, the registry of record) pins a git entry at a full
    commit, in `commit:` and `install.commit:`.
  - A composed version, and every later version of a mash-up (`lifecycle.mash_up_spec`), installs what the
    *deployed* manifest pins.
  - So a fix upstream reaches runs through a compose-api PR, a review of a 40-character hash, and a release, and only
    then a version.
  - viva-pde-particle#69 (2026-10-29) needs exactly that: merge, manifest PR, release 0.7.73, then the mash-up's @3.
- **A prebuilt environment already moves by API.** `compose-api environments create viva-pde-particle --image
  …@sha256:…` registers an image as a version, by an environment administrator, with no PR. Composed environments are
  the exception.
- **What a version records is enough to reproduce and roll back.**
  - Each version keeps its spec, with each entry's commit, its `pixi.lock`, and its read-back of packages and
    interfaces. Every run records its version.
  - The default changes only by `PUT …/default`, and only to a `ready` version.
- **Compliance already runs per version (composition step 5).**
  - Each version runs its entries' cases, and admission consults that version's standing (`environments/admission.py`).
  - But an entry with no cases yet, or whose cases are still running, **keeps the manifest's level**. A version made
    at an untested commit is admitted at `tested` until its cases finish.
  - `PUT …/default` checks only that the version is `ready`, not its compliance.

## Decisions (proposed)

- **E1. The PR stays for trust; the commit moves without one.**
  - A PR still adds an entry, and still changes how it installs: source, conda requirements, extras, module roots,
    level, compliance cases.
  - What may move without one is the commit of a flagged git entry.
- **E2. The flag is on the entry.**
  - `updates: main` allows any commit on the repository's default branch. `updates: tags` allows only commits a
    release tag points at.
  - No separate list: the manifest is the one place that says what is trusted.
  - Unflagged entries, and PyPI and wheel entries, move by PR as now. A PyPI pin could follow later with
    `updates: releases`.
- **E3. A moved commit is checked against the repository.**
  - The API asks GitHub, anonymously, as `registry/catalog.py` does, that the commit exists and is on the default
    branch, or is a tag's.
  - Anything else is a 422. Branch names are never accepted, only a full commit; `HEAD` of the branch, resolved and
    recorded, is the convenience form.
- **E4. The manifest's commit becomes the default for new versions.**
  - "Which commit is live" is the default version, as the API and web pages already show.
  - The manifest comment says so. Nothing writes the manifest back automatically; see open question 2.
- **E5. Compliance gates a moved commit (step 2).**
  - **Admission:** in a version whose entry commit differs from the manifest's, that entry's classes are refused until
    its cases have passed, instead of keeping the manifest's level. An entry with no cases at all cannot move (E2's
    flag requires cases).
  - **Default:** `PUT …/default` refuses a version with a failed or unfinished case of a moved entry.
- **E6. Who, when and why are recorded.** Versions already keep their creator's subject, time and a note. The
  version's response shows each moved entry as "moved from <manifest commit> to <commit>", so a reviewer reads the
  change where it takes effect.

## Work

### 1. The flag, and versions at a moved commit
- `RegistryEntry.updates: Literal["main", "tags"] | None` in `registry/manifest.py`.
  - A git entry only, with compliance cases under `registry/compliance/<entry>/`; validated in the manifest's tests.
- `NewEnvironmentVersion.entries: dict[str, str]` (entry id to commit) on `POST …/versions`, for composed environments
  and mash-ups.
  - Refused (422) for an unflagged entry, an entry the environment does not have, a commit that fails E3, or a
    prebuilt environment.
  - The spec's entry carries the commit, so the version's identity and its "same definition" answer include it.
- CLI: `compose-api environments create <name> --entry viva-pde-particle=<sha>` (repeatable), and
  `--entry viva-pde-particle=main` to resolve the branch's head (E3).
- Flag viva-pde-particle `updates: main` in the same PR. It has compliance cases, and its own CI runs this service's
  job contract on every push.

### 2. Compliance gates it
- **Admission:** `admission.standing_of` marks a moved entry. `registry/validation.py` refuses its classes unless its
  cases passed in that version.
- **Default:** `PUT …/default` returns 409 for a version whose moved entries have failed or unfinished cases.
- **Tests:**
  - a moved entry is refused while its cases run and admitted once they pass;
  - the default is refused before that;
  - an unmoved entry behaves as now.

### 3. The web page
- An environment's page lists commits on a flagged entry's branch newer than the default version's, from GitHub.
- For an administrator, a "Make a version at this commit" action, then the compliance report as it fills in.

### 4. (Later) candidates by the service
- A scheduled check, or a webhook from the repository, makes a candidate version when a flagged repository moves.
  It never makes it the default.
- Only if step 3's manual flow turns out to be too slow. It needs no change in vivarium-collective repositories if
  it polls.

## Pros and cons (from the discussion, 2026-10-29)

- **For:**
  - A routine upstream fix reaches runs with two CLI calls, or one page action, and no compose-api release.
  - Review stays where it decides something: which repository is trusted and how it installs.
  - Composed environments move the way prebuilt ones already do.
  - Reproducibility and rollback are unchanged (versions, locks, explicit defaults).
- **Against, and what answers it:**
  - New code runs without a person reading it. Answered by: flagged entries only; the default branch or tags only;
    environment administrators only; refused until its compliance passes (E5).
  - The history of pins leaves `git log manifest.yaml`. Answered by: versions record who, when, why and from what
    (E6); optionally a write-back (open question 2).
  - Two places say "the commit". Answered by: E4's rule, and pages that show the default version's commits.
  - The compose-api PR's CI no longer runs for a bump. Our CI checks the manifest, not the upstream code, so
    compliance carries this. A flagged repository should run our job contract in its own CI, as viva-pde-particle's
    does.

## Verification
- Unit and API tests per step, as above.
- **Live after 1–2:**
  - `compose-api environments create mash-05956395cf --entry viva-pde-particle=<#69's merge>` makes @3;
  - a run naming @3 is refused for viva-pde-particle's classes until its cases pass, then admitted;
  - `environments default mash-05956395cf 3` succeeds only then.

## Open questions
1. `updates: main` or only `updates: tags` for viva-pde-particle? Step 1 flags it `main`, what its prebuilt image
   follows today; `tags` would need it to tag releases.
2. Write the defaults back? A scheduled PR that sets each flagged entry's manifest commit to its default version's
   would keep `git log` a readable history, at the cost of a bot PR per move.
3. Should a run that names a version explicitly be able to use a moved entry before its compliance passes, for the
   person testing it? E5 says no; an administrator's override is possible if that is too strict.
