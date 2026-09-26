import indextool


def test_version_and_format_version():
    assert indextool.__version__ == "0.1.0"
    assert indextool.FORMAT_VERSION == "0.1"
