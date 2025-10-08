"""Sound notification system for liquidation alerts."""
import os
import platform
import subprocess
import threading
import sys
from typing import Optional, Tuple
import logging
from pathlib import Path

# Try to import required modules
PLAYSOUND_AVAILABLE = False
SOUND_SYSTEM = None

try:
    if sys.platform == 'darwin':
        # On macOS, use AppKit for better reliability
        import AppKit
        SOUND_SYSTEM = 'appkit'
        PLAYSOUND_AVAILABLE = True
    else:
        # On other platforms, try playsound
        from playsound import playsound
        SOUND_SYSTEM = 'playsound'
        PLAYSOUND_AVAILABLE = True
except ImportError as e:
    import warnings
    warnings.warn(f"Sound notifications may not work properly: {e}")
    
    # Try to install required packages
    if sys.platform == 'darwin':
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "pyobjc"])
            import AppKit
            SOUND_SYSTEM = 'appkit'
            PLAYSOUND_AVAILABLE = True
        except:
            warnings.warn("Failed to install pyobjc. Sound notifications will be disabled.")
    else:
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "playsound==1.2.2"])
            from playsound import playsound
            SOUND_SYSTEM = 'playsound'
            PLAYSOUND_AVAILABLE = True
        except:
            warnings.warn("Failed to install playsound. Sound notifications will be disabled.")

logger = logging.getLogger(__name__)

class SoundNotifier:
    """Handles playing sound notifications for important events."""
    
    def __init__(self, enabled: bool = True):
        """Initialize the sound notifier.
        
        Args:
            enabled: Whether sound notifications are enabled
        """
        self.enabled = enabled and PLAYSOUND_AVAILABLE
        self.sound_file = self._get_default_sound_file()
        
        if not PLAYSOUND_AVAILABLE and enabled:
            logger.warning("Sound notifications are enabled but playsound module is not available. "
                         "Install it with: pip install playsound==1.2.2")
    
    def _get_default_sound_file(self) -> Optional[str]:
        """Get the path to the default sound file.
        
        Returns:
            Path to the sound file or None if not found
        """
        # Try to find a system sound
        system = platform.system().lower()
        
        if system == 'darwin':  # macOS
            sound_path = "/System/Library/Sounds/Ping.aiff"
            if os.path.exists(sound_path):
                return sound_path
            
            # Try another common sound
            sound_path = "/System/Library/Sounds/Glass.aiff"
            if os.path.exists(sound_path):
                return sound_path
                
        elif system == 'windows':
            # Windows system sounds
            sound_path = os.path.join(os.environ.get('WINDIR', 'C:\\Windows'), 'Media', 'Windows Notify.wav')
            if os.path.exists(sound_path):
                return sound_path
                
            sound_path = os.path.join(os.environ.get('WINDIR', 'C:\\Windows'), 'Media', 'Alarm01.wav')
            if os.path.exists(sound_path):
                return sound_path
                
        elif system == 'linux':
            # Common Linux sound locations
            possible_paths = [
                '/usr/share/sounds/freedesktop/stereo/message.oga',
                '/usr/share/sounds/gnome/default/alerts/glass.ogg',
                '/usr/share/sounds/ubuntu/notifications/Positive.ogg'
            ]
            
            for path in possible_paths:
                if os.path.exists(path):
                    return path
        
        # If no system sound found, use a simple beep as fallback
        return None
    
    def play_sound(self, sound_file: Optional[str] = None) -> None:
        """Play a sound file in a non-blocking way.
        
        Args:
            sound_file: Path to the sound file to play. If None, uses the default sound.
        """
        if not self.enabled or not PLAYSOUND_AVAILABLE:
            return
            
        sound_to_play = sound_file or self.sound_file
        
        def _play():
            try:
                if SOUND_SYSTEM == 'appkit':
                    # Use AppKit for macOS
                    import AppKit
                    if sound_to_play and os.path.exists(sound_to_play):
                        sound = AppKit.NSSound.alloc().initWithContentsOfFile_byReference_(sound_to_play, True)
                        if sound:
                            sound.play()
                        else:
                            raise Exception("Failed to load sound file")
                    else:
                        # System beep
                        AppKit.NSBeep()
                        
                elif SOUND_SYSTEM == 'playsound':
                    # Use playsound for other platforms
                    if sound_to_play and os.path.exists(sound_to_play):
                        playsound(sound_to_play, block=False)
                    else:
                        # Fallback to system beep
                        print('\a', end='', flush=True)  # ASCII bell character
                        
                else:
                    # Fallback to system beep if no sound system is available
                    print('\a', end='', flush=True)
                    
            except Exception as e:
                logger.warning(f"Failed to play sound: {e}")
                # Try system beep as last resort
                try:
                    print('\a', end='', flush=True)
                except:
                    pass
        
        # Play sound in a separate thread to avoid blocking
        thread = threading.Thread(target=_play, daemon=True)
        thread.start()

# Global sound notifier instance
sound_notifier = SoundNotifier(enabled=True)

def play_liquidation_sound():
    """Play the liquidation alert sound."""
    sound_notifier.play_sound()
