"""Git command construction, path safety and remote parsing."""

from __future__ import annotations

import pytest

from app.errors import ApiError, ErrorCode
from app.services import compose_service, git_service


class TestSlug:
    @pytest.mark.parametrize(
        "name,expected",
        [
            ("My App", "my-app"),
            ("web  service", "web-service"),
            ("UPPER", "upper"),
            ("a--b", "a-b"),
            ("-trimmed-", "trimmed"),
            ("v2_api", "v2-api"),
        ],
    )
    def test_slugify(self, name, expected):
        assert git_service.slugify(name) == expected

    @pytest.mark.parametrize("name", ["", "   ", "!!!", "---"])
    def test_slugify_rejects_unusable(self, name):
        with pytest.raises(ApiError) as exc:
            git_service.slugify(name)
        assert exc.value.code == ErrorCode.INVALID_NAME

    def test_slug_respects_max_length(self):
        assert len(git_service.slugify("x" * 200)) <= git_service.MAX_SLUG_LENGTH


class TestPathSafety:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("/", "/"),
            ("", "/"),
            (None, "/"),
            ("/app", "/app"),
            ("app", "/app"),
            ("/app/", "/app"),
            ("app//sub", "/app/sub"),
            ("./app", "/app"),
        ],
    )
    def test_normalize(self, raw, expected):
        assert git_service.normalize_path(raw) == expected

    @pytest.mark.parametrize("raw", ["../etc", "/app/../../etc", ".."])
    def test_escape_rejected(self, raw):
        """A path must never resolve outside the clone."""
        with pytest.raises(ApiError) as exc:
            git_service.normalize_path(raw)
        assert exc.value.code == ErrorCode.INVALID_PATH

    @pytest.mark.parametrize("raw", ["sub/dir.yml", "..", "."])
    def test_compose_file_must_be_a_filename(self, raw):
        with pytest.raises(ApiError) as exc:
            git_service.validate_compose_file(raw)
        assert exc.value.code == ErrorCode.INVALID_PATH

    def test_empty_compose_file_falls_back_to_default(self):
        assert git_service.validate_compose_file("") == "docker-compose.yml"

    def test_compose_file_defaults(self):
        assert git_service.validate_compose_file(None) == "docker-compose.yml"
        assert git_service.validate_compose_file(" docker.yml ") == "docker.yml"


class TestComposeArgv:
    def test_shape_and_project_directory(self):
        argv = compose_service.compose_argv(
            "my-app", "/srv/api", "docker-compose.yml", "build", "--progress", "plain"
        )
        assert argv[:3] == ["docker", "compose", "-p"]
        assert argv[3] == "my-app"
        assert "-f" in argv and "--project-directory" in argv

        compose_path = argv[argv.index("-f") + 1]
        project_dir = argv[argv.index("--project-directory") + 1]
        # The project directory is what makes relative bind mounts in the
        # compose file resolve on the host.
        assert compose_path == f"{project_dir}/docker-compose.yml"
        assert project_dir.endswith("/srv/api")

    def test_root_path_uses_clone_root(self):
        argv = compose_service.compose_argv("my-app", "/", "docker-compose.yml", "up")
        project_dir = argv[argv.index("--project-directory") + 1]
        assert project_dir.endswith("/my-app")


class TestLsRemoteParsing:
    def test_default_branch_and_heads(self):
        output = (
            "ref: refs/heads/main\tHEAD\n"
            "abc123\tHEAD\n"
            "abc123\trefs/heads/main\n"
            "def456\trefs/heads/develop\n"
            "fff000\trefs/tags/v1.0.0\n"
        )
        default, branches = git_service.parse_ls_remote(output)
        assert default == "main"
        # Tags are not branches.
        assert branches == {"main": "abc123", "develop": "def456"}

    def test_no_symref_yields_no_default(self):
        default, branches = git_service.parse_ls_remote("abc123\trefs/heads/main\n")
        assert default is None
        assert branches == {"main": "abc123"}


class TestGitEnv:
    def test_credentials_never_prompt(self):
        """A missing credential must fail fast rather than hang the request."""
        assert git_service.GIT_ENV["GIT_TERMINAL_PROMPT"] == "0"
        assert "BatchMode=yes" in git_service.GIT_ENV["GIT_SSH_COMMAND"]


class TestLocalRepoOperations:
    async def test_clone_fetch_checkout_and_rev_parse(self, bare_repo, tmp_path):
        dest = tmp_path / "clone"
        await git_service.clone(str(bare_repo), dest)
        assert (dest / ".git").exists()

        sha = await git_service.rev_parse(dest)
        assert len(sha) == 40

        subject = await git_service.commit_subject(dest)
        assert subject == "first commit"

        await git_service.checkout_branch(dest, "develop")
        remotes = git_service.run_git(["remote"], cwd=dest)
        assert "origin" in remotes.stdout

    async def test_checkout_missing_branch_fails(self, bare_repo, tmp_path):
        from app.errors import ApiError

        dest = tmp_path / "clone"
        await git_service.clone(str(bare_repo), dest)
        with pytest.raises(ApiError) as exc:
            await git_service.checkout_branch(dest, "nope")
        assert exc.value.code == ErrorCode.GIT_ERROR

    async def test_ls_remote_rejects_unreachable(self):
        with pytest.raises(ApiError) as exc:
            await git_service.ls_remote("file:///definitely/not/here.git")
        assert exc.value.code == ErrorCode.REPO_UNREACHABLE

    async def test_list_branches_reads_remote(self, bare_repo):
        branches = await git_service.list_branches(str(bare_repo))
        assert {b["name"] for b in branches} == {"main", "develop"}

    async def test_log_commits(self, bare_repo, tmp_path):
        dest = tmp_path / "clone"
        await git_service.clone(str(bare_repo), dest)
        commits = await git_service.log_commits(dest, "main", limit=5)
        assert commits and commits[0]["subject"] == "first commit"
        assert commits[0]["author"] == "t"