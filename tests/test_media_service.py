import io
import threading

import pytest
from PIL import Image

from site_agent.application.media import MediaService
from site_agent.core.llm import LLMError
from site_agent.core.memory import Memory
from site_agent.core.media_worker import MediaWorker
from site_agent.core.media_contracts import MediaAnalysis
from site_agent.hands.opencode_runner import RunnerError, _materialize_media
from site_agent.hands.local_media import LocalMediaStore


class FakeStore:
    def __init__(self):
        self.objects = {}
        self.get_calls = []

    def put(self, key, data, content_type):
        self.objects[key] = (data, content_type)

    def get(self, key):
        self.get_calls.append(key)
        return self.objects[key][0]

    def delete(self, key):
        self.objects.pop(key, None)

    def signed_get_url(self, key, ttl_seconds):
        return "https://signed.invalid/" + key


class LocalUrlStore(FakeStore):
    def signed_get_url(self, key, ttl_seconds):
        return "/api/intake/media/object?key=" + key


class FakeAnalyzer:
    model = "qwen-test"

    def analyze_images(self, urls, instruction):
        return MediaAnalysis.from_mapping({
            "description": "A blue photo", "tags": ["blue"], "alt_text": "Blue photo",
            "orientation": "square", "dominant_colors": [], "suggested_uses": ["social post"],
            "quality_notes": [], "ocr_text": "", "knowledge_relevant": False,
        })


class SchemaFailingAnalyzer:
    model = "qwen-test"

    def analyze_images(self, urls, instruction):
        raise LLMError("invalid structured analysis", code="invalid_structured_analysis")


class BlockingAnalyzer(FakeAnalyzer):
    def __init__(self):
        self.started = threading.Event()
        self.release = threading.Event()

    def analyze_images(self, urls, instruction):
        self.started.set()
        assert self.release.wait(2)
        return super().analyze_images(urls, instruction)


class RecordingAnalyzer(FakeAnalyzer):
    def __init__(self, store):
        self.store = store
        self.urls = []
        self.image_sizes = []

    def analyze_images(self, urls, instruction):
        self.urls = list(urls)
        self.image_sizes = [Image.open(io.BytesIO(self.store.objects[url.split("signed.invalid/", 1)[1]][0])).size
                            for url in urls]
        return super().analyze_images(urls, instruction)


class UrlRecordingAnalyzer(FakeAnalyzer):
    def __init__(self):
        self.urls = []

    def analyze_images(self, urls, instruction):
        self.urls = list(urls)
        return super().analyze_images(urls, instruction)


def test_media_service_uploads_private_original_and_returns_safe_record(tmp_path):
    output = io.BytesIO()
    Image.new("RGB", (10, 10), "blue").save(output, format="JPEG")
    store = FakeStore()
    memory = Memory(tmp_path / "memory.db")
    service = MediaService(memory, store, {"site": {"media": {"enabled": True}}})

    result = service.upload("../menu photo.jpg", output.getvalue(), "image/jpeg")

    assert result["duplicate"] is False
    assert result["asset"]["status"] == "queued"
    assert result["asset"]["thumbnail_url"] is None
    assert len(store.objects) == 1
    assert all("original/" in key for key in store.objects)
    memory.close()


def test_media_service_deduplicates_and_restores_archived_asset(tmp_path):
    store = FakeStore()
    memory = Memory(tmp_path / "memory.db")
    service = MediaService(memory, store, {"site": {"media": {"enabled": True}}})
    data = b"%PDF-1.7\n"
    first = service.upload("menu.pdf", data, "application/pdf")
    asset_id = first["asset"]["id"]
    memory.update_media_asset(asset_id, archived_ts="later")

    second = service.upload("menu.pdf", data, "application/pdf")

    assert second["duplicate"] is True
    assert second["asset"]["archived"] is False
    assert len(store.objects) == 1
    memory.close()


def test_media_worker_normalizes_and_analyzes_once(tmp_path):
    output = io.BytesIO()
    Image.new("RGB", (20, 10), "blue").save(output, format="JPEG")
    memory = Memory(tmp_path / "memory.db")
    store = FakeStore()
    service = MediaService(memory, store, {"site": {"media": {"enabled": True}}})
    uploaded = service.upload("blue.jpg", output.getvalue())
    context = {"memory": memory, "media_store": store, "media_service": service, "media_analyzer": FakeAnalyzer()}
    worker = MediaWorker(context)
    assert worker.process_one() is True
    asset = memory.get_media_asset(uploaded["asset"]["id"])
    assert asset.status.value == "ready"
    assert asset.normalized_key and asset.thumbnail_key
    assert asset.description == "A blue photo"
    memory.close()


