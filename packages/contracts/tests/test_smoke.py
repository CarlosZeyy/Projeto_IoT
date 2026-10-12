import qc_contracts


def test_import_and_version() -> None:
    assert qc_contracts.__version__ == "0.0.0"
