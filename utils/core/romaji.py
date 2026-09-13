"""
Romaji conversion utilities for Japanese text search support.
Converts between hiragana, katakana, and romaji.
"""

# Hiragana to Romaji mapping
HIRAGANA_TO_ROMAJI = {
    # Basic vowels
    'あ': 'a', 'い': 'i', 'う': 'u', 'え': 'e', 'お': 'o',
    # K-row
    'か': 'ka', 'き': 'ki', 'く': 'ku', 'け': 'ke', 'こ': 'ko',
    'が': 'ga', 'ぎ': 'gi', 'ぐ': 'gu', 'げ': 'ge', 'ご': 'go',
    # S-row
    'さ': 'sa', 'し': 'shi', 'す': 'su', 'せ': 'se', 'そ': 'so',
    'ざ': 'za', 'じ': 'ji', 'ず': 'zu', 'ぜ': 'ze', 'ぞ': 'zo',
    # T-row
    'た': 'ta', 'ち': 'chi', 'つ': 'tsu', 'て': 'te', 'と': 'to',
    'だ': 'da', 'ぢ': 'di', 'づ': 'du', 'で': 'de', 'ど': 'do',
    # N-row
    'な': 'na', 'に': 'ni', 'ぬ': 'nu', 'ね': 'ne', 'の': 'no',
    # H-row
    'は': 'ha', 'ひ': 'hi', 'ふ': 'fu', 'へ': 'he', 'ほ': 'ho',
    'ば': 'ba', 'び': 'bi', 'ぶ': 'bu', 'べ': 'be', 'ぼ': 'bo',
    'ぱ': 'pa', 'ぴ': 'pi', 'ぷ': 'pu', 'ぺ': 'pe', 'ぽ': 'po',
    # M-row
    'ま': 'ma', 'み': 'mi', 'む': 'mu', 'め': 'me', 'も': 'mo',
    # Y-row
    'や': 'ya', 'ゆ': 'yu', 'よ': 'yo',
    # R-row
    'ら': 'ra', 'り': 'ri', 'る': 'ru', 'れ': 're', 'ろ': 'ro',
    # W-row
    'わ': 'wa', 'を': 'wo', 'ん': 'n',
    # Small characters
    'ゃ': 'ya', 'ゅ': 'yu', 'ょ': 'yo',
    'ぁ': 'a', 'ぃ': 'i', 'ぅ': 'u', 'ぇ': 'e', 'ぉ': 'o',
    'っ': '',  # Double consonant marker, handled specially
    # Long vowel
    'ー': '',
}

# Katakana to Romaji mapping (same sounds, different characters)
KATAKANA_TO_ROMAJI = {
    # Basic vowels
    'ア': 'a', 'イ': 'i', 'ウ': 'u', 'エ': 'e', 'オ': 'o',
    # K-row
    'カ': 'ka', 'キ': 'ki', 'ク': 'ku', 'ケ': 'ke', 'コ': 'ko',
    'ガ': 'ga', 'ギ': 'gi', 'グ': 'gu', 'ゲ': 'ge', 'ゴ': 'go',
    # S-row
    'サ': 'sa', 'シ': 'shi', 'ス': 'su', 'セ': 'se', 'ソ': 'so',
    'ザ': 'za', 'ジ': 'ji', 'ズ': 'zu', 'ゼ': 'ze', 'ゾ': 'zo',
    # T-row
    'タ': 'ta', 'チ': 'chi', 'ツ': 'tsu', 'テ': 'te', 'ト': 'to',
    'ダ': 'da', 'ヂ': 'di', 'ヅ': 'du', 'デ': 'de', 'ド': 'do',
    # N-row
    'ナ': 'na', 'ニ': 'ni', 'ヌ': 'nu', 'ネ': 'ne', 'ノ': 'no',
    # H-row
    'ハ': 'ha', 'ヒ': 'hi', 'フ': 'fu', 'ヘ': 'he', 'ホ': 'ho',
    'バ': 'ba', 'ビ': 'bi', 'ブ': 'bu', 'ベ': 'be', 'ボ': 'bo',
    'パ': 'pa', 'ピ': 'pi', 'プ': 'pu', 'ペ': 'pe', 'ポ': 'po',
    # M-row
    'マ': 'ma', 'ミ': 'mi', 'ム': 'mu', 'メ': 'me', 'モ': 'mo',
    # Y-row
    'ヤ': 'ya', 'ユ': 'yu', 'ヨ': 'yo',
    # R-row
    'ラ': 'ra', 'リ': 'ri', 'ル': 'ru', 'レ': 're', 'ロ': 'ro',
    # W-row
    'ワ': 'wa', 'ヲ': 'wo', 'ン': 'n',
    # Small characters
    'ャ': 'ya', 'ュ': 'yu', 'ョ': 'yo',
    'ァ': 'a', 'ィ': 'i', 'ゥ': 'u', 'ェ': 'e', 'ォ': 'o',
    'ッ': '',  # Double consonant marker
    # Extended katakana
    'ヴ': 'vu', 'ファ': 'fa', 'フィ': 'fi', 'フェ': 'fe', 'フォ': 'fo',
    'ティ': 'ti', 'ディ': 'di', 'トゥ': 'tu', 'ドゥ': 'du',
    # Long vowel
    'ー': '',
}

