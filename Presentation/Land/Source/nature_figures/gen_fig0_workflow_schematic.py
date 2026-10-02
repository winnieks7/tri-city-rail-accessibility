#!/usr/bin/env python3
"""Build the Figure 1 study design panel-first; no research model runs."""
from importlib import import_module
from fig1_content import record,PANEL_NAMES
def main():
    record()
    for name in PANEL_NAMES.values():
        import_module(name).main()
    print("Five native-size conceptual panels and shared labels exported.")
if __name__=="__main__": main()
