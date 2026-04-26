import pytest
import os
from pathlib import Path

# Get the directory of this conftest.py
TEST_DIR = Path(__file__).parent
TEST_DATA_DIR = TEST_DIR / "test_data"
ROOT_DIR = TEST_DIR.parent

@pytest.fixture(scope="session")
def sample_diff_path():
    return str(ROOT_DIR / "examples" / "sample.diff")

@pytest.fixture(scope="session")
def sample_p4_diff_path():
    return str(ROOT_DIR / "examples" / "sample_p4.diff")

@pytest.fixture(scope="session")
def sample_c_path():
    return str(ROOT_DIR / "examples" / "sample.c")

@pytest.fixture(scope="session")
def config_path():
    return str(ROOT_DIR / "config.yaml")

@pytest.fixture
def git_diff_text(sample_diff_path):
    with open(sample_diff_path, 'r') as f:
        return f.read()

@pytest.fixture
def p4_diff_text(sample_p4_diff_path):
    with open(sample_p4_diff_path, 'r') as f:
        return f.read()

@pytest.fixture
def cstyle_module():
    import sys
    sys.path.insert(0, str(ROOT_DIR))
    import cstyle
    return cstyle
