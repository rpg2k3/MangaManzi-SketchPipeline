"""PixAI HTTP client smoke tests."""

import json

import pytest

from app.pixai import PixAIClient, TaskParameters, LoraSpec, ControlNetSpec
from app.pixai.client import media_ids_from_task


def test_taskparameters_to_pixai_dict_uses_camelcase():
    p = TaskParameters(
        prompts="hello world",
        negative_prompts="bad",
        loras=[LoraSpec(model_id="lora-1", weight=0.8)],
        control_nets=[ControlNetSpec(type="openpose", media_id="m-1")],
        media_id="init-img",
        strength=0.5,
        priority="high",
    )
    d = p.to_pixai_dict()
    assert d["prompts"] == "hello world"
    assert d["negativePrompts"] == "bad"
    assert d["samplingMethod"] == "DPM++ 2M Karras"
    # Phase 1B baseline: 832x1216 portrait, CFG 6.0, 26 steps.
    assert d["samplingSteps"] == 26
    assert d["cfgScale"] == 6.0
    assert d["width"] == 832
    assert d["height"] == 1216
    # PixAI's lora field is an object keyed by model id, not an array.
    assert d["lora"] == {"lora-1": 0.8}
    assert d["controlNets"] == [{"type": "openpose", "mediaId": "m-1", "weight": 1.0}]
    assert d["mediaId"] == "init-img"
    assert d["strength"] == 0.5
    assert d["priority"] == "high"


def test_create_generation_task_round_trip(respx_pixai, fake_pixai_responses):
    with PixAIClient(api_key="sk-test") as client:
        task = client.create_generation_task({"prompts": "x"})
    assert task["id"] == "task-1"
    assert task["status"] == "completed"
    assert task["outputs"]["mediaId"] == "media-1"


def test_get_task_by_id_round_trip(respx_pixai, fake_pixai_responses):
    with PixAIClient(api_key="sk-test") as client:
        client.create_generation_task({"prompts": "x"})
        task = client.get_task_by_id("task-1")
    assert task["id"] == "task-1"
    assert task["status"] == "completed"


def test_authorization_header_sent(respx_pixai, fake_pixai_responses):
    with PixAIClient(api_key="sk-mytestkey") as client:
        client.create_generation_task({"prompts": "x"})
    request = respx_pixai.calls.last.request
    assert request.headers["authorization"] == "Bearer sk-mytestkey"
    assert request.headers["content-type"] == "application/json"
    body = json.loads(request.content)
    assert "createGenerationTask" in body["query"]
    assert body["variables"]["parameters"]["prompts"] == "x"


def test_media_ids_from_task_single_and_batch():
    assert media_ids_from_task({"outputs": {"mediaId": "m-1"}}) == ["m-1"]
    assert media_ids_from_task({"outputs": {"batch": [{"mediaId": "m-2"}, {"mediaId": "m-3"}]}}) == ["m-2", "m-3"]
    assert media_ids_from_task({}) == []
    assert media_ids_from_task({"outputs": None}) == []


def test_upload_media_file_round_trip(respx_pixai, stub_skeleton, fake_pixai_responses):
    with PixAIClient(api_key="sk-test") as client:
        media_id = client.upload_media_file(stub_skeleton)
    assert media_id.startswith("upload-media-ext-")
    # Two uploadMedia mutations + one PUT happened
    upload_mutations = [
        c for c in respx_pixai.calls
        if c.request.url == "https://api.pixai.art/graphql"
        and "uploadMedia" in json.loads(c.request.content)["query"]
    ]
    assert len(upload_mutations) == 2
    s3_puts = [c for c in respx_pixai.calls if c.request.method == "PUT"]
    assert len(s3_puts) == 1


def test_download_media_returns_bytes(respx_pixai, fake_pixai_responses):
    with PixAIClient(api_key="sk-test") as client:
        client.create_generation_task({"prompts": "x"})
        media = client.get_media_by_id("media-1")
        body = client.download_media(media)
    assert body.startswith(b"\x89PNG")


def test_test_connection_treats_invalid_id_format_as_ok(respx_mock):
    """PixAI's "Invalid ID format" response proves auth made it through —
    the request reached the resolver, the resolver only rejected the input.
    """
    from httpx import Response
    from app.pixai.client import test_connection
    respx_mock.post("https://api.pixai.art/graphql").mock(
        return_value=Response(200, json={"errors": [{"message": "Invalid ID format"}]})
    )
    status, msg = test_connection("sk-pixai-test")
    assert status == "ok"


def test_test_connection_treats_not_found_as_ok(respx_mock):
    from httpx import Response
    from app.pixai.client import test_connection
    respx_mock.post("https://api.pixai.art/graphql").mock(
        return_value=Response(200, json={"errors": [{"message": "Task not found"}]})
    )
    status, _ = test_connection("sk-pixai-test")
    assert status == "ok"


def test_test_connection_treats_null_task_as_ok(respx_mock):
    from httpx import Response
    from app.pixai.client import test_connection
    respx_mock.post("https://api.pixai.art/graphql").mock(
        return_value=Response(200, json={"data": {"task": None}})
    )
    status, _ = test_connection("sk-pixai-test")
    assert status == "ok"


def test_test_connection_returns_invalid_on_401(respx_mock):
    from httpx import Response
    from app.pixai.client import test_connection
    respx_mock.post("https://api.pixai.art/graphql").mock(
        return_value=Response(401, json={"errors": [{"message": "Unauthorized"}]})
    )
    status, _ = test_connection("sk-bad")
    assert status == "invalid"
