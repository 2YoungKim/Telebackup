from gui.main import start_app
from gui.windows.welcome import WelcomeWindow
from utils import get_cached_client

if __name__ == '__main__':
    # Since this is the first time, it will be loaded and cached
    get_cached_client()
    start_app(WelcomeWindow)
