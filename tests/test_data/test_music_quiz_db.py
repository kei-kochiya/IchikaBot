from utils.data.music_quiz_db import MusicQuizDB, is_correct_guess, normalize


def test_normalize_function():
    assert normalize("Tell Your World!") == "tellyourworld"
    assert normalize("ロキ (Roki)") == "roki"
    assert normalize("39 - thank you") == "39thankyou"
    assert normalize("") == ""


def test_normalize_folds_unicode_before_the_ascii_filter():
    # Accented letters keep their base letter instead of vanishing
    assert normalize("Ángel") == "angel"
    assert normalize("Bocca della Verità") == "boccadellaverita"
    assert normalize("Fräulein=Ojousama") == "frauleinojousama"
    assert normalize("Tōkyō") == "tokyo"
    # Full-width / compatibility forms (e.g. typed with a Japanese IME) become plain ASCII
    assert normalize("ｔｅｌｌ　ｙｏｕｒ　ｗｏｒｌｄ") == "tellyourworld"
    assert normalize("PaⅢ.SENSATION") == "paiiisensation"
    # Guesses typed with accents still match plain titles
    assert is_correct_guess("Ángel", ["angel"]) is True


def test_is_correct_guess():
    targets = ["tellyourworld", "hibana"]

    # Exact match
    assert is_correct_guess("Tell Your World", targets) is True
    assert is_correct_guess("tellyourworld", targets) is True

    # Substring match (>= 3 chars)
    assert is_correct_guess("hiban", targets) is True
    assert is_correct_guess("world", targets) is True

    # False guess
    assert is_correct_guess("stella", targets) is False
    assert is_correct_guess("", targets) is False


def test_partial_guess_length_is_counted_after_normalizing():
    targets = ["hibana", "needle"]
    # Spaces and punctuation don't count towards the 3 characters
    assert is_correct_guess("e  ", targets) is False  # 1 char: "e"
    assert is_correct_guess("  e  e  ", targets) is False  # 2 chars: "ee"
    assert is_correct_guess("h i", targets) is False  # 2 chars: "hi"
    assert is_correct_guess("n.e", targets) is False
    # ...but they don't stop a real 3+ character guess either
    assert is_correct_guess("h i b", targets) is True  # "hib"
    assert is_correct_guess("need-", targets) is True


def test_music_quiz_db_instance():
    db = MusicQuizDB.get_instance()
    assert len(db._db) > 500

    # Test song info extraction
    sample_key = list(db._db.keys())[0]
    info = db.get_song_info(f"{sample_key}.mp3")
    assert isinstance(info, dict)
    assert "title_jp" in info or "title_en" in info

    # Test display builders
    display = db.build_display_answer(info)
    assert len(display) > 0

    norm_targets = db.build_norm_targets(info)
    assert isinstance(norm_targets, list)
    assert len(norm_targets) > 0

    # Test commission queries
    comm_ids = db.get_commission_ids()
    assert len(comm_ids) >= 200
    assert db.is_commission("54") is True  # Ready Steady
    assert db.is_commission("54.mp3") is True
    assert db.is_commission("1") is False  # Tell Your World
    assert db.is_commission("1.mp3") is False


def test_build_reveal():
    info = {"title_en": "Lower one's eyes", "romaji_title": "Lower", "title_jp": "ロウワー"}
    reveal = MusicQuizDB.build_reveal(info)
    assert reveal == "🎵 **Lower one's eyes**"
    assert "🔤" not in reveal

    info_jp = {"title_en": None, "romaji_title": None, "title_jp": "ロウワー"}
    assert MusicQuizDB.build_reveal(info_jp) == "🎵 **ロウワー**"
