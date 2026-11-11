---
id: shrinking-concessions
name: Shrinking concessions
category: concessions
summary: Make each concession smaller and slower than the last, which signals that you are approaching your limit.
use_when:
  - The user is moving on a number over several rounds
  - The user's concessions are growing or keeping a steady size
signals:
  - Successive offers from "us" in the ledger with equal or growing steps
  - Quick replies with new numbers
avoid_when:
  - The user's opening was so far off that a large first move is needed to stay credible
---
## Moves
- Track the size of the user's concessions in the ledger. Warn if a step is as big as or bigger than the last one.
- Suggest the next step size: roughly half the previous one.
- Pair each step with a reason and a pause, so it is clearly costly.

## Say it like this
- "We moved $20k last time. We can find another $8k, and that's stretching it."

## Watch out
- Also read the counterpart's pattern: shrinking steps from them suggest their limit is near.
