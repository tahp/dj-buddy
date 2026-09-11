"""Separate console executable so frozen yt-dlp retains stdout and cancellation."""
import multiprocessing
import yt_dlp

if __name__ == '__main__':
    multiprocessing.freeze_support()
    yt_dlp.main()
