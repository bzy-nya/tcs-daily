from __future__ import annotations

import unittest
from http.client import IncompleteRead
from unittest.mock import patch

from tcs_daily import _http


class _Response:
    def __init__(
        self,
        *,
        payload: bytes = b"",
        error: Exception | None = None,
        status: int = 200,
    ) -> None:
        self.payload = payload
        self.error = error
        self.status = status

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        if self.error is not None:
            raise self.error
        return self.payload


class HttpRetryTests(unittest.TestCase):
    def test_get_retries_incomplete_response(self) -> None:
        responses = [
            _Response(error=IncompleteRead(b"partial", 4)),
            _Response(payload=b"complete"),
        ]

        with (
            patch.object(_http, "urlopen", side_effect=responses) as urlopen,
            patch.object(_http.time, "sleep") as sleep,
        ):
            result = _http.get("https://example.test/paper.pdf", retries=2)

        self.assertEqual(result, b"complete")
        self.assertEqual(urlopen.call_count, 2)
        sleep.assert_called_once_with(1)

    def test_get_resumes_incomplete_response_with_range(self) -> None:
        responses = [
            _Response(error=IncompleteRead(b"part", 3)),
            _Response(payload=b"ial", status=206),
        ]

        with (
            patch.object(_http, "urlopen", side_effect=responses) as urlopen,
            patch.object(_http.time, "sleep") as sleep,
        ):
            result = _http.get("https://example.test/paper.pdf", retries=2)

        self.assertEqual(result, b"partial")
        second_request = urlopen.call_args_list[1].args[0]
        self.assertEqual(second_request.get_header("Range"), "bytes=4-")
        sleep.assert_called_once_with(1)


if __name__ == "__main__":
    unittest.main()
