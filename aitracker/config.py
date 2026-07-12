import os


PROJECTS = os.path.expanduser("~/.claude/projects")


_HERE = os.path.dirname(os.path.abspath(__file__))


FLAGS_FILE = os.path.join(_HERE, "flags.json")


TITLES_FILE = os.path.join(_HERE, "titles.json")


AUGMENT_DIR = os.path.expanduser("~/.augment")


TASKS_DIR = os.path.expanduser("~/.claude/tasks")


EDIT_TOOLS = {"Edit", "MultiEdit", "NotebookEdit"}


LIVE_WINDOW = 300


NARRATION_CAP = 40000


NARR_PAGE = 60          # narration entries per /api/session page + per /api/narration fetch


AUGGIE_SESSIONS = os.path.join(AUGMENT_DIR, "sessions")
