import pytest

from prank_news.models import NewsRequest


@pytest.mark.parametrize("minutes", [0.5, 15])
def test_request_limits(minutes):
    request = NewsRequest([" 王小明 "], minutes, "")
    assert request.passenger_names == ["王小明"]
    assert request.voice == "zh-TW-HsiaoChenNeural"


@pytest.mark.parametrize("minutes", [0.49, 15.01, float("nan"), float("inf"), True, "3"])
def test_reject_invalid_duration(minutes):
    with pytest.raises(ValueError):
        NewsRequest(["王小明"], minutes, "")


@pytest.mark.parametrize("names", [[], [""], [" "], "王小明", [None]])
def test_reject_invalid_names(names):
    with pytest.raises(ValueError):
        NewsRequest(names, 3, "")
