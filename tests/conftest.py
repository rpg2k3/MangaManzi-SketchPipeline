"""Shared pytest fixtures for the BetaStage smoke tests.

Tests are fully mocked — they never hit the real PixAI or Anthropic APIs.
- PixAI GraphQL traffic is intercepted via `respx`.
- Claude tool-use calls are short-circuited by patching
  `app.claude.client.call_with_tool` so we don't round-trip the SDK.
"""

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


@pytest.fixture
def tmp_data_root(tmp_path, monkeypatch):
    """Redirect data/sheets, data/history, data/outputs into a tmp dir."""
    sheets_dir = tmp_path / "data" / "sheets"
    history_dir = tmp_path / "data" / "history"
    outputs_dir = tmp_path / "data" / "outputs"
    sheets_dir.mkdir(parents=True)
    history_dir.mkdir(parents=True)
    outputs_dir.mkdir(parents=True)

    import app.critique.history as history_mod
    import app.pipeline.orchestrator as orch_mod
    import app.sheets.storage as storage_mod

    monkeypatch.setattr(storage_mod, "SHEETS_DIR", sheets_dir)
    monkeypatch.setattr(history_mod, "HISTORY_ROOT", history_dir)
    monkeypatch.setattr(orch_mod, "OUTPUTS_ROOT", outputs_dir)

    return tmp_path


@pytest.fixture
def sample_sheet():
    return {
        "id": "test_char",
        "character_id": "test_char",
        "name": "Test Char",
        "archetype": "F_yadult",
        "head_count": 7.5,
        "linkedLoraId": "char_lora_id_12345",
        "triggerWords": "test_char_trigger",
        "loraWeight": 0.9,
        "designNotes": "Testing harness character",
        "outfitVariants": [],
        "continuityRules": [],
        "learnedDrifts": [],
        "audit": [],
        "build": {"shoulder_width_heads": 1.7},
        "face": {"shape": "oval"},
        "hair": {"style": "short", "color": "black"},
        "outfit": {"top": "shirt"},
        "color_palette": {"primary": "#000000"},
    }


@pytest.fixture
def fake_critique():
    return {
        "drifts": [
            {"aspect": "head_proportion", "expected": "7.5 head-heights",
             "observed": "drifted to 7.0", "severity": "moderate"},
        ],
        "successes": ["pose locked correctly"],
        "suggestedPromptDeltas": ["explicitly reinforce 7.5 head-heights"],
    }


@pytest.fixture
def fake_prompt_payload():
    return {
        "prompts": "test_char_trigger, dynamic pose, anime style",
        "negative_prompts": "lowres, bad anatomy",
        "rationale": "Honors character LoRA trigger and prior critique.",
    }


@pytest.fixture
def patched_claude(monkeypatch, fake_critique, fake_prompt_payload):
    """Short-circuit Claude tool-use calls so tests don't hit the SDK."""
    def fake_call_with_tool(api_key, *, tool_name, **kwargs):
        if tool_name == "report_critique":
            return dict(fake_critique)
        if tool_name == "emit_prompt":
            return dict(fake_prompt_payload)
        if tool_name == "emit_patch":
            return {"operations": [], "audit_summary": "noop"}
        if tool_name == "emit_scene_plan":
            return {
                "subjects": [{"sheetId": "test_char", "role": "primary",
                              "lora_stack": ["9k9base", "sketch_lora", "char_lora_id_12345"]}],
                "prompt_skeleton": "skeleton",
                "suggested_control_nets": ["openpose", "depth"],
            }
        raise RuntimeError(f"Unmocked tool: {tool_name}")

    monkeypatch.setattr("app.claude.client.call_with_tool", fake_call_with_tool)
    monkeypatch.setattr("app.claude.prompts.call_with_tool", fake_call_with_tool)
    monkeypatch.setattr("app.claude.critique.call_with_tool", fake_call_with_tool)
    monkeypatch.setattr("app.claude.sheets.call_with_tool", fake_call_with_tool)
    monkeypatch.setattr("app.claude.scene.call_with_tool", fake_call_with_tool)


