import os
from unittest.mock import patch
import main

# Mock time.sleep to run cycles instantly
def mock_sleep(seconds):
    pass

if __name__ == "__main__":
    import sys
    sys.argv = ["main.py", "--dry-run"]
    
    # Run 24 cycles
    cycles_left = 24
    
    original_sleep = main.time.sleep
    
    def conditional_sleep(seconds):
        global cycles_left
        if seconds > 10: # Poll sleep
            cycles_left -= 1
            if cycles_left <= 0:
                print("\n[TEST] 24 cycles completed. Exiting.")
                sys.exit(0)
        else: # Small gap sleep
            pass # ignore
            
    with patch("main.time.sleep", side_effect=conditional_sleep):
        main.main()
