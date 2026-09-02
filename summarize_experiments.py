import sys
import os
import subprocess

if __name__ == '__main__':
    script = os.path.join(os.path.dirname(__file__), 'scripts', 'summarize_experiments.py')
    sys.exit(subprocess.call([sys.executable, script] + sys.argv[1:]))
