from unittest.mock import MagicMock

from cogs.system.help import COMMAND_CATEGORIES, HelpCog


def test_category_lookup_ignores_case_and_spaces():
    cog = HelpCog(MagicMock())

    assert cog.create_help_embed("card & gacha").title == "Card & Gacha"
    assert cog.create_help_embed("CardOfTheDay").title == "Card of the Day"
    assert cog.create_help_embed("no such thing").title == "Danh sách lệnh"


def test_command_forms_have_no_dangling_placeholders():
    cog = HelpCog(MagicMock())

    for category in COMMAND_CATEGORIES:
        for field in cog.create_help_embed(category).fields:
            assert "`-`" not in field.value and " / " not in field.value, field.value


def test_overview_lists_the_commands_themselves():
    overview = HelpCog(MagicMock()).create_help_embed(None)
    values = " ".join(field.value for field in overview.fields)

    for command in ("`/gacha pull`", "`/songguess`", "`!sgv`", "`/mercari`"):
        assert command in values
    assert "!sync" not in values  # owner-only: not for everyone's help
