"""Contract test for src.data.loaders (owner: M1). Keeps public signatures as listed in CLAUDE.md section 5."""
import inspect

import src.data.loaders as m


def test_load_and_clean_signature() -> None:
    assert list(inspect.signature(m.load_and_clean).parameters) == ['seed_dir']
