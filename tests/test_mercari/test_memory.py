import psutil

from mercari_scraper import ItemSource, MercariScraper


def test_memory_under_one_gigabyte():
    """Verify that scraping Mercari JP uses far less than 1GB of RAM."""
    proc = psutil.Process()
    ram_before_mb = proc.memory_info().rss / (1024 * 1024)

    with MercariScraper() as scraper:
        # Fetch 60 items across both individual and shops
        items = scraper.search("pikachu", source=ItemSource.ALL, limit=60)
        assert len(items) == 60

    ram_after_mb = proc.memory_info().rss / (1024 * 1024)
    peak_mb = max(ram_before_mb, ram_after_mb)

    print(
        f"\n[RAM BENCHMARK] Before: {ram_before_mb:.2f} MB, After: {ram_after_mb:.2f} MB, Peak: {peak_mb:.2f} MB"
    )

    # Hard constraint: strictly under 1024 MB (1 GB)
    assert peak_mb < 1024, f"RAM usage exceeded 1GB limit: {peak_mb} MB"
    # Scraper memory growth should be minimal (< 100 MB delta)
    ram_delta_mb = max(0.0, ram_after_mb - ram_before_mb)
    assert ram_delta_mb < 100, f"RAM growth higher than expected: {ram_delta_mb:.2f} MB"
