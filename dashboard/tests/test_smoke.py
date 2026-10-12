import qc_dashboard


def test_import_and_version() -> None:
    assert qc_dashboard.__version__ == "0.0.0"
