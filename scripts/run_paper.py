import os
import sys

# Ensure the src directory is in the path so `algodesk` can be imported
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))

from algodesk.runner import run_paper, build_parser

if __name__ == "__main__":
    args = build_parser().parse_args()
    args.mode = "paper"
    run_paper(args)