#!/usr/bin/env python3
"""Render native-size Figure 2 panels. Assemble with fig2_assemble.py after QA."""
from fig2_data import record_values
from fig2a_geographical_setting import main as panel_a
from fig2b_baseline import main as panel_b
from fig2c_activations import main as panel_c

if __name__ == '__main__':
    record_values()
    panel_a()
    panel_b()
    panel_c()