def test_media_worker_sends_a_small_temporary_webp_to_vision(tmp_path):
    output = io.BytesIO()
    Image.new("RGB", (2400, 1600), "blue").save(output, format="JPEG", quality=95)
    memory = Memory(tmp_path / "memory.db")
    store = FakeStore()
    service = MediaService(memory, store, {"site": {"media": {"enabled": True}}})
    uploaded = service.upload("blue.jpg", output.getvalue())
    analyzer = RecordingAnalyzer(store)
    worker = MediaWorker({"memory": memory, "media_store": store, "media_service": service,
                          "media_analyzer": analyzer})

    assert worker.process_one() is True
    assert len(analyzer.urls) == 1
    assert "/analysis/image.webp" in analyzer.urls[0]
    assert "/original/" not in analyzer.urls[0]
    assert analyzer.image_sizes == [(1600, 1067)]
    analysis_key = analyzer.urls[0].split("?", 1)[0].replace("https://signed.invalid/", "")
    assert analysis_key not in store.objects
    assert any("/normalized/image.webp" in key and value[1] == "image/webp"
               for key, value in store.objects.items())
    assert all("/analysis/" not in key for key in store.objects)
    memory.close()


def test_media_worker_converts_private_local_vision_urls_to_data_urls(tmp_path):
    output = io.BytesIO()
    Image.new("RGB", (20, 10), "blue").save(output, format="JPEG")
    memory = Memory(tmp_path / "memory.db")
    store = LocalUrlStore()
    service = MediaService(memory, store, {"site": {"media": {"enabled": True}}})
    uploaded = service.upload("blue.jpg", output.getvalue())
    analyzer = UrlRecordingAnalyzer()
    worker = MediaWorker({"memory": memory, "media_store": store, "media_service": service,
                          "media_analyzer": analyzer})

    assert worker.process_one() is True
    assert analyzer.urls[0].startswith("data:image/webp;base64,")
    assert memory.get_media_asset(uploaded["asset"]["id"]).status.value == "ready"
    memory.close()


def test_local_media_preview_reports_an_image_content_type(tmp_path):
    output = io.BytesIO()
    Image.new("RGB", (20, 10), "blue").save(output, format="JPEG")
    memory = Memory(tmp_path / "memory.db")
    store = LocalMediaStore(tmp_path / "media")
    service = MediaService(memory, store, {"site": {"media": {"enabled": True}}})
    uploaded = service.upload("blue.jpg", output.getvalue())

    assert MediaWorker({"memory": memory, "media_store": store, "media_service": service}).process_one() is True
    data, content_type = service.read_preview(uploaded["asset"]["id"], thumbnail=False)

    assert data
    assert content_type == "image/webp"
    memory.close()


def test_media_service_makes_a_bounded_advisor_image_data_url(tmp_path):
    output = io.BytesIO()
    Image.new("RGB", (1400, 900), "#e75c48").save(output, format="JPEG", quality=95)
    memory = Memory(tmp_path / "memory.db")
    store = FakeStore()
    service = MediaService(memory, store, {"site": {"media": {"enabled": True}}})
    uploaded = service.upload("brand-mark.jpg", output.getvalue())
    MediaWorker({"memory": memory, "media_store": store, "media_service": service}).process_one()

    data_url = service.advisor_image_data_url(uploaded["asset"]["id"])

    assert data_url is not None
    assert data_url.startswith("data:image/webp;base64,")
    assert len(data_url) < 2_500_000
    memory.close()


def test_media_worker_does_not_retry_invalid_analysis_schema(tmp_path):
    output = io.BytesIO()
    Image.new("RGB", (20, 10), "blue").save(output, format="JPEG")
    memory = Memory(tmp_path / "memory.db")
    store = FakeStore()
    service = MediaService(memory, store, {"site": {"media": {"enabled": True}}})
    uploaded = service.upload("blue.jpg", output.getvalue())
    context = {"memory": memory, "media_store": store, "media_service": service,
               "media_analyzer": SchemaFailingAnalyzer()}

    assert MediaWorker(context).process_one() is True
    asset = memory.get_media_asset(uploaded["asset"]["id"])
    assert asset.status.value == "ready"
    assert asset.analysis_status.value == "failed"
    assert asset.attempts == 1
    assert asset.normalized_key and asset.thumbnail_key
    assert "reader returned an unreadable result" in service.serialize(asset)["status_message"]
    memory.close()


def test_media_worker_waits_for_explicit_retry_after_non_retryable_analysis_failure(tmp_path):
    output = io.BytesIO()
    Image.new("RGB", (20, 10), "blue").save(output, format="JPEG")
    memory = Memory(tmp_path / "memory.db")
    store = FakeStore()
    service = MediaService(memory, store, {"site": {"media": {"enabled": True}}})
    uploaded = service.upload("blue.jpg", output.getvalue())
    analyzer = SchemaFailingAnalyzer()
    worker = MediaWorker({"memory": memory, "media_store": store, "media_service": service,
                          "media_analyzer": analyzer})

    assert worker.process_one() is True
    failed = memory.get_media_asset(uploaded["asset"]["id"])
    assert failed.analysis_status.value == "failed"
    assert failed.analysis_attempts == 1

    assert worker.process_one() is False
    unchanged = memory.get_media_asset(uploaded["asset"]["id"])
    assert unchanged.analysis_attempts == 1
    assert unchanged.analysis_status.value == "failed"
    memory.close()


