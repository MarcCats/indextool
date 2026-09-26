# Measure it on your own repository

Two afternoons. Decide the bar before you run anything, and report both directions.

**Setup.** Same commit, a fresh session per run, same model and settings. Arm A: your current architecture notes and
no map. Arm B: the map, the pointer and the hook installed by `indextool init`. Four runs per task per arm.

**Tasks.** One architecture overview ("describe how this system is laid out and what writes its main tables"); one
lookup a grep answers ("where is X computed"); one trivial named edit. Optionally one impact task ("change table T's
schema and update its dependents").

**Measure.** Tokens after the first turn and the tool-call count, from the transcript; wrong claims per overview,
counted by a blind grader with a fixed rubric; pass or fail on the edits.

**Bar.** Overview: at least 15% fewer tokens at no loss of accuracy. Trivial edit: no more than 5% extra cost.
Lookup: expect no change.

**Report both directions.** A result that misses the bar is still a result. If the overview bar is missed but the
notes you had were found to be wrong, the freshness guarantee is the reason to keep the map, not the token count.

The pointer text `init` writes carries no numbers, because a figure in hand-written text goes stale. If you change the
wording, measure it the same way: how the pointer is worded changes how often the assistant opens the map.
