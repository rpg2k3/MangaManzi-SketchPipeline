"""PixAI GraphQL HTTP client.

GraphQL strings (createGenerationTask, getTaskById, getMediaById,
cancelGenerationTask, TaskBase + MediaBase fragments) are taken
verbatim from the official PixAI JS client to stay in lockstep with
their server-side schema.
"""

import httpx

from .debug_log import log_response
from .defaults import GRAPHQL_ENDPOINT
from .errors import PixAIAuthError, PixAIError

_TASK_FRAGMENT = """
fragment TaskBase on Task {
  id userId parameters outputs status startedAt endAt createdAt updatedAt
}
"""

_MEDIA_FRAGMENT = """
fragment MediaBase on Media {
  id type width height urls { variant url } imageType
}
"""

_CREATE_GENERATION_TASK = _TASK_FRAGMENT + """
mutation createGenerationTask($parameters: JSONObject!) {
  createGenerationTask(parameters: $parameters) { ...TaskBase }
}
"""

_GET_TASK_BY_ID = _TASK_FRAGMENT + """
query getTaskById($id: ID!) {
  task(id: $id) { ...TaskBase }
}
"""

_GET_MEDIA_BY_ID = _MEDIA_FRAGMENT + """
query getMediaById($id: String!) {
  media(id: $id) { ...MediaBase }
}
"""

_CANCEL_GENERATION_TASK = _TASK_FRAGMENT + """
mutation cancelGenerationTask($id: ID!) {
  cancelGenerationTask(id: $id) { ...TaskBase }
}
"""

_UPLOAD_MEDIA = _MEDIA_FRAGMENT + """
mutation uploadMedia($input: UploadMediaInput!) {
  uploadMedia(input: $input) {
    uploadUrl
    externalId
    mediaId
    media { ...MediaBase }
  }
}
"""

_MIME_BY_EXT = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}


