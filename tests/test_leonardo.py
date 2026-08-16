"""Tests for verticals/leonardo.py — init-image upload and img2img generation.

Every requests call and every sleep is patched. Both public functions are
wrapped in @with_retry, so failure tests patch verticals.retry.time.sleep to
keep backoff out of the run, and the polling loop's own time.sleep is patched
via the leonardo module.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from verticals import leonardo


def _resp(payload=None, content=b"", status_error=None):
    r = MagicMock()
    r.json.return_value = payload or {}
    r.content = content
    if status_error:
        r.raise_for_status.side_effect = status_error
    return r


@pytest.fixture(autouse=True)
def no_sleep():
    """Neither the poll loop nor the retry decorator should really wait."""
    with patch("verticals.leonardo.time.sleep"), patch("verticals.retry.time.sleep"):
        yield


class TestGetLeonardoKey:
    def test_delegates_to_get_key(self):
        with patch("verticals.leonardo._get_key", return_value="k") as gk:
            assert leonardo.get_leonardo_key() == "k"
        gk.assert_called_once_with("LEONARDO_API_KEY")


class TestHeaders:
    def test_sends_key_as_bearer_not_query_param(self):
        h = leonardo._headers("secret")
        assert h["Authorization"] == "Bearer secret"
        assert h["Content-Type"] == "application/json"


class TestUploadInitImage:
    def _presign(self, fields):
        return {"uploadInitImage": {"url": "https://up", "id": "img-1", "fields": fields}}

    def test_returns_image_id_with_json_string_fields(self, tmp_path):
        img = tmp_path / "otto.png"
        img.write_bytes(b"png")
        with patch("verticals.leonardo.requests.post") as post:
            post.side_effect = [_resp(self._presign('{"key": "v"}')), _resp()]
            assert leonardo._upload_init_image(img, "k") == "img-1"
        # Second call is the presigned upload, which takes form fields + file.
        assert post.call_args_list[1].args[0] == "https://up"
        assert post.call_args_list[1].kwargs["data"] == {"key": "v"}

    def test_accepts_dict_fields(self, tmp_path):
        img = tmp_path / "otto.png"
        img.write_bytes(b"png")
        with patch("verticals.leonardo.requests.post") as post:
            post.side_effect = [_resp(self._presign({"key": "v"})), _resp()]
            assert leonardo._upload_init_image(img, "k") == "img-1"

    def test_empty_fields_string_becomes_empty_dict(self, tmp_path):
        img = tmp_path / "otto.png"
        img.write_bytes(b"png")
        with patch("verticals.leonardo.requests.post") as post:
            post.side_effect = [_resp(self._presign("")), _resp()]
            leonardo._upload_init_image(img, "k")
        assert post.call_args_list[1].kwargs["data"] == {}

    def test_sends_extension_without_dot(self, tmp_path):
        img = tmp_path / "otto.jpg"
        img.write_bytes(b"jpg")
        with patch("verticals.leonardo.requests.post") as post:
            post.side_effect = [_resp(self._presign("")), _resp()]
            leonardo._upload_init_image(img, "k")
        assert post.call_args_list[0].kwargs["json"] == {"extension": "jpg"}

    def test_raises_when_presign_fails(self, tmp_path):
        img = tmp_path / "otto.png"
        img.write_bytes(b"png")
        with patch("verticals.leonardo.requests.post",
                   return_value=_resp(status_error=RuntimeError("500"))):
            with pytest.raises(RuntimeError, match="500"):
                leonardo._upload_init_image(img, "k")


class TestGenerateImageLeonardo:
    START = {"sdGenerationJob": {"generationId": "gen-1"}}

    def _poll(self, status, images=None):
        return {"generations_by_pk": {"status": status,
                                      "generated_images": images if images is not None else []}}

    def test_writes_image_on_completion(self, tmp_path):
        out = tmp_path / "frame.png"
        with patch("verticals.leonardo.requests.post", return_value=_resp(self.START)), \
             patch("verticals.leonardo.requests.get") as get:
            get.side_effect = [
                _resp(self._poll("COMPLETE", [{"url": "https://img"}])),
                _resp(content=b"IMAGEBYTES"),
            ]
            leonardo.generate_image_leonardo("a dog", out, "k")
        assert out.read_bytes() == b"IMAGEBYTES"

    def test_polls_until_complete(self, tmp_path):
        out = tmp_path / "frame.png"
        with patch("verticals.leonardo.requests.post", return_value=_resp(self.START)), \
             patch("verticals.leonardo.requests.get") as get:
            get.side_effect = [
                _resp(self._poll("PENDING")),
                _resp(self._poll("PENDING")),
                _resp(self._poll("COMPLETE", [{"url": "https://img"}])),
                _resp(content=b"X"),
            ]
            leonardo.generate_image_leonardo("a dog", out, "k")
        assert get.call_count == 4

    def test_raises_on_failed_status(self, tmp_path):
        with patch("verticals.leonardo.requests.post", return_value=_resp(self.START)), \
             patch("verticals.leonardo.requests.get",
                   return_value=_resp(self._poll("FAILED"))):
            with pytest.raises(RuntimeError, match="generation failed"):
                leonardo.generate_image_leonardo("p", tmp_path / "o.png", "k")

    def test_raises_when_complete_but_no_images(self, tmp_path):
        with patch("verticals.leonardo.requests.post", return_value=_resp(self.START)), \
             patch("verticals.leonardo.requests.get",
                   return_value=_resp(self._poll("COMPLETE", []))):
            with pytest.raises(RuntimeError, match="no images returned"):
                leonardo.generate_image_leonardo("p", tmp_path / "o.png", "k")

    def test_times_out_after_24_polls(self, tmp_path):
        with patch("verticals.leonardo.requests.post", return_value=_resp(self.START)), \
             patch("verticals.leonardo.requests.get",
                   return_value=_resp(self._poll("PENDING"))) as get:
            with pytest.raises(RuntimeError, match="timed out"):
                leonardo.generate_image_leonardo("p", tmp_path / "o.png", "k")
        # 24 polls per attempt, and @with_retry(max_retries=3) means the whole
        # 120s wait runs 4 times over. Worth seeing plainly: a hung Leonardo
        # job blocks for ~8 minutes before the caller gets its exception.
        assert get.call_count == 24 * 4

    def test_body_defaults(self, tmp_path):
        with patch("verticals.leonardo.requests.post", return_value=_resp(self.START)) as post, \
             patch("verticals.leonardo.requests.get") as get:
            get.side_effect = [_resp(self._poll("COMPLETE", [{"url": "u"}])), _resp(content=b"x")]
            leonardo.generate_image_leonardo("a dog", tmp_path / "o.png", "k")
        body = post.call_args.kwargs["json"]
        assert body["prompt"] == "a dog"
        assert (body["width"], body["height"]) == (576, 1024)  # 9:16
        assert body["num_images"] == 1
        assert "init_image_id" not in body  # no reference supplied

    def test_reference_image_switches_to_img2img(self, tmp_path):
        ref = tmp_path / "otto.png"
        ref.write_bytes(b"png")
        with patch("verticals.leonardo._upload_init_image", return_value="img-9") as up, \
             patch("verticals.leonardo.requests.post", return_value=_resp(self.START)) as post, \
             patch("verticals.leonardo.requests.get") as get:
            get.side_effect = [_resp(self._poll("COMPLETE", [{"url": "u"}])), _resp(content=b"x")]
            leonardo.generate_image_leonardo(
                "a dog", tmp_path / "o.png", "k",
                reference_image_path=ref, init_strength=0.42,
            )
        up.assert_called_once()
        body = post.call_args.kwargs["json"]
        assert body["init_image_id"] == "img-9"
        assert body["init_strength"] == 0.42

    def test_missing_reference_image_is_skipped(self, tmp_path):
        with patch("verticals.leonardo._upload_init_image") as up, \
             patch("verticals.leonardo.requests.post", return_value=_resp(self.START)) as post, \
             patch("verticals.leonardo.requests.get") as get:
            get.side_effect = [_resp(self._poll("COMPLETE", [{"url": "u"}])), _resp(content=b"x")]
            leonardo.generate_image_leonardo(
                "a dog", tmp_path / "o.png", "k",
                reference_image_path=Path(tmp_path / "absent.png"),
            )
        up.assert_not_called()
        assert "init_image_id" not in post.call_args.kwargs["json"]

    def test_negative_prompt_sent_when_supplied(self, tmp_path):
        with patch("verticals.leonardo.requests.post", return_value=_resp(self.START)) as post, \
             patch("verticals.leonardo.requests.get") as get:
            get.side_effect = [_resp(self._poll("COMPLETE", [{"url": "u"}])), _resp(content=b"x")]
            leonardo.generate_image_leonardo(
                "a doorway", tmp_path / "o.png", "k",
                negative_prompt="text, words, gibberish text",
            )
        # The API's own exclusion field — "no text" in the positive prompt does
        # not suppress lettering, which is what produced garbled labels.
        assert post.call_args.kwargs["json"]["negative_prompt"] == "text, words, gibberish text"

    def test_negative_prompt_omitted_when_empty(self, tmp_path):
        with patch("verticals.leonardo.requests.post", return_value=_resp(self.START)) as post, \
             patch("verticals.leonardo.requests.get") as get:
            get.side_effect = [_resp(self._poll("COMPLETE", [{"url": "u"}])), _resp(content=b"x")]
            leonardo.generate_image_leonardo("a doorway", tmp_path / "o.png", "k")
        assert "negative_prompt" not in post.call_args.kwargs["json"]
