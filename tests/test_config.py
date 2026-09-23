import json

from voicecli.config import Config, config_path


def write(data) -> None:
    config_path().parent.mkdir(parents=True, exist_ok=True)
    config_path().write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")


def test_missing_file_gives_defaults():
    assert Config.load() == Config()


def test_corrupt_or_non_object_file_gives_defaults():
    write("{not json")
    assert Config.load() == Config()
    write([1, 2, 3])
    assert Config.load() == Config()


def test_bad_fields_fall_back_one_by_one():
    write({"model": "base.en", "opacity": "loud", "auto_enter": "yes", "port": 80,
           "silence_ms": 900, "mode": "shout", "overlay_x": -40, "device": None, "unknown": 1})
    cfg = Config.load()
    assert cfg.model == "base.en" and cfg.silence_ms == 900 and cfg.overlay_x == -40  # valid ones kept
    assert cfg.opacity == 1.0 and cfg.auto_enter is False and cfg.port == 47821  # bad ones reset
    assert cfg.mode == "ptt"
    assert cfg.device is None


def test_int_accepted_for_float_but_bool_is_not_an_int():
    cfg = Config.from_dict({"opacity": 1, "silence_ms": True})
    assert cfg.opacity == 1.0 and isinstance(cfg.opacity, float)
    assert cfg.silence_ms == 700


def test_save_is_atomic_and_round_trips():
    cfg = Config(model="tiny.en", overlay_x=10, log_transcripts=True)
    cfg.save()
    assert not list(config_path().parent.glob("*.tmp"))
    assert Config.load() == cfg