# Combination characters (must be checked before single chars)
COMBINATIONS_HIRA = {
    'きゃ': 'kya', 'きゅ': 'kyu', 'きょ': 'kyo',
    'しゃ': 'sha', 'しゅ': 'shu', 'しょ': 'sho',
    'ちゃ': 'cha', 'ちゅ': 'chu', 'ちょ': 'cho',
    'にゃ': 'nya', 'にゅ': 'nyu', 'にょ': 'nyo',
    'ひゃ': 'hya', 'ひゅ': 'hyu', 'ひょ': 'hyo',
    'みゃ': 'mya', 'みゅ': 'myu', 'みょ': 'myo',
    'りゃ': 'rya', 'りゅ': 'ryu', 'りょ': 'ryo',
    'ぎゃ': 'gya', 'ぎゅ': 'gyu', 'ぎょ': 'gyo',
    'じゃ': 'ja', 'じゅ': 'ju', 'じょ': 'jo',
    'びゃ': 'bya', 'びゅ': 'byu', 'びょ': 'byo',
    'ぴゃ': 'pya', 'ぴゅ': 'pyu', 'ぴょ': 'pyo',
    # Extended combinations
    'てぃ': 'ti', 'でぃ': 'di', 'ふぁ': 'fa', 'ふぃ': 'fi', 'ふぇ': 'fe', 'ふぉ': 'fo',
    'じぇ': 'je', 'しぇ': 'she', 'ちぇ': 'che',
}

COMBINATIONS_KATA = {
    'キャ': 'kya', 'キュ': 'kyu', 'キョ': 'kyo',
    'シャ': 'sha', 'シュ': 'shu', 'ショ': 'sho',
    'チャ': 'cha', 'チュ': 'chu', 'チョ': 'cho',
    'ニャ': 'nya', 'ニュ': 'nyu', 'ニョ': 'nyo',
    'ヒャ': 'hya', 'ヒュ': 'hyu', 'ヒョ': 'hyo',
    'ミャ': 'mya', 'ミュ': 'myu', 'ミョ': 'myo',
    'リャ': 'rya', 'リュ': 'ryu', 'リョ': 'ryo',
    'ギャ': 'gya', 'ギュ': 'gyu', 'ギョ': 'gyo',
    'ジャ': 'ja', 'ジュ': 'ju', 'ジョ': 'jo',
    'ビャ': 'bya', 'ビュ': 'byu', 'ビョ': 'byo',
    'ピャ': 'pya', 'ピュ': 'pyu', 'ピョ': 'pyo',
    # Extended combinations
    'ティ': 'ti', 'ディ': 'di', 'ファ': 'fa', 'フィ': 'fi', 'フェ': 'fe', 'フォ': 'fo',
    'ウィ': 'wi', 'ウェ': 'we', 'ウォ': 'wo',
    'ジェ': 'je', 'シェ': 'she', 'チェ': 'che',
}


def hiragana_to_romaji(text: str) -> str:
    """Convert hiragana text to romaji."""
    if not text:
        return ''
    
    result = []
    i = 0
    
    while i < len(text):
        # Check for っ (double consonant)
        if text[i] == 'っ' and i + 1 < len(text):
            next_char = text[i + 1]
            if next_char in HIRAGANA_TO_ROMAJI:
                romaji = HIRAGANA_TO_ROMAJI.get(next_char, '')
                if romaji:
                    result.append(romaji[0])  # Double first consonant
            i += 1
            continue
        
        # Check for 2-char combinations first
        if i + 1 < len(text):
            combo = text[i:i+2]
            if combo in COMBINATIONS_HIRA:
                result.append(COMBINATIONS_HIRA[combo])
                i += 2
                continue
        
        # Single character
        char = text[i]
        if char in HIRAGANA_TO_ROMAJI:
            result.append(HIRAGANA_TO_ROMAJI[char])
        else:
            result.append(char)  # Keep non-hiragana as-is
        i += 1
    
    return ''.join(result)


def katakana_to_romaji(text: str) -> str:
    """Convert katakana text to romaji."""
    if not text:
        return ''
    
    result = []
    i = 0
    
    while i < len(text):
        # Check for ッ (double consonant)
        if text[i] == 'ッ' and i + 1 < len(text):
            next_char = text[i + 1]
            if next_char in KATAKANA_TO_ROMAJI:
                romaji = KATAKANA_TO_ROMAJI.get(next_char, '')
                if romaji:
                    result.append(romaji[0])  # Double first consonant
            i += 1
            continue
        
        # Check for 2-char combinations first
        if i + 1 < len(text):
            combo = text[i:i+2]
            if combo in COMBINATIONS_KATA:
                result.append(COMBINATIONS_KATA[combo])
                i += 2
                continue
        
        # Single character
        char = text[i]
        if char in KATAKANA_TO_ROMAJI:
            result.append(KATAKANA_TO_ROMAJI[char])
        else:
            result.append(char)  # Keep non-katakana as-is
        i += 1
    
    return ''.join(result)


def to_romaji(text: str) -> str:
    """Convert any Japanese text (hiragana/katakana) to romaji."""
    if not text:
        return ''
    
    # First convert katakana, then hiragana
    result = katakana_to_romaji(text)
    result = hiragana_to_romaji(result)
    
    return result.lower()


def normalize_for_search(text: str) -> str:
    """
    Normalize text for search comparison.
    Converts Japanese to romaji and lowercases everything.
    """
    if not text:
        return ''
    
    # Convert to romaji and lowercase
    romaji = to_romaji(text)
    
    # Remove common separators and spaces for fuzzy matching
    normalized = romaji.replace(' ', '').replace('-', '').replace('_', '')
    
    return normalized.lower()


def matches_query(query: str, *fields: str) -> bool:
    """
    Check if a query matches any of the given fields.
    Supports romaji, hiragana, katakana, and English.
    """
    query_normalized = normalize_for_search(query)
    
    for field in fields:
        if not field:
            continue
        
        # Check direct match (case-insensitive)
        if query.lower() in field.lower():
            return True
        
        # Check romaji match
        field_normalized = normalize_for_search(field)
        if query_normalized in field_normalized:
            return True
    
    return False
