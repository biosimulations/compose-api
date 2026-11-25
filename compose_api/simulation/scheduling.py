"""Which queued runs go next (docs/plan-durable-submission.md, Q3): the seam for fair scheduling.

The worker claims due submissions highest priority first, oldest first, then asks the policy which of them to work on
now; the others are put back for a little while. The policy caps the load the queue puts on the cluster: the number of
runs on SLURM (or about to be), the share of that a single non-interactive queue (a suite run) may take, the number of
one requester's interactive runs, and the number of runs making an image ready at once.

A requester at its cap is also left out of the claim (``claim_submissions(requester_cap=...)``). Putting its rows back
would not be enough: they come due again, still the oldest, before anyone else's rows are reached, so one person's
backlog would starve everyone queued after it. ``select`` applies the cap within one claim, whose rows the claim's own
count doesn't see.

The overall and queue caps count runs submitting or on SLURM, so the runs a worker holds on their way to sbatch
(``requested``, ``preparing``, at most ``submission_worker_concurrency`` per worker) can pass them briefly. One
requester's cap counts those held runs too, so one worker never passes it; two workers claiming at the same moment can,
by at most one claim each. A run already ``submitting`` (one whose sbatch waits to be retried, say) is counted, so no
count holds it back, and the claim takes it first, or a queue or requester whose submits all failed would never be
resumed.
"""

from collections import Counter
from dataclasses import dataclass, field

from compose_api.config import get_settings
from compose_api.simulation.models import Submission, SubmissionState

INTERACTIVE = "interactive"


@dataclass
class Load:
    """What the queue has on the cluster now: active runs per queue (submitting, or on SLURM and unfinished), the
    interactive ones per requester (None: anonymous) with those a worker holds on their way to sbatch, and runs whose
    image is being made ready."""

    active: Counter[str] = field(default_factory=Counter)
    preparing: int = 0
    active_by_requester: Counter[str | None] = field(default_factory=Counter)


@dataclass(frozen=True)
class SubmissionPolicy:
    max_active: int
    queue_share: float
    max_preparing: int
    max_active_per_requester: int | None = None  # None: only the overall cap

    @classmethod
    def from_settings(cls) -> "SubmissionPolicy":
        settings = get_settings()
        return cls(
            max_active=settings.submission_max_active_jobs,
            queue_share=settings.submission_queue_share,
            max_preparing=settings.submission_max_preparing,
            max_active_per_requester=settings.submission_max_active_per_requester,
        )

    def queue_cap(self, queue: str) -> int:
        """How many active runs ``queue`` may have: interactive work only the overall cap, any other queue its share."""
        return self.max_active if queue == INTERACTIVE else max(1, int(self.max_active * self.queue_share))

    def select(self, candidates: list[Submission], load: Load) -> tuple[list[Submission], list[Submission]]:
        """``candidates`` (in claim order) split into those to work on now and those to put back."""
        active = Counter(load.active)
        by_requester = Counter(load.active_by_requester)
        cap = self.max_active_per_requester
        preparing = load.preparing
        go: list[Submission] = []
        wait: list[Submission] = []
        for c in candidates:
            needs_image = c.state in (SubmissionState.REQUESTED, SubmissionState.PREPARING)
            interactive = c.queue == INTERACTIVE
            counted = c.state is SubmissionState.SUBMITTING  # already in the load: resuming it adds nothing
            if (
                not counted
                and (
                    sum(active.values()) >= self.max_active
                    or active[c.queue] >= self.queue_cap(c.queue)
                    or (interactive and cap is not None and by_requester[c.requested_by] >= cap)
                )
            ) or (needs_image and preparing >= self.max_preparing):
                wait.append(c)
                continue
            go.append(c)
            if not counted:
                active[c.queue] += 1
                by_requester[c.requested_by] += interactive
            preparing += needs_image
        return go, wait
