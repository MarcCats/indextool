import re
from pathlib import Path

README = (Path(__file__).resolve().parent.parent / "README.md").read_text(encoding="utf-8")


def test_the_headline_claim_is_only_what_ci_enforces():
    first_paragraph = README.split("\n\n")[1]
    assert "cannot silently diverge" in first_paragraph


def test_limits_are_stated_up_front():
    top = README[:2500]
    assert "Python only" in top
    assert "structure, not intent" in top
    assert "importlib" in README
    flat = " ".join(top.split())  # the README wraps its lines; the clause must hold wherever the wrap falls
    assert "only where a configured detector matches" in flat
    assert "no route or table outside the detectors is seen" in flat


def test_no_token_saving_figure_is_advertised():
    assert not re.search(r"\d+\s*%", README)
    assert "fewer tokens" not in README.lower()


def test_related_work_credits_prior_art_without_claiming_a_new_category():
    assert "Related work" in README
    assert "not a new category" in README
