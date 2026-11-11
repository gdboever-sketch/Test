# Strategy playbook

This folder is the coach's context repository: the negotiation strategies it
draws on during a call. Each strategy is a Markdown file. The coach reads all of
them at the start of a call, and every suggestion on the dashboard shows the
strategy it came from.

## Format

```markdown
---
id: conditional-concessions          # lowercase-with-dashes, unique
name: Conditional concessions
category: concessions                # one of the categories below
summary: One sentence the coach can apply at a glance.
use_when:                            # situations where this strategy fits
  - ...
signals:                             # words or patterns to listen for in the transcript
  - "Can you do a bit better on...?"
avoid_when:                          # when not to use it
  - ...
---
## Moves
What the coach should suggest, step by step.

## Say it like this
Example phrases the user can say almost word for word.

## Watch out
Pitfalls, limits, and ethical boundaries.
```

Categories: `preparation`, `opening`, `information`, `value-creation`,
`concessions`, `closing`, `defense`. Subfolders are only for organisation; any
`.md` file in this tree except README files is loaded.

## Writing good strategies

- Make `signals` concrete. They are how the coach recognises the moment in
  the transcript.
- Keep "Say it like this" short. The user reads it mid-sentence.
- Write `avoid_when` as carefully as `use_when`. A strategy used in the wrong
  situation costs more than not using it.
- Strategies must be honest. The coach is told never to suggest lying,
  fabricated offers, or misrepresentation, so keep tactics like those out of
  the playbook. Recognising and defending against them belongs in `defense/`.

## Choosing strategies per negotiation

In a brief, name strategies to favour or to leave out:

```yaml
preferred_strategies: [trade-across-issues, objective-criteria]
excluded_strategies: [strategic-silence]
```

## Checking and using the playbook

```bash
negotiator strategies check            # validate every file
negotiator strategies list             # list ids by category
STRATEGIES_DIR=/path/to/your/playbook negotiator serve
```

`STRATEGIES_DIR` can point to a separate Git repository, so you can version and
share a playbook independently of the agent's code.
