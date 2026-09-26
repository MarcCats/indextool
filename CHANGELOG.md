# Changelog

A change that can alter the generated files bumps the minor version, and its entry has an "Output changes" line that
tells users to run `indextool generate` and commit the result. Patch releases never change output, so
`pip install "indextool~=X.Y.0"` is safe to pin.

The golden gate (`scripts/check_golden_bump.py`) enforces this once per release cycle, not once per change: it compares
each golden file at the head of a branch with the merge base of the branch and the target, and fails only when the
golden's text changed while its `indextool <major.minor>` header did not. A cycle that changes any golden output
therefore bumps the minor version once, however many changes it holds, and a golden that is new or deleted needs no bump.

## 0.1.0

First release.

Output changes: none (first release).
