from pathlib import Path
from evaluation.downstream import estimate_downstream_read_tokens

def test_full_file_costs_more_than_slice(tmp_path):
    src = tmp_path / "auth.py"
    src.write_text("def login():\n    pass\n" * 50)  # ~100 lines
    items_full = [{"path": str(src), "lines": None}]
    items_slice = [{"path": str(src), "lines": [1, 10]}]
    full_cost = estimate_downstream_read_tokens(items_full, project_root=tmp_path)
    slice_cost = estimate_downstream_read_tokens(items_slice, project_root=tmp_path)
    assert full_cost > slice_cost, "Full file read must cost more than a 10-line slice"

def test_missing_file_returns_zero(tmp_path):
    items = [{"path": str(tmp_path / "nonexistent.py"), "lines": None}]
    cost = estimate_downstream_read_tokens(items, project_root=tmp_path)
    assert cost == 0

def test_multiple_items_summed(tmp_path):
    f1 = tmp_path / "a.py"
    f2 = tmp_path / "b.py"
    f1.write_text("x = 1\n" * 100)
    f2.write_text("y = 2\n" * 50)
    items = [
        {"path": str(f1), "lines": None},
        {"path": str(f2), "lines": None},
    ]
    cost = estimate_downstream_read_tokens(items, project_root=tmp_path)
    single = estimate_downstream_read_tokens([{"path": str(f1), "lines": None}], project_root=tmp_path)
    assert cost > single, "Two files must cost more than one"