class PixAIClient:
    def __init__(
        self,
        api_key: str,
        endpoint: str = GRAPHQL_ENDPOINT,
        timeout: float = 30.0,
        http_client: httpx.Client | None = None,
    ):
        self._api_key = api_key
        self._endpoint = endpoint
        self._owns_http = http_client is None
        self._http = http_client or httpx.Client(
            timeout=timeout,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "User-Agent": "9LivesK9/0.1",
            },
        )

    def close(self):
        if self._owns_http:
            self._http.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def _request(self, query: str, variables: dict, operation: str) -> dict:
        body = {"query": query, "variables": variables}
        # Capture outgoing request alongside responses so failures like
        # "Validation Failed: task parameters /lora" can be diffed against
        # the actual payload we sent.
        log_response(f"{operation}:REQUEST", 0, body)
        try:
            res = self._http.post(self._endpoint, json=body)
        except httpx.HTTPError as e:
            raise PixAIError(f"HTTP error during {operation}: {e}") from e

        try:
            data = res.json()
        except ValueError:
            log_response(operation, res.status_code, res.text)
            raise PixAIError(
                f"Non-JSON response from {operation} (status {res.status_code}): "
                f"{res.text[:300]}"
            )

        log_response(operation, res.status_code, data)

        if res.status_code in (401, 403):
            raise PixAIAuthError(f"Auth failed on {operation}: {data}")
        if data.get("errors"):
            msg = data["errors"][0].get("message", "GraphQL error")
            raise PixAIError(f"{operation} failed: {msg}")
        if "data" not in data:
            raise PixAIError(f"Unexpected response from {operation}: {data}")
        return data["data"]

    def create_generation_task(self, params: dict) -> dict:
        d = self._request(_CREATE_GENERATION_TASK, {"parameters": params}, "createGenerationTask")
        return d["createGenerationTask"]

    def get_task_by_id(self, task_id: str) -> dict | None:
        """Return the task dict, or None if PixAI replies `data.task: null`.

        Null is observed when (a) the task hasn't propagated to the read DB
        yet — transient — or (b) PixAI's worker rejected the task post-validation
        (e.g. unsupported `modelId`) — terminal. Polling treats a few null
        replies as transient before failing.
        """
        d = self._request(_GET_TASK_BY_ID, {"id": task_id}, "getTaskById")
        return d.get("task")

    def get_media_by_id(self, media_id: str) -> dict:
        d = self._request(_GET_MEDIA_BY_ID, {"id": media_id}, "getMediaById")
        return d["media"]

    def cancel_generation_task(self, task_id: str) -> dict:
        d = self._request(_CANCEL_GENERATION_TASK, {"id": task_id}, "cancelGenerationTask")
        return d["cancelGenerationTask"]

    def upload_media_file(self, file_path) -> str:
        """Upload an image file to PixAI's S3 backing store. Returns mediaId.

        Flow (matches the official JS client):
          1. uploadMedia mutation with {type: Image, provider: S3} → uploadUrl + externalId.
          2. HTTP PUT the file bytes to uploadUrl.
          3. uploadMedia mutation again with externalId to finalize → returns mediaId.
        """
        from pathlib import Path as _P

        path = _P(file_path)
        if not path.exists():
            raise PixAIError(f"Upload source not found: {path}")
        mime = _MIME_BY_EXT.get(path.suffix.lower(), "image/png")

        d = self._request(
            _UPLOAD_MEDIA,
            {"input": {"type": "IMAGE", "provider": "S3"}},
            "uploadMedia:requestUrl",
        )
        info = d["uploadMedia"]
        upload_url = info.get("uploadUrl")
        external_id = info.get("externalId")
        if not upload_url:
            raise PixAIError("uploadMedia did not return an uploadUrl")

        body = path.read_bytes()
        with httpx.Client(timeout=120.0) as anon:
            put = anon.put(upload_url, content=body, headers={"Content-Type": mime})
            put.raise_for_status()

        d2 = self._request(
            _UPLOAD_MEDIA,
            {"input": {"type": "IMAGE", "provider": "S3", "externalId": external_id}},
            "uploadMedia:register",
        )
        media_id = d2["uploadMedia"].get("mediaId")
        if not media_id:
            raise PixAIError("uploadMedia register step did not return mediaId")
        return media_id

    def public_url_of(self, media: dict) -> str | None:
        urls = media.get("urls") or []
        for u in urls:
            if u.get("variant") == "PUBLIC":
                return u.get("url")
        return urls[0].get("url") if urls else None

    def download_media(self, media: dict) -> bytes:
        url = self.public_url_of(media)
        if not url:
            raise PixAIError("Media has no public URL")
        with httpx.Client(timeout=120.0) as anon:
            r = anon.get(url)
            r.raise_for_status()
            return r.content


def media_ids_from_task(task: dict) -> list[str]:
    """Extract media IDs from a completed task. Handles both single and batch outputs."""
    outputs = task.get("outputs") or {}
    if isinstance(outputs.get("batch"), list):
        return [item["mediaId"] for item in outputs["batch"] if item.get("mediaId")]
    if outputs.get("mediaId"):
        return [outputs["mediaId"]]
    return []


def test_connection(api_key: str) -> tuple[str, str]:
    """Validate PixAI key. Returns (status, message).

    Strategy: issue a minimal `getTaskById` with a sentinel id. The auth
    header is processed before the resolver runs, so any response other
    than 401/403 proves the key is valid. Possible non-auth outcomes:
      - PixAI returns {task: null} → no error path → "ok"
      - PixAI returns "Invalid ID format" / "not found" / similar →
        input-validation error caught here and treated as "ok"
      - Any unexpected error → "warning" (reachable but odd)
    """
    sentinel = "00000000-0000-0000-0000-000000000000"
    try:
        with PixAIClient(api_key=api_key) as client:
            client._request(_GET_TASK_BY_ID, {"id": sentinel}, "test_connection")
        return ("ok", "Connected.")
    except PixAIAuthError as e:
        return ("invalid", f"Invalid API key: {str(e)[:120]}")
    except PixAIError as e:
        msg = str(e).lower()
        ok_patterns = (
            "invalid id", "invalid format", "not found", "no task",
            "no such task", "does not exist", "task not found",
        )
        if any(p in msg for p in ok_patterns):
            return ("ok", "Connected.")
        return ("warning", f"Reachable but: {str(e)[:120]}")
    except Exception as e:
        return ("error", f"Connection failed: {str(e)[:100]}")
