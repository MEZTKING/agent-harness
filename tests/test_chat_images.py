import base64

import pytest

from roundtable.providers.base import ProviderError
from roundtable.providers.chat_images import picture_from_message


def test_picture_is_read_from_the_chat_answer():
    png = b"\x89PNG\r\n\x1a\nfake"

    class Msg:
        images = [{"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(png).decode()}}]

    class Extra:
        images = None
        model_extra = {"images": [{"image_url": {"url": "data:image/webp;base64," + base64.b64encode(b"w").decode()}}]}

    assert picture_from_message(Msg()) == (png, "png")
    assert picture_from_message(Extra()) == (b"w", "webp")

    class Empty:
        images = []
        model_extra = {}

    with pytest.raises(ProviderError):
        picture_from_message(Empty())
