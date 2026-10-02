#!/usr/bin/env python3
"""Render Figure 5 panel-first from retained results, without outcome reruns."""
from importlib import import_module
from fig5_plotting import render_furniture
def main():
    for letter in "abcdefghi": import_module(f"fig5{letter}").main()
    render_furniture()
    print("Nine native-size map panels and shared figure furniture rendered.")
if __name__=="__main__": main()
