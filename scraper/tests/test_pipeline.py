import json
from pathlib import Path
import pytest
from unittest.mock import MagicMock, patch

from scraper.diff import compute_diff, update_changelog
from scraper.fetch import Fetcher
from scraper.pipeline import Pipeline, merge_soft_deleted_museums


def test_extract_list_page_next_data():
    sample_html = """
    <!DOCTYPE html>
    <html>
      <head>
        <script id="__NEXT_DATA__" type="application/json">
          {"buildId": "test-build-123", "props": {"pageProps": {"story": {"name": "Deelnemende musea"}}}}
        </script>
      </head>
      <body>Hello</body>
    </html>
    """
    fetcher = Fetcher()
    with patch.object(fetcher, "fetch_url", return_value=(200, sample_html.encode("utf-8"), {})):
        build_id, next_data = fetcher.fetch_list_page()
        assert build_id == "test-build-123"
        assert next_data["props"]["pageProps"]["story"]["name"] == "Deelnemende musea"


def test_build_id_404_refresh_and_retry():
    fetcher = Fetcher()

    old_build_id = "build-v1"
    new_build_id = "build-v2"
    slug = "huis-zypendaal"

    def mock_fetch_url(url, use_cache=True):
        if f"_next/data/{old_build_id}" in url:
            return 404, b"Not Found", {}
        elif "deelnemende-musea" in url:
            html = f'<script id="__NEXT_DATA__" type="application/json">{{"buildId": "{new_build_id}"}}</script>'
            return 200, html.encode("utf-8"), {}
        elif f"_next/data/{new_build_id}" in url:
            payload = {"pageProps": {"story": {"name": "Huis Zypendaal", "slug": slug}}}
            return 200, json.dumps(payload).encode("utf-8"), {}
        return 404, b"Not Found", {}

    with patch.object(fetcher, "fetch_url", side_effect=mock_fetch_url):
        story = fetcher.fetch_detail_story(slug, old_build_id)
        assert story is not None
        assert story["name"] == "Huis Zypendaal"
        assert story["slug"] == slug


def test_diff_and_changelog(tmp_path):
    changelog_file = tmp_path / "changelog.json"

    old_dataset = {
        "museums": [
            {"slug": "museum-a", "first_seen": "2026-09-01"},
            {"slug": "museum-b", "first_seen": "2026-09-01"},
        ]
    }
    new_museums = [
        {"slug": "museum-b"},
        {"slug": "museum-c"},
    ]

    diff = compute_diff(new_museums, old_dataset)
    assert diff["added"] == ["museum-c"]
    assert diff["removed"] == ["museum-a"]
    assert diff["retained"] == ["museum-b"]
    assert diff["old_first_seen"]["museum-b"] == "2026-09-01"

    entry = update_changelog(diff, total_count=2, changelog_path=changelog_file)
    assert entry["added"] == ["museum-c"]
    assert entry["removed"] == ["museum-a"]
    assert entry["total_count"] == 2

    # Verify changelog file
    with open(changelog_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert len(data["history"]) == 1
    assert data["history"][0]["added"] == ["museum-c"]


def test_pipeline_failure_path_preserves_old_data(tmp_path):
    museums_file = tmp_path / "museums.json"
    meta_file = tmp_path / "meta.json"

    # Pre-populate museums.json with existing good data
    initial_content = json.dumps({"source": {"name": "test"}, "museums": [{"slug": "good-museum"}]})
    museums_file.write_text(initial_content)

    pipeline = Pipeline()
    # Mock pipeline to return only 5 items (which fails validation as min count is 100)
    fake_list_data = {
        "buildId": "bid",
        "props": {
            "pageProps": {
                "story": {
                    "content": {
                        "body": [
                            {
                                "contentAreas": [
                                    {
                                        "content": [
                                            {
                                                "component": "all-articles",
                                                "articles": [
                                                    {"slug": f"m-{i}", "name": f"M {i}", "published_at": "2026-09-19", "content": {}}
                                                    for i in range(5)
                                                ],
                                            }
                                        ]
                                    }
                                ]
                            }
                        ]
                    }
                }
            }
        },
    }

    with patch.object(pipeline.fetcher, "fetch_list_page", return_value=("bid", fake_list_data)), \
         patch("scraper.pipeline.MUSEUMS_JSON_PATH", museums_file), \
         patch("scraper.pipeline.META_JSON_PATH", meta_file):

        with pytest.raises(ValueError) as excinfo:
            pipeline.run()

        assert "Dataset validation failed" in str(excinfo.value)
        # Verify previous museums.json was NOT overwritten or corrupted
        assert museums_file.read_text() == initial_content
        # Verify meta.json was NOT written
        assert not meta_file.exists()


def test_soft_delete_requires_two_consecutive_runs():
    """
    Verify that a missing museum is retained as status='active' (consecutive_missing=1)
    on its first missed run, and only transitions to status='removed' (consecutive_missing=2)
    after 2 consecutive missed runs. If it reappears, it returns to status='active' with 0.
    """
    initial_museums = [
        {"slug": "museum-a", "name": "Museum A", "status": "active", "consecutive_missing": 0},
        {"slug": "museum-b", "name": "Museum B", "status": "active", "consecutive_missing": 0},
    ]
    old_dataset = {"museums": initial_museums}

    # RUN 1: museum-b is absent in new scrape
    scrape_run_1 = [{"slug": "museum-a", "name": "Museum A"}]
    merged_1 = merge_soft_deleted_museums(scrape_run_1, old_dataset)

    by_slug_1 = {m["slug"]: m for m in merged_1}
    assert len(by_slug_1) == 2
    assert by_slug_1["museum-a"]["status"] == "active"
    assert by_slug_1["museum-a"]["consecutive_missing"] == 0

    # museum-b is missing for run 1 -> MUST STAY ACTIVE with consecutive_missing=1
    assert by_slug_1["museum-b"]["status"] == "active"
    assert by_slug_1["museum-b"]["consecutive_missing"] == 1

    # RUN 2: museum-b is absent again in 2nd consecutive run
    dataset_after_run_1 = {"museums": merged_1}
    scrape_run_2 = [{"slug": "museum-a", "name": "Museum A"}]
    merged_2 = merge_soft_deleted_museums(scrape_run_2, dataset_after_run_1)

    by_slug_2 = {m["slug"]: m for m in merged_2}
    assert len(by_slug_2) == 2
    # museum-b has now been absent for 2 consecutive runs -> MUST BE MARKED 'removed'
    assert by_slug_2["museum-b"]["status"] == "removed"
    assert by_slug_2["museum-b"]["consecutive_missing"] == 2

    # RUN 3: museum-b reappears in the source scrape!
    dataset_after_run_2 = {"museums": merged_2}
    scrape_run_3 = [
        {"slug": "museum-a", "name": "Museum A"},
        {"slug": "museum-b", "name": "Museum B"},
    ]
    merged_3 = merge_soft_deleted_museums(scrape_run_3, dataset_after_run_2)

    by_slug_3 = {m["slug"]: m for m in merged_3}
    assert len(by_slug_3) == 2
    # museum-b is resurrected to active with consecutive_missing=0
    assert by_slug_3["museum-b"]["status"] == "active"
    assert by_slug_3["museum-b"]["consecutive_missing"] == 0

