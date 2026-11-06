import hashlib
import json

from worker.clean import REASONS, clean, parse_shards, serialise


def rec(i, text, raw):
    return {"id": f"C{i:04d}", "text": text, "teacher_raw": raw}


GOOD = '{"intent": "weather_query", "date": null, "time": null, "place": "london"}'


def test_each_rejection_reason_and_counts_add_up():
    recs = [
        rec(1, "what is the weather in london", GOOD),
        rec(2, "what is the weather in london", GOOD),                       # duplicate of 1
        rec(3, "wake me up", "```json\n{}\n```"),                            # (a)
        rec(4, "wake me up", '{"intent": "alarm_set", "date": null}'),      # (b)
        rec(5, "wake me up", '{"intent": "wake", "date": null, "time": null, "place": null}'),  # (c)
        rec(6, "wake me at six", '{"intent": "alarm_set", "date": null, "time": "06:00", "place": null}'),  # (d)
        rec(7, "wake me at six", '{"intent": "alarm_set", "date": null, "time": "Six", "place": null}'),
    ]
    kept, c = clean(recs)
    assert [r["id"] for r in kept] == ["C0001", "C0007"]
    assert c["invalid_json"] == 1 and c["wrong_keys"] == 1 and c["bad_intent"] == 1
    assert c["slot_not_in_command"] == 1 and c["duplicates"] == 1 and c["kept"] == 2
    assert c["input"] == sum(c[r] for r in REASONS) + c["duplicates"] + c["kept"]


def test_teacher_raw_preserved_and_target_canonical():
    raw = '{"place": "london", "intent": "weather_query", "time": null, "date": null}  '
    kept, _ = clean([rec(1, "weather in london", raw)])
    assert kept[0]["teacher_raw"] == raw
    assert list(json.loads(kept[0]["target"])) == ["intent", "date", "time", "place"]


def test_output_is_sorted_and_deterministic():
    shard0 = "\n".join(json.dumps(rec(i, f"weather in london {i}", GOOD)) for i in (3, 1))
    shard1 = json.dumps(rec(2, "weather in london 2", GOOD))
    a = serialise(clean(parse_shards([shard0, shard1]))[0])
    b = serialise(clean(parse_shards([shard1, shard0]))[0])
    assert a == b
    assert [json.loads(x)["id"] for x in a.decode().splitlines()] == ["C0001", "C0002", "C0003"]
    assert hashlib.sha256(a).hexdigest() == hashlib.sha256(b).hexdigest()
