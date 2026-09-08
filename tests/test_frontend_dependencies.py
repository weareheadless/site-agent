import base64
import hashlib
import io
import tarfile

import pytest

import site_agent.hands.frontend_dependencies as dependencies
from site_agent.hands.frontend_dependencies import (
    ApprovedFrontendLibrary,
    FrontendDependencyError,
    available_frontend_libraries,
    materialize_frontend_libraries,
)


def _archive(tmp_path, files):
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w:gz") as package:
        for path, content in files.items():
            info = tarfile.TarInfo(f"package/{path}")
            info.size = len(content)
            package.addfile(info, io.BytesIO(content))
    archive = tmp_path / "gsap-3.12.5.tgz"
    archive.write_bytes(stream.getvalue())
    return archive


def test_materialize_frontend_libraries_uses_pinned_verified_files(tmp_path, monkeypatch):
    archive = _archive(tmp_path, {
        "dist/gsap.min.js": b"gsap-runtime",
        "dist/ScrollTrigger.min.js": b"scroll-trigger-runtime",
    })
    digest = base64.b64encode(hashlib.sha512(archive.read_bytes()).digest()).decode("ascii")
    monkeypatch.setitem(
        dependencies.APPROVED_FRONTEND_LIBRARIES,
        "gsap",
        ApprovedFrontendLibrary(
            name="gsap",
            package="gsap",
            version="3.12.5",
            integrity=f"sha512-{digest}",
            files=(
                ("dist/gsap.min.js", "public/vendor/gsap/gsap.min.js"),
                ("dist/ScrollTrigger.min.js", "public/vendor/gsap/ScrollTrigger.min.js"),
            ),
        ),
    )
    monkeypatch.setattr(dependencies, "_pack", lambda *args, **kwargs: archive)

    result = materialize_frontend_libraries(
        {"design_engine": {"libraries": {"gsap": {"enabled": True}}}},
        {"enabled": True, "libraries": ["gsap"]},
        tmp_path / "cache",
    )

    assert result.files["public/vendor/gsap/gsap.min.js"] == b"gsap-runtime"
    assert result.files["public/vendor/gsap/ScrollTrigger.min.js"] == b"scroll-trigger-runtime"
    assert result.libraries[0]["version"] == "3.12.5"


def test_materialize_frontend_libraries_rejects_unapproved_package(tmp_path):
    with pytest.raises(FrontendDependencyError, match="not approved"):
        materialize_frontend_libraries(
            {"design_engine": {"libraries": {"random-package": True}}},
            {"enabled": True},
            tmp_path / "cache",
        )


def test_materialize_frontend_libraries_skips_disabled_motion(tmp_path):
    result = materialize_frontend_libraries(
        {"design_engine": {"libraries": {"gsap": True}}},
        {"enabled": False},
        tmp_path / "cache",
    )

    assert result.files == {}


def test_materialize_frontend_libraries_respects_empty_model_selection(tmp_path, monkeypatch):
    monkeypatch.setattr(dependencies, "_pack", lambda *args, **kwargs: pytest.fail("unrequested library was downloaded"))

    result = materialize_frontend_libraries(
        {"design_engine": {"libraries": {"gsap": True}}},
        {"enabled": True, "libraries": []},
        tmp_path / "cache",
    )

    assert result.files == {}


def test_materialize_frontend_libraries_adds_instance_required_library(tmp_path, monkeypatch):
    archive = _archive(tmp_path, {
        "dist/gsap.min.js": b"gsap-runtime",
        "dist/ScrollTrigger.min.js": b"scroll-trigger-runtime",
    })
    digest = base64.b64encode(hashlib.sha512(archive.read_bytes()).digest()).decode("ascii")
    monkeypatch.setitem(
        dependencies.APPROVED_FRONTEND_LIBRARIES,
        "gsap",
        ApprovedFrontendLibrary(
            name="gsap",
            package="gsap",
            version="3.12.5",
            integrity=f"sha512-{digest}",
            files=(
                ("dist/gsap.min.js", "public/vendor/gsap/gsap.min.js"),
                ("dist/ScrollTrigger.min.js", "public/vendor/gsap/ScrollTrigger.min.js"),
            ),
        ),
    )
    monkeypatch.setattr(dependencies, "_pack", lambda *args, **kwargs: archive)

    result = materialize_frontend_libraries(
        {"design_engine": {"libraries": {"gsap": {"enabled": True, "required": True}}}},
        {"enabled": True, "libraries": []},
        tmp_path / "cache",
    )

    assert sorted(result.files) == [
        "public/vendor/gsap/ScrollTrigger.min.js",
        "public/vendor/gsap/gsap.min.js",
    ]


def test_materialize_frontend_libraries_rejects_unavailable_model_request(tmp_path):
    with pytest.raises(FrontendDependencyError, match="not available"):
        materialize_frontend_libraries(
            {"design_engine": {"libraries": {"gsap": True}}},
            {"enabled": True, "libraries": ["motion-one"]},
            tmp_path / "cache",
        )


def test_available_frontend_libraries_describes_enabled_host_allowlist():
    result = available_frontend_libraries({"design_engine": {"libraries": {"gsap": True}}})

    assert result == [{
        "name": "gsap",
        "package": "gsap",
        "version": "3.12.5",
        "capabilities": ["timelines", "scroll-linked animation", "ScrollTrigger", "Flip", "Observer", "Draggable"],
        "required": False,
    }]
