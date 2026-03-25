#!/usr/bin/env bash
set -e
echo "Installing YTScrapper dependencies..."
pip install -r requirements.txt
echo ""
echo "Done! Run the scraper with:"
echo "  python main.py"
