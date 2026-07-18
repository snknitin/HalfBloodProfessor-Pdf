"""Create or update the free Docker Space used by the production site."""

from pathlib import Path

from huggingface_hub import HfApi

REPO_ID = "NikeZoldyck/hb-pdf-engine"
ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    api = HfApi()
    api.create_repo(
        repo_id=REPO_ID,
        repo_type="space",
        space_sdk="docker",
        exist_ok=True,
    )
    api.upload_file(
        repo_id=REPO_ID,
        repo_type="space",
        path_or_fileobj=ROOT / "engine" / "README.space.md",
        path_in_repo="README.md",
        commit_message="Configure Docker Space",
    )
    api.upload_file(
        repo_id=REPO_ID,
        repo_type="space",
        path_or_fileobj=ROOT / "engine" / "Dockerfile.hf",
        path_in_repo="Dockerfile",
        commit_message="Add engine container",
    )
    api.upload_folder(
        repo_id=REPO_ID,
        repo_type="space",
        folder_path=ROOT / "app",
        path_in_repo="app",
        ignore_patterns=["**/__pycache__/**", "**/*.pyc"],
        commit_message="Upload deterministic renderer",
    )
    api.upload_folder(
        repo_id=REPO_ID,
        repo_type="space",
        folder_path=ROOT / "engine",
        path_in_repo="engine",
        ignore_patterns=[
            "node_modules/**",
            ".wrangler/**",
            "package-lock.json",
            "Dockerfile.hf",
            "README.space.md",
        ],
        commit_message="Upload annotation service",
    )
    print(f"Deployed source to https://huggingface.co/spaces/{REPO_ID}")


if __name__ == "__main__":
    main()
