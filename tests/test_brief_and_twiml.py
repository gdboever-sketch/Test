import pytest

from negotiator.telephony import build_twiml, media_stream_url, normalize_digits


def test_brief_renders_key_fields(brief):
    text = brief.render()
    assert "BATNA" in text
    assert "Annual price (priority 5)" in text
    assert text.index("Annual price") < text.index("Payment terms")  # sorted by priority
    assert "The competitor's exact quote" in text


def test_twiml_dials_digits_announces_and_streams(settings):
    xml = build_twiml(settings, "abc123", "tok", "wwww123#")
    assert '<Play digits="wwww123#"' in xml
    assert "<Say>" in xml and "AI note taking assistant" in xml
    assert 'url="wss://coach.example.com/media/abc123"' in xml
    assert '<Parameter name="token" value="tok"' in xml
    assert xml.index("<Play") < xml.index("<Say") < xml.index("<Connect")


def test_twiml_can_skip_announcement(settings):
    settings.announce_on_join = False
    assert "<Say" not in build_twiml(settings, "abc", "tok", None)


def test_media_url_requires_public_url(settings):
    settings.public_base_url = ""
    with pytest.raises(ValueError):
        media_stream_url(settings, "abc")


@pytest.mark.parametrize("raw,expected", [("123, 456#", "123w456#"), ("", None), (None, None)])
def test_normalize_digits(raw, expected):
    assert normalize_digits(raw) == expected


def test_normalize_digits_rejects_junk():
    with pytest.raises(ValueError):
        normalize_digits("123<Hangup/>")