def test_media_worker_retry_reuses_persisted_derivatives(tmp_path):
    output = io.BytesIO()
    Image.new("RGB", (20, 10), "blue").save(output, format="JPEG")
    memory = Memory(tmp_path / "memory.db")
    store = FakeStore()
    service = MediaService(memory, store, {"site": {"media": {"enabled": True}}})
    uploaded = service.upload("blue.jpg", output.getvalue())
    worker = MediaWorker({"memory": memory, "media_store": store, "media_service": service,
                          "media_analyzer": SchemaFailingAnalyzer()})

    assert worker.process_one() is True
    failed = memory.get_media_asset(uploaded["asset"]["id"])
    assert failed.status.value == "ready"
    assert failed.analysis_status.value == "failed"
    store.get_calls.clear()
    worker.analyzer = FakeAnalyzer()
    service.retry(failed.asset_id)

    assert worker.process_one() is True
    ready = memory.get_media_asset(failed.asset_id)
    assert ready.status.value == "ready"
    assert ready.original_key not in store.get_calls
    memory.close()


def test_media_worker_persists_preview_before_analysis_finishes(tmp_path):
    output = io.BytesIO()
    Image.new("RGB", (20, 10), "blue").save(output, format="JPEG")
    memory = Memory(tmp_path / "memory.db")
    store = FakeStore()
    service = MediaService(memory, store, {"site": {"media": {"enabled": True}}})
    uploaded = service.upload("blue.jpg", output.getvalue())
    analyzer = BlockingAnalyzer()
    worker = MediaWorker({"memory": memory, "media_store": store, "media_service": service,
                          "media_analyzer": analyzer})

    thread = threading.Thread(target=worker.process_one)
    thread.start()
    assert analyzer.started.wait(2)
    processing = memory.get_media_asset(uploaded["asset"]["id"])
    assert processing.status.value == "ready"
    assert processing.analysis_status.value == "processing"
    assert processing.normalized_key and processing.thumbnail_key
    assert service.serialize(processing)["thumbnail_url"]
    analyzer.release.set()
    thread.join(2)
    assert not thread.is_alive()
    memory.close()


def test_materialize_media_copies_only_ready_selected_websites_assets(tmp_path):
    output = io.BytesIO()
    Image.new("RGB", (20, 10), "blue").save(output, format="JPEG")
    memory = Memory(tmp_path / "memory.db")
    store = FakeStore()
    service = MediaService(memory, store, {"site": {"media": {"enabled": True, "site_asset_dir": "assets/images"}}})
    uploaded = service.upload("brand mark.jpg", output.getvalue())
    asset_id = uploaded["asset"]["id"]
    MediaWorker({"memory": memory, "media_store": store, "media_service": service}).process_one()
    clone = tmp_path / "clone"
    clone.mkdir()

    paths = _materialize_media(
        {"config": {"site": {"media": {"site_asset_dir": "assets/images"}}},
         "media_service": service, "_media_asset_ids": [asset_id]},
        clone,
    )

    assert paths == [f"assets/images/ada-{asset_id}-brand-mark.webp"]
    assert (clone / paths[0]).read_bytes() == store.objects[memory.get_media_asset(asset_id).normalized_key][0]
    memory.close()


def test_materialize_media_requires_a_configured_destination(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    store = FakeStore()
    service = MediaService(memory, store, {"site": {"media": {"enabled": True}}})

    with pytest.raises(RunnerError, match="site_asset_dir"):
        _materialize_media(
            {"config": {"site": {"media": {}}}, "media_service": service, "_media_asset_ids": [1]},
            tmp_path,
        )
    memory.close()


def test_media_service_transfers_ready_asset_through_provider_boundary(tmp_path):
    output = io.BytesIO()
    Image.new("RGB", (20, 10), "blue").save(output, format="JPEG")
    source_memory = Memory(tmp_path / "source.db")
    source_store = FakeStore()
    source = MediaService(source_memory, source_store, {"site": {"media": {"enabled": True}}})
    uploaded = source.upload("blue.jpg", output.getvalue())
    MediaWorker({"memory": source_memory, "media_store": source_store, "media_service": source}).process_one()

    target_memory = Memory(tmp_path / "target.db")
    target_store = FakeStore()
    target = MediaService(target_memory, target_store, {"site": {"media": {"enabled": False}}})
    source_asset, objects = source.export_asset(uploaded["asset"]["id"])
    imported = target.import_asset(source_asset, objects)

    assert imported.original_sha256 == source_asset.original_sha256
    assert target_memory.get_media_asset(imported.asset_id).status.value == "ready"
    assert {key: value[0] for key, value in target_store.objects.items()} == objects
    source_memory.close()
    target_memory.close()