@pytest.fixture
def fake_pixai_responses():
    """Stateful canned responses for the PixAI GraphQL endpoint.

    Returns a dict with helpers and counters tests can reference.
    """
    state = {
        "tasks": {},  # task_id -> task dict
        "next_task_id": 1,
        "next_media_id": 1,
        "uploaded_external_ids": [],
        "media_payloads": {},  # media_id -> media dict
    }

    def make_media(media_id: str) -> dict:
        m = {
            "id": media_id,
            "type": "IMAGE",
            "width": 768,
            "height": 1280,
            "imageType": "PNG",
            "urls": [{"variant": "PUBLIC", "url": f"https://cdn.pixai.test/{media_id}.png"}],
        }
        state["media_payloads"][media_id] = m
        return m

    def graphql_handler(request):
        from httpx import Response
        body = json.loads(request.content)
        query = body.get("query", "")
        variables = body.get("variables") or {}

        if "mutation createGenerationTask" in query:
            tid = f"task-{state['next_task_id']}"
            state["next_task_id"] += 1
            mid = f"media-{state['next_media_id']}"
            state["next_media_id"] += 1
            make_media(mid)
            task = {
                "id": tid,
                "userId": "u-1",
                "parameters": variables.get("parameters"),
                "outputs": {"mediaId": mid},
                "status": "completed",
                "startedAt": "2026-05-01T00:00:00Z",
                "endAt": "2026-05-01T00:00:30Z",
                "createdAt": "2026-05-01T00:00:00Z",
                "updatedAt": "2026-05-01T00:00:30Z",
            }
            state["tasks"][tid] = task
            return Response(200, json={"data": {"createGenerationTask": task}})

        if "query getTaskById" in query:
            t = state["tasks"].get(variables.get("id"))
            return Response(200, json={"data": {"task": t}})

        if "query getMediaById" in query:
            m = state["media_payloads"].get(variables.get("id"))
            return Response(200, json={"data": {"media": m}})

        if "mutation cancelGenerationTask" in query:
            t = state["tasks"].get(variables.get("id"))
            if t:
                t["status"] = "cancelled"
            return Response(200, json={"data": {"cancelGenerationTask": t}})

        if "mutation uploadMedia" in query:
            inp = variables.get("input") or {}
            ext = inp.get("externalId")
            if ext is None:
                ext = f"ext-{len(state['uploaded_external_ids']) + 1}"
                state["uploaded_external_ids"].append(ext)
                return Response(200, json={"data": {"uploadMedia": {
                    "uploadUrl": f"https://upload.pixai.test/{ext}",
                    "externalId": ext,
                    "mediaId": None,
                    "media": None,
                }}})
            mid = f"upload-media-{ext}"
            make_media(mid)
            return Response(200, json={"data": {"uploadMedia": {
                "uploadUrl": None,
                "externalId": ext,
                "mediaId": mid,
                "media": state["media_payloads"][mid],
            }}})

        return Response(200, json={"data": None, "errors": [{"message": f"Unknown query: {query[:80]}"}]})

    state["graphql_handler"] = graphql_handler
    return state


@pytest.fixture
def respx_pixai(respx_mock, fake_pixai_responses):
    """Wire respx to intercept PixAI GraphQL + upload + download calls."""
    from httpx import Response

    respx_mock.post("https://api.pixai.art/graphql").mock(
        side_effect=fake_pixai_responses["graphql_handler"]
    )
    respx_mock.put(url__regex=r"https://upload\.pixai\.test/.*").mock(
        return_value=Response(200)
    )
    respx_mock.get(url__regex=r"https://cdn\.pixai\.test/.*\.png").mock(
        return_value=Response(200, content=b"\x89PNG\r\n\x1a\n_FAKEPNG_")
    )
    return respx_mock


@pytest.fixture(autouse=True)
def disable_pixai_polling_sleep(monkeypatch):
    """Make poll_until_complete return immediately in tests."""
    import app.pixai.polling as polling_mod
    monkeypatch.setattr(polling_mod.time, "sleep", lambda *_: None)


@pytest.fixture
def stub_skeleton(tmp_path):
    p = tmp_path / "skeleton.png"
    p.write_bytes(b"\x89PNG\r\n\x1a\n_SKELETON_")
    return p
