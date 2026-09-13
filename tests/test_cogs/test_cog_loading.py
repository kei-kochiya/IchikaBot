import os
import pytest
from pathlib import Path


@pytest.mark.asyncio
async def test_all_cogs_load(mock_bot):
    cogs_dir = Path("cogs")
    assert cogs_dir.exists(), "cogs directory must exist"

    loaded_cogs = []
    failed_cogs = []

    for root, dirs, files in os.walk(cogs_dir):
        for filename in files:
            if filename.endswith(".py") and not filename.startswith("__"):
                relative_path = os.path.relpath(os.path.join(root, filename), ".")
                module_name = relative_path.replace(os.path.sep, ".")[:-3]

                try:
                    await mock_bot.load_extension(module_name)
                    loaded_cogs.append(module_name)
                except Exception as e:
                    failed_cogs.append((module_name, str(e)))

    assert len(failed_cogs) == 0, f"Failed to load cogs: {failed_cogs}"
    assert len(loaded_cogs) >= 15, f"Expected at least 15 cogs, but loaded {len(loaded_cogs)}"

    # Test clean cog unloading
    for module_name in loaded_cogs:
        await mock_bot.unload_extension(module_name)
