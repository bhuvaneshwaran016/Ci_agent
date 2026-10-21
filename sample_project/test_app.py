
from app import add, maximum


def test_add():
    assert add(2, 3) == 5


def test_maximum():
    assert maximum(3, 5) == 5
