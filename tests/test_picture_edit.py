"""Picture edits and see-through pictures (providers/chat_images.py), against a made-up chat endpoint.

Nothing reaches the network: the provider's client is a stand-in that records the request and answers with a
picture made here.
"""

import base64
import io

import pytest
from PIL import Image

from roundtable.providers import chat_images as C
from roundtable.providers.base import ProviderError


def png(im) -> bytes:
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


def on_magenta(size=(64, 64)) -> bytes:
    """A red square on a nearly-magenta background (models never hit the colour exactly)."""
    im = Image.new("RGB", size, (250, 6, 247))
    for x in range(16, 48):
        for y in range(16, 48):
            im.putpixel((x, y), (200, 20, 20))
    return png(im)


class FakeClient:
    def __init__(self, answer: bytes):
        self.calls = []
        self.answer = answer
        self.chat = self
        self.completions = self

    def create(self, **kw):
        self.calls.append(kw)
        url = "data:image/png;base64," + base64.b64encode(self.answer).decode()

        class Msg:
            images = [{"image_url": {"url": url}}]

        class Choice:
            message = Msg()

        class U:
            prompt_tokens, completion_tokens, cost = 10, 1290, 0.039

        class Resp:
            choices = [Choice()]
            usage = U()

        return Resp()


def provider(answer: bytes):
    p = C.ChatImagesProvider("openrouter-images", api_key_env=None, base_url="http://localhost:9/v1")
    p.client = FakeClient(answer)
    return p


EARLIER = png(Image.new("RGB", (8, 8), (10, 120, 40)))


def test_an_edit_sends_the_earlier_picture_with_the_instruction():
    p = provider(on_magenta())
    data, ext, usage = p.generate("google/gemini-2.5-flash-image", "make the tree autumn red",
                                  {"from_image": EARLIER, "aspect_ratio": "1:1"})
    assert ext == "png" and data == on_magenta()
    content = p.client.calls[0]["messages"][0]["content"]
    assert content[0] == {"type": "text", "text": "make the tree autumn red"}
    assert content[1]["image_url"]["url"] == "data:image/png;base64," + base64.b64encode(EARLIER).decode()
    assert p.client.calls[0]["extra_body"]["image_config"] == {"aspect_ratio": "1:1"}


def test_the_earlier_picture_can_be_a_file(tmp_path):
    f = tmp_path / "before.png"
    f.write_bytes(EARLIER)
    p = provider(on_magenta())
    p.generate("openai/gpt-5-image", "add a hat", {"from_image": str(f)})
    assert p.client.calls[0]["messages"][0]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")
    with pytest.raises(ProviderError, match="isn't there"):
        p.generate("openai/gpt-5-image", "add a hat", {"from_image": str(tmp_path / "gone.png")})
    with pytest.raises(ProviderError, match="isn't a PNG"):
        p.generate("openai/gpt-5-image", "add a hat", {"from_image": b"not a picture"})


def test_a_model_without_picture_in_is_refused_before_any_request():
    p = provider(on_magenta())
    with pytest.raises(ProviderError) as e:
        p.generate("someone/text-to-image-only", "make it red", {"from_image": EARLIER})
    assert not e.value.retryable
    assert "can't take an earlier picture to change, so nothing was sent and nothing was paid" in str(e.value)
    assert p.client.calls == []  # no request: no charge
    assert C.refusal("someone/text-to-image-only", {"from_image": EARLIER, "picture_in": True}) is None


def test_without_the_new_options_the_request_is_as_before():
    p = provider(on_magenta())
    p.generate("google/gemini-2.5-flash-image", "a cat", {"size": "2K"})
    call = p.client.calls[0]
    assert call["messages"] == [{"role": "user", "content": "a cat"}]
    assert call["extra_body"] == {"modalities": ["image", "text"], "usage": {"include": True},
                                  "image_config": {"image_size": "2K"}}


def test_see_through_is_cut_out_here_when_the_model_cannot():
    p = provider(on_magenta())
    record = {}
    data, ext, _ = p.generate("google/gemini-2.5-flash-image", "a red box", {"transparent": True, "record": record})
    assert ext == "png" and record == {"transparent": "cut-out", "from_image": False}
    text = p.client.calls[0]["messages"][0]["content"]
    assert text.startswith("a red box") and "#FF00FF" in text
    assert "background" not in p.client.calls[0]["extra_body"].get("image_config", {})
    im = Image.open(io.BytesIO(data))
    assert im.mode == "RGBA" and im.info.get("Transparent") == "cut-out"
    assert im.getpixel((0, 0))[3] == 0 and im.getpixel((63, 63))[3] == 0  # the background is clear
    assert im.getpixel((32, 32)) == (200, 20, 20, 255)  # the subject is kept as it was


def test_a_model_that_can_is_asked_and_its_answer_kept():
    clear = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
    clear.putpixel((5, 5), (255, 0, 0, 255))
    p = provider(png(clear))
    record = {}
    data, ext, _ = p.generate("openai/gpt-5-image", "a dot", {"transparent": True, "record": record})
    assert p.client.calls[0]["extra_body"]["image_config"] == {"background": "transparent"}
    assert record["transparent"] == "model"
    im = Image.open(io.BytesIO(data))
    assert im.info.get("Transparent") == "model" and im.getpixel((5, 5)) == (255, 0, 0, 255)


def test_a_model_asked_that_did_not_is_cut_out_from_its_own_background():
    white = Image.new("RGB", (32, 32), (255, 255, 255))
    for x in range(8, 24):
        white.putpixel((x, 16), (0, 0, 0))
    p = provider(png(white))
    record = {}
    data, _, _ = p.generate("openai/gpt-5-image", "a line", {"transparent": True, "record": record})
    assert record["transparent"] == "cut-out (from the model's own background)"
    im = Image.open(io.BytesIO(data))
    assert im.getpixel((0, 0))[3] == 0 and im.getpixel((10, 16))[3] == 255


def test_without_pillow_a_model_that_cannot_is_refused_first(monkeypatch):
    monkeypatch.setattr(C, "_has_pillow", lambda: False)
    p = provider(on_magenta())
    with pytest.raises(ProviderError, match="can't make a see-through picture"):
        p.generate("google/gemini-2.5-flash-image", "x", {"transparent": True})
    assert p.client.calls == []


def test_the_cut_out_on_a_made_up_picture_has_a_soft_edge():
    im = Image.new("RGB", (10, 1), (255, 0, 255))
    shades = [(255, 0, 255), (255, 40, 255), (255, 90, 255), (255, 130, 255), (0, 200, 0)]
    for x, c in enumerate(shades):
        im.putpixel((x, 0), c)
    out = Image.open(io.BytesIO(C.cut_out(png(im), C.KEY_COLOUR, tolerance=60)))
    alphas = [out.getpixel((x, 0))[3] for x in range(5)]
    assert alphas[0] == 0 and alphas[1] == 0 and 0 < alphas[2] < 255 and alphas[3] == 255 and alphas[4] == 255
