---
name: Pytest basics
when: Writing or fixing Python tests with pytest.
tags: [tests, python]
---
- Put tests in `tests/test_<thing>.py`; each test is a function named `test_...` that says in its name what must be true.
- One behaviour per test. Arrange, act, assert, in that order, with a blank line between them if it helps.
- Use plain `assert` with the value you expect: `assert total([2, 3]) == 5`. Pytest shows both sides when it fails.
- `tmp_path` gives each test its own empty folder; never write into the project or the home folder.
- `monkeypatch.setattr` and `monkeypatch.setenv` change things for one test only and put them back afterwards.
- `pytest.raises(ValueError, match="...")` checks an error and its message.
- `@pytest.mark.parametrize` runs the same test over a small table of inputs instead of copying it.
- Shared set-up goes in a fixture (in the test file, or `tests/conftest.py` when several files use it).
- No network, no real keys, no sleeping: replace the slow or outside part with a small fake.
- Run `python -m pytest -q` (or just the file you changed) before you finish, and fix what fails rather than loosening the test.
