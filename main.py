"""Точка входу: python main.py [шлях до CSV/ZIP]"""
import sys

from app.app import main

if __name__ == "__main__":
    main(sys.argv[1:])
