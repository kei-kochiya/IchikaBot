import os

replacements = {
    "from utils.game_data": "from utils.data.game_data",
    "import utils.game_data": "import utils.data.game_data",
    "from utils import game_data": "from utils.data import game_data",
    
    "from utils.card_data": "from utils.data.card_data",
    "import utils.card_data": "import utils.data.card_data",
    "from utils import card_data": "from utils.data import card_data",
    
    "from utils.music_quiz_db": "from utils.data.music_quiz_db",
    "import utils.music_quiz_db": "import utils.data.music_quiz_db",
    "from utils import music_quiz_db": "from utils.data import music_quiz_db",
    
    "from utils.database": "from utils.core.database",
    "import utils.database": "import utils.core.database",
    "from utils import database": "from utils.core import database",
    
    "from utils.autoupdater": "from utils.core.autoupdater",
    "import utils.autoupdater": "import utils.core.autoupdater",
    "from utils import autoupdater": "from utils.core import autoupdater",
    
    "from utils.romaji": "from utils.core.romaji",
    "import utils.romaji": "import utils.core.romaji",
    "from utils import romaji": "from utils.core import romaji",
    
    "from utils.image_helper": "from utils.media.image_helper",
    "import utils.image_helper": "import utils.media.image_helper",
    "from utils import image_helper": "from utils.media import image_helper",
    
    "from utils.audio_fx": "from utils.media.audio_fx",
    "import utils.audio_fx": "import utils.media.audio_fx",
    "from utils import audio_fx": "from utils.media import audio_fx",
    
    "from utils.cards": "from utils.game.cards",
    "import utils.cards": "import utils.game.cards",
    "from utils import cards": "from utils.game import cards",
}

def process_file(path):
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    new_content = content
    for old, new in replacements.items():
        new_content = new_content.replace(old, new)
        
    if new_content != content:
        with open(path, 'w', encoding='utf-8') as f:
            f.write(new_content)
        print(f"Updated {path}")

# Process bot.py
process_file(r"d:\botTesting\bot.py")

# Process cogs/
for root, _, files in os.walk(r"d:\botTesting\cogs"):
    for file in files:
        if file.endswith(".py"):
            process_file(os.path.join(root, file))

# Process utils/
for root, _, files in os.walk(r"d:\botTesting\utils"):
    for file in files:
        if file.endswith(".py"):
            process_file(os.path.join(root, file))

print("Done!")
