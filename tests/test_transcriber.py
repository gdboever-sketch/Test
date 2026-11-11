from negotiator.transcriber import utterances_from_result


def _result(words, is_final=True):
    return {
        "type": "Results",
        "is_final": is_final,
        "channel": {"alternatives": [{"transcript": " ".join(w[1] for w in words), "words": [
            {"word": w[1].lower(), "punctuated_word": w[1], "speaker": w[0], "start": i, "end": i + 0.5}
            for i, w in enumerate(words)
        ]}]},
    }


def test_splits_by_speaker_turn():
    out = utterances_from_result(_result([(0, "Hello"), (0, "there."), (1, "Hi."), (0, "So,")]))
    assert [(u.speaker, u.text) for u in out] == [(0, "Hello there."), (1, "Hi."), (0, "So,")]
    assert out[0].render().startswith("[00:00] Speaker 0: Hello there.")


def test_ignores_interim_and_other_messages():
    assert utterances_from_result(_result([(0, "Hello")], is_final=False)) == []
    assert utterances_from_result({"type": "Metadata"}) == []
