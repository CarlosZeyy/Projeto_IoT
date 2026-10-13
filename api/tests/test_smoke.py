import qc_api


def test_import_and_version() -> None:
    assert qc_api.__version__ == "0.1.0"
