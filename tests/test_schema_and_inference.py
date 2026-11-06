from app.inference import build_prompt, trim_after_object
from app.schema import Schema

S = Schema.load(None)


def test_valid_frame_accepted_in_key_order():
    out = S.validate('{"place": "tokyo", "time": null, "date": null, "intent": "datetime_query"}')
    assert list(out) == ["intent", "date", "time", "place"]


def test_invalid_frames_rejected():
    for raw in ["not json", '{"intent": "alarm_set"}', "[1, 2]",
                '{"intent": "dance", "date": null, "time": null, "place": null}',
                '{"intent": "alarm_set", "date": 5, "time": null, "place": null}',
                '{"intent": "alarm_set", "date": null, "time": null, "place": null, "x": 1}']:
        assert S.validate(raw) is None, raw


def test_trim_stops_after_first_object():
    assert trim_after_object(' {"a": "x}"} more text {"b": 1}') == '{"a": "x}"}'
    assert trim_after_object(' {"a": "unfinish') == '{"a": "unfinish'


def test_prompt_format():
    assert build_prompt("  wake me up ") == "Command: wake me up\nJSON:"
