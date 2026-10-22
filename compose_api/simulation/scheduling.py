"""Which queued runs go next (docs/plan-durable-submission.md, Q3): the seam for fair scheduling.

The worker claims due submissions highest priority first, oldest first, then asks the policy which of them to work on
now; the others are put back for a little while. The first policy caps the load the queue puts on the cluster: the
number of runs on SLURM (or about to be), the share of that a single non-interactive queue (a suite run) may take, and
the number of runs making an image ready at once. A fair-share policy (per requester, or round-robin across queues)
can replace it: the queue, priority and requester of every row are already recorded.
"""

from collections import Counter
from dataclasses import dataclass, field

from compose_api.config import get_settings
from compose_api.simulation.models import Submission, SubmissionState

INTERACTIVE = "interactive"


@dataclass
class Load:
    """What the queue has on the cluster now: active runs per queue (submitting, or on SLURM and unfinished), and runs
    whose image is being made ready."""

    active: Counter[str] = field(default_factory=Counter)
    preparing: int = 0


@dataclass(frozen=True)
class SubmissionPolicy:
    max_active: int
    queue_share: float
    max_preparing: int

    @classmethod
    def from_settings(cls) -> "SubmissionPolicy":
        settings = get_settings()
        return cls(
            max_active=settings.submission_max_active_jobs,
            queue_share=settings.submission_queue_share,
            max_preparing=settings.submission_max_preparing,
        )

    def queue_cap(self, queue: str) -> int:
        """How many active runs ``queue`` may have: interactive work only the overall cap, any other queue its share."""
        return self.max_active if queue == INTERACTIVE else max(1, int(self.max_active * self.queue_share))

    def select(self, candidates: list[Submission], load: Load) -> tuple[list[Submission], list[Submission]]:
        """``candidates`` (in claim order) split into those to work on now and those to put back."""
        active = Counter(load.active)
        preparing = load.preparing
        go: list[Submission] = []
        wait: list[Submission] = []
        for c in candidates:
            needs_image = c.state in (SubmissionState.REQUESTED, SubmissionState.PREPARING)
            if (
                sum(active.values()) >= self.max_active
                or active[c.queue] >= self.queue_cap(c.queue)
                or (needs_image and preparing >= self.max_preparing)
            ):
                wait.append(c)
                continue
            go.append(c)
            active[c.queue] += 1
            preparing += needs_image
        return go, wait
