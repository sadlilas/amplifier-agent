import amplifier_agent_lib


def test_package_importable() -> None:
    assert isinstance(amplifier_agent_lib.__version__, str)
    assert len(amplifier_agent_lib.__version__) > 0
