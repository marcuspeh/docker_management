"""The error envelope, its status mapping, and static hosting."""

from __future__ import annotations

import pytest

from app.errors import CODE_STATUS, ApiError, ErrorCode
from app.schemas import RepoOut


class TestErrorEnvelope:
    @pytest.mark.parametrize("code", sorted(CODE_STATUS))
    def test_every_code_has_a_status(self, code):
        assert isinstance(CODE_STATUS[code], int)

    def test_payload_shape_is_stable(self):
        """The frontend raises one ApiError against this exact shape."""
        payload = ApiError(ErrorCode.NOT_CLONED, "nope", {"field": "path"}).to_payload()
        assert set(payload) == {"error"}
        assert set(payload["error"]) == {"code", "message", "detail"}
        assert payload["error"]["code"] == "NOT_CLONED"
        assert payload["error"]["detail"] == {"field": "path"}

    @pytest.mark.parametrize(
        "code,status",
        [
            (ErrorCode.INVALID_PATH, 400),
            (ErrorCode.INVALID_NAME, 400),
            (ErrorCode.REPO_UNREACHABLE, 400),
            (ErrorCode.PROTECTED, 403),
            (ErrorCode.NOT_FOUND, 404),
            (ErrorCode.NAME_TAKEN, 409),
            (ErrorCode.NOT_CLONED, 409),
            (ErrorCode.DEPLOY_IN_PROGRESS, 409),
            (ErrorCode.DOCKER_ERROR, 502),
            (ErrorCode.GIT_ERROR, 502),
        ],
    )
    def test_status_mapping(self, code, status):
        assert ApiError(code, "x").status_code == status

    def test_detail_defaults_to_empty_dict(self):
        assert ApiError(ErrorCode.NOT_FOUND, "x").detail == {}


class TestCamelCase:
    def test_response_uses_camel_case(self):
        repo = RepoOut(
            id="1",
            name="n",
            url="u",
            path="/",
            compose_file="docker-compose.yml",
            default_branch="main",
            cloned=False,
            last_deployment=None,
            created_at="2026-01-01T00:00:00Z",
        )
        payload = repo.model_dump(by_alias=True, mode="json")
        assert "composeFile" in payload
        assert "defaultBranch" in payload
        assert "compose_file" not in payload

    def test_accepts_field_names_too(self):
        repo = RepoOut(
            id="1", name="n", url="u", path="/", compose_file="c.yml",
            default_branch=None, cloned=False, last_deployment=None,
            created_at="2026-01-01T00:00:00Z",
        )
        assert repo.compose_file == "c.yml"


class TestErrorResponses:
    def test_unknown_route_uses_envelope(self, client):
        r = client.get("/api/does-not-exist")
        assert r.status_code == 404
        assert r.json()["error"]["code"] == ErrorCode.NOT_FOUND

    def test_validation_error_names_the_field(self, client):
        r = client.post("/api/scm/repos", json={"url": "file:///x"})
        assert r.status_code == 400
        assert r.json()["error"]["code"] == ErrorCode.INVALID_NAME
        assert "field" in r.json()["error"]["detail"]


class TestStaticHosting:
    @pytest.fixture(autouse=True)
    def _dist(self, tmp_path, monkeypatch):
        for app, marker in (("scm", "SCM"), ("containers", "CONTAINERS")):
            d = tmp_path / app
            (d / "assets").mkdir(parents=True)
            (d / "index.html").write_text(f"<html>{marker}</html>")
            (d / "assets" / "index-abc123.js").write_text("console.log(1)")

        from app import config

        monkeypatch.setattr(config.settings, "scm_dist_dir", tmp_path / "scm")
        monkeypatch.setattr(config.settings, "containers_dist_dir", tmp_path / "containers")
        self.tmp_path = tmp_path

    def _client(self):
        """Build a fresh app so it picks up the patched dist directories."""
        from fastapi.testclient import TestClient

        from app.main import create_app

        return TestClient(create_app())

    def test_root_redirects_to_scm(self):
        with self._client() as c:
            r = c.get("/", follow_redirects=False)
        assert r.status_code in (307, 302)
        assert r.headers["location"] == "/scm/"

    @pytest.mark.parametrize("base,marker", [("/scm", "SCM"), ("/containers", "CONTAINERS")])
    def test_each_app_served_at_its_base(self, base, marker):
        with self._client() as c:
            r = c.get(f"{base}/")
        assert r.status_code == 200
        assert marker in r.text

    @pytest.mark.parametrize("base,marker", [("/scm", "SCM"), ("/containers", "CONTAINERS")])
    def test_deep_link_falls_back_to_own_index(self, base, marker):
        """A client-side route must return that app's index, not the other's."""
        with self._client() as c:
            r = c.get(f"{base}/some/deep/link")
        assert r.status_code == 200
        assert marker in r.text

    def test_index_is_not_cached(self):
        with self._client() as c:
            r = c.get("/scm/")
        assert r.headers["cache-control"] == "no-cache"

    def test_hashed_assets_are_immutable(self):
        with self._client() as c:
            r = c.get("/scm/assets/index-abc123.js")
        assert r.status_code == 200
        assert "immutable" in r.headers["cache-control"]

    def test_apps_do_not_leak_into_each_other(self):
        with self._client() as c:
            assert "CONTAINERS" not in c.get("/scm/anything").text
            assert "SCM" not in c.get("/containers/anything").text

    def test_missing_app_returns_404_envelope(self, tmp_path, monkeypatch):
        """Either app can be hosted elsewhere; the rest keeps working."""
        from fastapi.testclient import TestClient

        from app import config
        from app.main import create_app

        monkeypatch.setattr(
            config.settings, "containers_dist_dir", tmp_path / "not-built"
        )
        with TestClient(create_app()) as c:
            r = c.get("/containers/")
            assert r.status_code == 404
            assert r.json()["error"]["code"] == ErrorCode.NOT_FOUND
            # The other app and the API are unaffected.
            assert c.get("/scm/").status_code == 200
            assert c.get("/api/health").status_code == 200